"""v1.2 新增：統一 Evidence Validation 結果彙總（agent/filters/validation.py）＋
`assign_evidence_ids` 的建構期隔離閘門（真正的 Invalid Evidence quarantine，
不是只有 dedup 降權）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.filters.source_weights import WeightBreakdown
from agent.filters.validation import build_validation_certificate, build_validation_results
from agent.orchestrator import assign_evidence_ids
from agent.schemas import Evidence, EvidenceDraft, FilterDecision, FilterVerdict, HorizonClass, now_iso


def _ev(ev_id: str = "ev-001", injection_flag: str | None = None) -> Evidence:
    return Evidence(
        id=ev_id,
        coin="BTC",
        source="test-source",
        fetched_at=now_iso(),
        content_reference="Price reference value=100",
        related_claim="claim",
        source_type="price",
        source_weight=0.5,
        injection_flag=injection_flag,
    )


class TestBuildValidationResults:
    def test_uses_breakdown_final_weight_and_grade_when_present(self):
        ev = _ev()
        breakdowns = {
            "ev-001": WeightBreakdown(
                evidence_id="ev-001", formula="four_factor", final_weight=0.82, level_name="A+"
            )
        }
        [result] = build_validation_results([ev], breakdowns, [])

        assert result.evidence_id == "ev-001"
        assert result.source_reliability == 0.82
        assert result.source_grade == "A+"
        assert result.timestamp_valid is True
        assert result.injection_flag is None
        assert result.dedup_verdict is None
        assert result.data_integrity_ok is True

    def test_falls_back_to_evidence_source_weight_when_no_breakdown(self):
        ev = _ev()
        [result] = build_validation_results([ev], {}, [])
        assert result.source_reliability == 0.5
        assert result.source_grade == ""

    def test_carries_injection_flag_from_evidence(self):
        ev = _ev(injection_flag="high")
        [result] = build_validation_results([ev], {}, [])
        assert result.injection_flag == "high"

    def test_carries_dedup_verdict_from_filter_decisions(self):
        ev = _ev()
        decisions = [
            FilterDecision(
                evidence_id="ev-001", check_code="DEDUP", verdict=FilterVerdict.REMOVED, reason="重複"
            ),
            # 非 DEDUP 的決策不該被誤讀成 dedup_verdict
            FilterDecision(
                evidence_id="ev-001", check_code="PR", verdict=FilterVerdict.DOWNWEIGHTED, reason="話術"
            ),
        ]
        [result] = build_validation_results([ev], {}, decisions)
        assert result.dedup_verdict == "removed"

    def test_multiple_evidences_each_get_their_own_result(self):
        evs = [_ev("ev-001"), _ev("ev-002")]
        results = build_validation_results(evs, {}, [])
        assert [r.evidence_id for r in results] == ["ev-001", "ev-002"]

    def test_stale_timestamp_is_degraded_not_silently_valid(self):
        old = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ev = _ev()
        ev.fetched_at = old
        [result] = build_validation_results([ev], {}, [])
        assert result.status == "DEGRADED"
        assert result.checks["timestamp"].status == "warn"
        assert result.timestamp_valid is False
        assert "並非本次即時抓取" in result.checks["timestamp"].reason

    def test_fact_grounding_is_per_evidence_with_fact_ids(self):
        ev = _ev()
        ev.content_reference = "RSI14=45.2"
        facts = [{"summary": "RSI14 為 45.2", "evidence_ids": ["ev-001"]}]
        [result] = build_validation_results([ev], {}, [], facts=facts)
        check = result.checks["fact_grounding"]
        assert check.status == "pass"
        assert check.fact_ids == ["fact-001"]

    def test_pre_schema_quarantine_is_in_certificate_main_results(self):
        results = build_validation_results(
            [_ev()],
            {},
            [],
            quarantined_drafts=[
                {
                    "index": 2,
                    "coin": "BTC",
                    "source": "broken",
                    "source_type": "price",
                    "content_reference": "bad payload",
                    "reason": "ValidationError: invalid source_type",
                }
            ],
        )
        certificate = build_validation_certificate(results)
        assert certificate["schema_version"] == "2.0"
        assert certificate["summary"]["invalid"] == 1
        quarantined = certificate["results"][1]
        assert quarantined["evidence_id"] == "quarantine:draft:002"
        assert quarantined["status"] == "INVALID"
        assert quarantined["pre_schema_quarantine"] is True
        assert quarantined["checks"]["schema"]["status"] == "fail"

    def test_invalid_data_integrity_blocks_record(self):
        ev = _ev()
        ev.source_weight = float("nan")
        [result] = build_validation_results([ev], {}, [])
        assert result.status == "INVALID"
        assert result.checks["data_integrity"].status == "fail"

    def test_narrative_integrity_requires_traceable_url(self):
        ev = _ev()
        ev.source_type = "news"
        ev.content_reference = "A sufficiently long narrative item without a traceable source URL."
        [result] = build_validation_results([ev], {}, [])
        check = result.checks["data_integrity"]
        assert check.status == "warn"
        assert result.data_integrity_ok is False
        assert check.details["policy"] == "narrative"
        assert check.details["has_traceable_url"] is False

    def test_timestamp_reports_large_question_horizon_mismatch(self):
        ev = _ev()
        [result] = build_validation_results(
            [ev], {}, [], primary_horizon=HorizonClass.STRUCTURAL
        )
        check = result.checks["timestamp"]
        assert check.status == "warn"
        assert check.details["horizon_alignment"] == "supplemental"
        assert check.details["horizon_gap"] == 4


def _draft(**overrides) -> EvidenceDraft:
    base = dict(
        coin="BTC",
        source="x",
        fetched_at="2026-07-25T00:00:00Z",
        content_reference="x",
        related_claim="x",
        source_type="price",
    )
    base.update(overrides)
    return EvidenceDraft(**base)


class _RecordingLogger:
    def __init__(self):
        self.entries = []

    def log(self, **kwargs):
        self.entries.append(kwargs)


class TestAssignEvidenceIdsQuarantine:
    """`Evidence(id=..., **payload)` 建構失敗時，以前完全沒有防護——任何一筆
    壞資料會讓 pydantic ValidationError 直接炸穿整條 pipeline。"""

    def test_malformed_draft_is_quarantined_not_raised(self, monkeypatch):
        """用一個會讓 Evidence() 建構失敗的 payload 驗證：不拋例外，改為隔離。"""
        good = _draft()
        bad = _draft()
        # source_weight 超出常理範圍不會擋（沒有 schema 邊界），這裡改用
        # monkeypatch 讓其中一筆的 model_dump 回傳缺必要欄位的 payload，
        # 模擬「collector 給出結構不完整的草稿」。
        original_dump = EvidenceDraft.model_dump

        call_count = {"n": 0}

        def flaky_dump(self, *args, **kwargs):
            call_count["n"] += 1
            payload = original_dump(self, *args, **kwargs)
            if call_count["n"] == 2:
                payload["source_type"] = "not_a_real_source_type"
            return payload

        monkeypatch.setattr(EvidenceDraft, "model_dump", flaky_dump)

        logger = _RecordingLogger()
        evidences, quarantined = assign_evidence_ids([good, bad], logger=logger)

        assert len(evidences) == 1
        assert len(quarantined) == 1
        assert quarantined[0]["source"] == "x"
        assert "reason" in quarantined[0]
        quarantine_logs = [e for e in logger.entries if e.get("action") == "evidence_quarantined"]
        assert len(quarantine_logs) == 1

    def test_all_valid_drafts_produce_no_quarantine(self):
        evidences, quarantined = assign_evidence_ids([_draft(), _draft()])
        assert len(evidences) == 2
        assert quarantined == []

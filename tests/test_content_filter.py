"""Tests for agent/filters/content.py — L2 拉盤話術（R12-4）＋F9 情緒分布（詞典法）。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.filters.content import (
    F9_STATUS,
    PR_TERMS,
    apply_content_filters,
    check_pr_language,
    check_sentiment_distribution,
    scan_pr_terms,
)
from agent.filters.source_weights import apply_source_weights
from agent.logging_utils import ExecutionLogger
from agent.schemas import Evidence, FilterVerdict, PipelineLayer, SourceType


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_evidence(
    ev_id: str = "ev-001",
    content: str = "BTC price is rising steadily",
    source_type: SourceType = SourceType.NEWS,
    source_weight: float = 0.60,
    source: str = "CoinDesk RSS",
) -> Evidence:
    return Evidence(
        id=ev_id,
        coin="BTC",
        source=source,
        source_url=None,
        fetched_at=_now_iso(),
        content_reference=content,
        related_claim="test claim",
        source_type=source_type,
        source_weight=source_weight,
    )


# --- 話術掃描 ---


class TestScanPRTerms:
    def test_hit_mapping(self):
        evs = [
            _make_evidence(ev_id="ev-001", content="BTC is going to the moon"),
            _make_evidence(ev_id="ev-002", content="ETH traded flat today"),
            _make_evidence(ev_id="ev-003", content="SOL guaranteed 100x"),
        ]
        hits = scan_pr_terms(evs)
        assert set(hits) == {"ev-001", "ev-003"}
        assert hits["ev-001"] == "to the moon"

    def test_case_insensitive(self):
        assert scan_pr_terms([_make_evidence(content="BTC will SKYROCKET")]) != {}

    def test_chinese_term(self):
        hits = scan_pr_terms([_make_evidence(content="BTC 即將暴漲！")])
        assert hits["ev-001"] == "暴漲"

    def test_first_term_recorded(self):
        hits = scan_pr_terms(
            [_make_evidence(content="skyrocket to the moon guaranteed")]
        )
        # PR_TERMS 順序中第一個命中者
        assert hits["ev-001"] == "skyrocket"

    def test_no_hit_empty(self):
        assert scan_pr_terms([_make_evidence(content="moderate volume day")]) == {}


# --- 四因子模式：PR 決策由等級降級產生 ---


class TestPRDemotionDecisions:
    def test_demotion_decision_recorded_not_reapplied(self, tmp_path: Path):
        """四因子模式：權重已由 L1 算定，L2 只記錄 FilterDecision 不再改權重。"""
        logger = ExecutionLogger(tmp_path / "t.jsonl")
        evs = [
            _make_evidence(ev_id="ev-001", content="BTC will skyrocket next week"),
            _make_evidence(ev_id="ev-002", content="ETH traded flat today"),
        ]
        pr_hits = scan_pr_terms(evs)
        breakdowns = apply_source_weights(evs, logger, pr_demotions=pr_hits)
        weight_after_l1 = evs[0].source_weight

        decisions = apply_content_filters(
            evs, logger, pr_hits=pr_hits, breakdowns=breakdowns
        )

        pr_decisions = [d for d in decisions if d.check_code == "PR"]
        assert len(pr_decisions) == 1
        d = pr_decisions[0]
        assert d.evidence_id == "ev-001"
        assert d.verdict == FilterVerdict.DOWNWEIGHTED
        assert "來源等級" in d.reason and "skyrocket" in d.reason
        assert d.weight_before == pytest.approx(0.60)  # C 級未降前
        assert d.weight_after == pytest.approx(0.45)  # 降至 D 級
        # L2 未重複扣分
        assert evs[0].source_weight == weight_after_l1 == pytest.approx(0.45)

    def test_no_hits_no_decisions(self, tmp_path: Path):
        logger = ExecutionLogger(tmp_path / "t.jsonl")
        evs = [_make_evidence(content="moderate volume day")]
        breakdowns = apply_source_weights(evs, logger, pr_demotions={})
        decisions = apply_content_filters(evs, logger, pr_hits={}, breakdowns=breakdowns)
        assert [d for d in decisions if d.check_code == "PR"] == []


# --- 舊制 fallback 模式（無 breakdowns）---


class TestLegacyPRPath:
    def test_check_pr_language_x05(self):
        ev = _make_evidence(content="BTC will skyrocket next week")
        decisions = check_pr_language([ev])
        assert len(decisions) == 1
        assert decisions[0].weight_before == 0.60
        assert decisions[0].weight_after == pytest.approx(0.30)

    def test_weight_floor_005(self):
        ev = _make_evidence(content="guaranteed profits", source_weight=0.08)
        decisions = check_pr_language([ev])
        assert decisions[0].weight_after == 0.05

    def test_apply_without_breakdowns_uses_legacy_x05(self, tmp_path: Path):
        logger = ExecutionLogger(tmp_path / "t.jsonl")
        ev = _make_evidence(content="BTC will skyrocket to 100k", source_weight=0.60)
        apply_content_filters([ev], logger)
        assert ev.source_weight == pytest.approx(0.30)


# --- F9 情緒分布（詞典法）---


class TestF9Sentiment:
    def test_distribution_counts(self):
        evs = [
            _make_evidence(ev_id="ev-001", content="Bitcoin ETF approval sparks rally"),
            _make_evidence(ev_id="ev-002", content="Exchange hack triggers market plunge"),
            _make_evidence(ev_id="ev-003", content="Bitcoin traded sideways this week"),
        ]
        f9 = check_sentiment_distribution(evs)
        assert (f9["positive"], f9["negative"], f9["neutral"]) == (1, 1, 1)
        assert f9["sample"] == 3
        assert f9["enabled"] is True
        assert f9["labels"]["ev-001"] == "positive"
        assert f9["labels"]["ev-002"] == "negative"

    def test_word_boundary_no_partial_match(self):
        """'banana' 不應命中 'ban'。"""
        f9 = check_sentiment_distribution(
            [_make_evidence(content="banana themed token launched")]
        )
        assert f9["negative"] == 0
        assert f9["neutral"] == 1

    def test_duplicates_excluded(self):
        """被去重剔除者不納入分布（避免聯播稿灌高單向情緒）。"""
        kept = _make_evidence(ev_id="ev-001", content="Bitcoin rally continues strongly")
        dup = _make_evidence(ev_id="ev-002", content="Bitcoin rally continues strongly")
        dup.duplicate_of = "ev-001"
        f9 = check_sentiment_distribution([kept, dup])
        assert f9["sample"] == 1
        assert f9["positive"] == 1

    def test_non_narrative_ignored(self):
        f9 = check_sentiment_distribution(
            [_make_evidence(content="price rally detected", source_type=SourceType.PRICE)]
        )
        assert f9["sample"] == 0
        assert "無敘事類證據" in f9["note"]

    def test_herding_flag_requires_sample_and_ratio(self):
        bullish = [
            _make_evidence(ev_id=f"ev-{i:03d}", content=f"Coin {i} rally and breakout continues")
            for i in range(1, 6)
        ]
        f9 = check_sentiment_distribution(bullish)
        assert f9["sample"] == 5
        assert f9["one_sided_ratio"] == 1.0
        assert f9["herding_flag"] is True
        assert "羊群" in f9["note"]

        # 樣本 4 筆 → 即使 100% 單向也不觸發
        f9_small = check_sentiment_distribution(bullish[:4])
        assert f9_small["herding_flag"] is False

    def test_f9_status_enabled(self):
        assert F9_STATUS["enabled"] is True
        assert F9_STATUS["method"] == "lexicon"


# --- apply_content_filters 整合 ---


class TestApplyContentFilters:
    def test_logs_written_with_f9_and_summary(self, tmp_path: Path):
        logger = ExecutionLogger(tmp_path / "t.jsonl")
        evs = [_make_evidence(content="This is guaranteed to 100x")]
        breakdowns = apply_source_weights(evs, logger, pr_demotions=scan_pr_terms(evs))
        apply_content_filters(evs, logger, breakdowns=breakdowns)

        entries = [e for e in logger.read_all() if e.layer == PipelineLayer.CONTENT]
        actions = [e.action for e in entries]
        assert "l2_pr_filter" in actions
        assert "l2_f9_sentiment" in actions
        assert "l2_content_summary" in actions

        summary = next(e for e in entries if e.action == "l2_content_summary")
        assert summary.metrics["pr_hits"] == 1
        assert summary.metrics["mode"] == "four_factor"
        assert summary.metrics["f9"]["enabled"] is True

    def test_no_hit_still_logs_summary(self, tmp_path: Path):
        logger = ExecutionLogger(tmp_path / "t.jsonl")
        evs = [_make_evidence(content="BTC traded at 65000 with moderate volume")]
        breakdowns = apply_source_weights(evs, logger, pr_demotions={})
        decisions = apply_content_filters(evs, logger, pr_hits={}, breakdowns=breakdowns)

        assert decisions == []
        entries = [e for e in logger.read_all() if e.layer == PipelineLayer.CONTENT]
        summary = next(e for e in entries if e.action == "l2_content_summary")
        assert summary.metrics["pr_hits"] == 0

    def test_empty_evidences(self, tmp_path: Path):
        logger = ExecutionLogger(tmp_path / "t.jsonl")
        assert apply_content_filters([], logger) == []

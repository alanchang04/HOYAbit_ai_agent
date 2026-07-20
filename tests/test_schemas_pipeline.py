"""R3 schema 新增模型的單元測試：新欄位預設值、FilterDecision/RunMetrics 驗證。"""

import pytest
from pydantic import ValidationError

from agent.schemas import (
    EvidenceDraft,
    FilterDecision,
    FilterVerdict,
    LogEntry,
    LogPhase,
    LogStatus,
    PipelineLayer,
    RunMetrics,
    now_iso,
)


# ---------- 1. EvidenceDraft 新欄位預設值 ----------


class TestEvidenceDraftDefaults:
    """僅用舊必填欄位建構 EvidenceDraft，驗證新欄位有正確預設值。"""

    def test_new_fields_have_defaults(self):
        draft = EvidenceDraft(
            coin="BTC",
            source="CoinGecko",
            fetched_at=now_iso(),
            content_reference="BTC 現價 65000 USDT",
            related_claim="BTC 當前報價",
            source_type="price",
        )
        assert draft.source_weight == 0.5
        assert draft.weight_reason == ""
        assert draft.rag_verified is None
        assert draft.rag_support == ""

    def test_can_override_new_fields(self):
        draft = EvidenceDraft(
            coin="ETH",
            source="Etherscan",
            fetched_at=now_iso(),
            content_reference="ETH gas",
            related_claim="gas price",
            source_type="onchain",
            source_weight=0.85,
            weight_reason="鏈上公開 RPC",
            rag_verified=True,
            rag_support="RAG 確認",
        )
        assert draft.source_weight == 0.85
        assert draft.weight_reason == "鏈上公開 RPC"
        assert draft.rag_verified is True
        assert draft.rag_support == "RAG 確認"


# ---------- 2. LogEntry 新欄位預設值 ----------


class TestLogEntryDefaults:
    """僅用舊欄位建構 LogEntry，驗證 layer/metrics 預設值。"""

    def test_new_fields_have_defaults(self):
        entry = LogEntry(
            ts=now_iso(),
            phase=LogPhase.COLLECT,
            action="price_collector",
            status=LogStatus.OK,
        )
        assert entry.layer is None
        assert entry.metrics == {}

    def test_can_set_layer_and_metrics(self):
        entry = LogEntry(
            ts=now_iso(),
            phase=LogPhase.REASON,
            action="step_a",
            status=LogStatus.OK,
            layer=PipelineLayer.FACT,
            metrics={"input": 10, "kept": 7, "removed": 3},
        )
        assert entry.layer == PipelineLayer.FACT
        assert entry.metrics == {"input": 10, "kept": 7, "removed": 3}


# ---------- 3. FilterDecision 驗證 ----------


class TestFilterDecision:
    """FilterDecision 必要欄位與選用欄位。"""

    def test_valid_creation_kept(self):
        fd = FilterDecision(
            evidence_id="ev-001",
            check_code="PR",
            verdict=FilterVerdict.KEPT,
            reason="無 PR 詞彙命中",
        )
        assert fd.evidence_id == "ev-001"
        assert fd.check_code == "PR"
        assert fd.verdict == FilterVerdict.KEPT
        assert fd.reason == "無 PR 詞彙命中"
        assert fd.weight_before is None
        assert fd.weight_after is None

    def test_valid_creation_downweighted(self):
        fd = FilterDecision(
            evidence_id="ev-002",
            check_code="F10",
            verdict=FilterVerdict.DOWNWEIGHTED,
            reason="near-duplicate of ev-001",
            weight_before=0.8,
            weight_after=0.48,
        )
        assert fd.verdict == FilterVerdict.DOWNWEIGHTED
        assert fd.weight_before == 0.8
        assert fd.weight_after == 0.48

    def test_valid_creation_removed(self):
        fd = FilterDecision(
            evidence_id="ev-003",
            check_code="SUBJ",
            verdict=FilterVerdict.REMOVED,
            reason="主觀推測無佐證",
        )
        assert fd.verdict == FilterVerdict.REMOVED

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            FilterDecision(verdict=FilterVerdict.KEPT)  # type: ignore

    def test_evidence_id_required(self):
        with pytest.raises(ValidationError):
            FilterDecision(
                check_code="PR",
                verdict=FilterVerdict.KEPT,
                reason="test",
            )  # type: ignore

    def test_check_code_required(self):
        with pytest.raises(ValidationError):
            FilterDecision(
                evidence_id="ev-001",
                verdict=FilterVerdict.KEPT,
                reason="test",
            )  # type: ignore

    def test_reason_required(self):
        with pytest.raises(ValidationError):
            FilterDecision(
                evidence_id="ev-001",
                check_code="PR",
                verdict=FilterVerdict.KEPT,
            )  # type: ignore


# ---------- 4. RunMetrics 驗證 ----------


class TestRunMetrics:
    """RunMetrics 預設值與可覆寫。"""

    def test_all_defaults(self):
        m = RunMetrics()
        assert m.confidence == 0
        assert m.noise_removal_rate == 0.0
        assert m.total_tokens == 0
        assert m.integrity_status == "INTACT"
        assert m.raw_evidence_count == 0
        assert m.kept_fact_count == 0

    def test_override_values(self):
        m = RunMetrics(
            confidence=72,
            noise_removal_rate=0.35,
            total_tokens=4500,
            integrity_status="DEGRADED",
            raw_evidence_count=15,
            kept_fact_count=10,
        )
        assert m.confidence == 72
        assert m.noise_removal_rate == 0.35
        assert m.total_tokens == 4500
        assert m.integrity_status == "DEGRADED"
        assert m.raw_evidence_count == 15
        assert m.kept_fact_count == 10


# ---------- 5. PipelineLayer enum ----------


class TestPipelineLayer:
    """驗證 PipelineLayer 五個值都存在。"""

    def test_all_five_values_exist(self):
        assert PipelineLayer.SOURCE == "L1_source"
        assert PipelineLayer.CONTENT == "L2_content"
        assert PipelineLayer.FACT == "L3_fact"
        assert PipelineLayer.CROSS == "L4_cross"
        assert PipelineLayer.CONCLUSION == "L5_conclusion"

    def test_exactly_five_members(self):
        assert len(PipelineLayer) == 5


# ---------- 6. FilterVerdict enum ----------


class TestFilterVerdict:
    """驗證 FilterVerdict 三個值。"""

    def test_all_three_values_exist(self):
        assert FilterVerdict.KEPT == "kept"
        assert FilterVerdict.DOWNWEIGHTED == "downweighted"
        assert FilterVerdict.REMOVED == "removed"

    def test_exactly_three_members(self):
        assert len(FilterVerdict) == 3

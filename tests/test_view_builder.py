"""test_view_builder：驗證 view_builder 組裝 report_view.json。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.reasoning.pipeline import ReasoningResult
from agent.report.view_builder import build_report_view
from agent.schemas import (
    Evidence,
    FilterDecision,
    FilterVerdict,
    LogEntry,
    LogPhase,
    LogStatus,
    PipelineLayer,
    RunMetrics,
    SourceType,
    now_iso,
)


@pytest.fixture
def sample_evidences() -> list[Evidence]:
    """建立假證據清單。"""
    return [
        Evidence(
            id="ev-001",
            coin="BTC",
            source="CoinGecko API",
            source_url="https://api.coingecko.com/",
            fetched_at=now_iso(),
            content_reference="BTC price at $67,000 with 24h volume of $30B",
            related_claim="BTC 目前價格走勢",
            source_type=SourceType.PRICE,
            source_weight=0.80,
            weight_reason="交易所聚合行情 API",
        ),
        Evidence(
            id="ev-002",
            coin="BTC",
            source="Etherscan",
            source_url="https://etherscan.io/",
            fetched_at=now_iso(),
            content_reference="BTC hash rate reached all-time high",
            related_claim="鏈上數據顯示算力新高",
            source_type=SourceType.ONCHAIN,
            source_weight=0.85,
            weight_reason="鏈上公開 RPC，數據不可竄改",
        ),
        Evidence(
            id="ev-003",
            coin="BTC",
            source="CryptoPanic RSS",
            source_url="https://cryptopanic.com/",
            fetched_at=now_iso(),
            content_reference="Bitcoin ETF sees record inflows this week",
            related_claim="ETF 資金流入",
            source_type=SourceType.NEWS,
            source_weight=0.60,
            weight_reason="主流媒體，未逐篇查證",
        ),
    ]


@pytest.fixture
def sample_reasoning_result() -> ReasoningResult:
    return ReasoningResult(
        question_type="multi_source",
        facts=[
            {"summary": "BTC 價格在 $67,000 附近", "evidence_ids": ["ev-001"]},
            {"summary": "鏈上算力創新高", "evidence_ids": ["ev-002"]},
        ],
        cross_validation={
            "consistent_signals": ["價格與鏈上數據同步向好"],
            "contradictions": [],
        },
        inference=[
            {
                "hypothesis": "BTC 短期偏強",
                "supporting_evidence_ids": ["ev-001", "ev-002"],
                "opposing_evidence_ids": [],
            }
        ],
        conclusion={
            "market_judgment": "BTC 目前處於偏強格局",
            "confidence": "中",
            "limitations": ["社群/總經資料缺失"],
            "invalidation_conditions": ["若出現大量拋售訊號"],
            "evidence_ids": ["ev-001", "ev-002", "ev-003"],
        },
        follow_up_watchpoints=["觀察 ETF 資金流向"],
        debate={
            "bull_argument": "算力新高加上 ETF 資金流入支持偏強格局",
            "bull_evidence_ids": ["ev-001", "ev-002"],
            "bear_critique": "缺乏社群與總經數據佐證",
            "bear_argument": "新聞面利好可能已被價格反映",
            "bear_evidence_ids": ["ev-003"],
        },
        confidence_score=60,
    )


@pytest.fixture
def sample_run_metrics() -> RunMetrics:
    return RunMetrics(
        confidence=60,
        noise_removal_rate=0.1,
        total_tokens=500,
        integrity_status="INTACT",
        raw_evidence_count=3,
        kept_fact_count=2,
    )


@pytest.fixture
def sample_filter_decisions() -> list[FilterDecision]:
    return [
        FilterDecision(
            evidence_id="ev-003",
            check_code="PR",
            verdict=FilterVerdict.DOWNWEIGHTED,
            reason='命中 PR 話術「to the moon」，權重 0.60 → 0.30',
            weight_before=0.60,
            weight_after=0.30,
        ),
    ]


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    """準備含 execution_log.jsonl 的暫存目錄。"""
    log_path = tmp_path / "execution_log.jsonl"
    entries = [
        LogEntry(
            ts=now_iso(),
            phase=LogPhase.REASON,
            action="l3_fact_extraction",
            detail="input=3, kept=2, removed=1, rate=0.333",
            status=LogStatus.OK,
            layer=PipelineLayer.FACT,
            metrics={"input": 3, "kept": 2, "removed": 1, "removal_rate": 0.333},
        ),
        LogEntry(
            ts=now_iso(),
            phase=LogPhase.REASON,
            action="l4_cross_validation",
            detail="consistent=1, contradictions=0",
            status=LogStatus.OK,
            layer=PipelineLayer.CROSS,
            metrics={"consistent": 1, "contradictions": 0},
        ),
        LogEntry(
            ts=now_iso(),
            phase=LogPhase.REASON,
            action="l5_confidence_score",
            detail="score=60, base=55, auth_bonus=7, contradiction_penalty=0, gap_penalty=10",
            status=LogStatus.OK,
            layer=PipelineLayer.CONCLUSION,
            metrics={
                "base": 55,
                "auth_bonus": 7,
                "contradiction_penalty": 0,
                "gap_penalty": 10,
                "final": 60,
            },
        ),
    ]
    lines = [e.model_dump_json() for e in entries]
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def test_build_report_view_produces_valid_json(
    out_dir: Path,
    sample_evidences: list[Evidence],
    sample_reasoning_result: ReasoningResult,
    sample_run_metrics: RunMetrics,
    sample_filter_decisions: list[FilterDecision],
) -> None:
    """驗證 view_builder 產出完整 report_view.json。"""
    result = build_report_view(
        out_dir=out_dir,
        evidences=sample_evidences,
        reasoning_result=sample_reasoning_result,
        run_metrics=sample_run_metrics,
        filter_decisions=sample_filter_decisions,
        coin="BTC",
        question="BTC 近期走勢分析",
    )

    assert result is not None
    assert result["schema_version"] == "1.0"

    # 驗證 meta
    meta = result["meta"]
    assert meta["coin"] == "BTC"
    assert meta["question_type"] == "multi_source"
    assert "generated_at" in meta
    assert meta["metrics"]["confidence"] == 60

    # 驗證 panel1
    panel1 = result["panel1_raw_feed"]
    assert panel1["count"] == 3
    assert panel1["items"][0]["fingerprint"] == "F1"
    assert panel1["items"][0]["evidence_id"] == "ev-001"
    assert panel1["items"][2]["fingerprint"] == "F3"

    # 驗證 filter_decisions 歸屬到正確的 evidence
    ev3_item = panel1["items"][2]
    assert len(ev3_item["filter_decisions"]) == 1
    assert ev3_item["filter_decisions"][0]["check_code"] == "PR"

    # 驗證 panel2
    panel2 = result["panel2_naive_baseline"]
    assert panel2["enabled"] is False
    assert len(panel2["steps"]) == 4

    # 驗證 panel3
    panel3 = result["panel3_refinement"]
    assert "noise_removal_rate" in panel3
    assert len(panel3["layers"]) == 5
    assert panel3["layers"][0]["layer"] == "L1_source"
    assert panel3["layers"][1]["layer"] == "L2_content"
    assert panel3["layers"][2]["layer"] == "L3_fact"
    assert panel3["layers"][3]["layer"] == "L4_cross"
    assert panel3["layers"][4]["layer"] == "L5_conclusion"

    # L5 confidence breakdown
    l5 = panel3["layers"][4]
    assert l5["confidence_breakdown"]["base"] == 55
    assert l5["confidence_breakdown"]["final"] == 60

    # log_events_by_layer
    assert "log_events_by_layer" in panel3
    assert "L3_fact" in panel3["log_events_by_layer"]

    # 驗證 panel4
    panel4 = result["panel4_report"]
    assert panel4["integrity_status"] == "INTACT"
    assert panel4["confidence"] == 60
    assert panel4["market_judgment"] == "BTC 目前處於偏強格局"
    assert len(panel4["core_facts"]) >= 1
    assert len(panel4["bullish_evidence"]) >= 1
    assert len(panel4["risk_evidence"]) >= 1
    assert panel4["follow_up_watchpoints"] == ["觀察 ETF 資金流向"]

    # 驗證寫入檔案
    view_path = out_dir / "report_view.json"
    assert view_path.exists()
    loaded = json.loads(view_path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "1.0"


def test_build_report_view_fingerprint_mapping(
    out_dir: Path,
    sample_evidences: list[Evidence],
    sample_reasoning_result: ReasoningResult,
    sample_run_metrics: RunMetrics,
    sample_filter_decisions: list[FilterDecision],
) -> None:
    """驗證指紋映射 F1..Fn 依出現順序。"""
    result = build_report_view(
        out_dir=out_dir,
        evidences=sample_evidences,
        reasoning_result=sample_reasoning_result,
        run_metrics=sample_run_metrics,
        filter_decisions=sample_filter_decisions,
        coin="BTC",
        question="test",
    )

    assert result is not None
    items = result["panel1_raw_feed"]["items"]
    for i, item in enumerate(items, 1):
        assert item["fingerprint"] == f"F{i}"


def test_build_report_view_failure_returns_none(tmp_path: Path) -> None:
    """驗證組裝失敗回傳 None，不丟例外。"""
    # 傳入不合法的資料觸發內部錯誤
    result = build_report_view(
        out_dir=tmp_path,
        evidences=[],  # type: ignore
        reasoning_result=None,  # type: ignore - force error
        run_metrics=RunMetrics(),
        filter_decisions=[],
        coin="BTC",
        question="test",
    )
    assert result is None


def test_build_report_view_l3_removed_items_populated(
    out_dir: Path,
    sample_evidences: list[Evidence],
    sample_reasoning_result: ReasoningResult,
    sample_run_metrics: RunMetrics,
    sample_filter_decisions: list[FilterDecision],
) -> None:
    """驗證 L3 removed_items 能反推出未被事實層引用的證據，並帶上正確理由。

    sample_reasoning_result 的 facts 只引用 ev-001/ev-002；ev-003 未被引用，
    且在 sample_filter_decisions 中有 PR 判定 —— removed_items 應包含 ev-003，
    reason 沿用該 PR 判定的說明，而不是通用的「未引用」文字。
    """
    result = build_report_view(
        out_dir=out_dir,
        evidences=sample_evidences,
        reasoning_result=sample_reasoning_result,
        run_metrics=sample_run_metrics,
        filter_decisions=sample_filter_decisions,
        coin="BTC",
        question="test",
    )

    assert result is not None
    l3 = next(l for l in result["panel3_refinement"]["layers"] if l["layer"] == "L3_fact")
    removed_items = l3["removed_items"]

    assert len(removed_items) == 1
    assert removed_items[0]["evidence_id"] == "ev-003"
    assert removed_items[0]["fingerprint"] == "F3"
    assert "PR 話術" in removed_items[0]["reason"]

    # ev-001/ev-002 有被事實層引用，不應出現在 removed_items
    removed_ids = {item["evidence_id"] for item in removed_items}
    assert "ev-001" not in removed_ids
    assert "ev-002" not in removed_ids


def test_build_report_view_l3_removed_items_generic_reason_without_filter_decision(
    out_dir: Path,
    sample_run_metrics: RunMetrics,
) -> None:
    """驗證未被事實層引用、且無 L2 過濾判定的證據，會得到通用的「未引用」理由。"""
    evidences = [
        Evidence(
            id="ev-001",
            coin="BTC",
            source="CoinGecko API",
            fetched_at=now_iso(),
            content_reference="BTC price info",
            related_claim="x",
            source_type=SourceType.PRICE,
            source_weight=0.8,
        ),
        Evidence(
            id="ev-002",
            coin="BTC",
            source="Some Blog",
            fetched_at=now_iso(),
            content_reference="unrelated secondary detail",
            related_claim="x",
            source_type=SourceType.NEWS,
            source_weight=0.6,
        ),
    ]
    reasoning_result = ReasoningResult(
        question_type="multi_source",
        facts=[{"summary": "s", "evidence_ids": ["ev-001"]}],
        cross_validation={},
        confidence_score=50,
    )

    result = build_report_view(
        out_dir=out_dir,
        evidences=evidences,
        reasoning_result=reasoning_result,
        run_metrics=sample_run_metrics,
        filter_decisions=[],  # 無任何 L2 判定
        coin="BTC",
        question="test",
    )

    assert result is not None
    l3 = next(l for l in result["panel3_refinement"]["layers"] if l["layer"] == "L3_fact")
    removed_items = l3["removed_items"]

    assert len(removed_items) == 1
    assert removed_items[0]["evidence_id"] == "ev-002"
    assert "未引用" in removed_items[0]["reason"]


def test_build_report_view_with_baseline(
    out_dir: Path,
    sample_evidences: list[Evidence],
    sample_reasoning_result: ReasoningResult,
    sample_run_metrics: RunMetrics,
    sample_filter_decisions: list[FilterDecision],
) -> None:
    """驗證 baseline 有值時 panel2 enabled=True。"""
    baseline = {
        "analysis": "未過濾分析結果摘要",
        "caveat": "此為未過濾對照組輸出",
    }
    result = build_report_view(
        out_dir=out_dir,
        evidences=sample_evidences,
        reasoning_result=sample_reasoning_result,
        run_metrics=sample_run_metrics,
        filter_decisions=sample_filter_decisions,
        baseline_result=baseline,
        coin="BTC",
        question="test",
    )

    assert result is not None
    panel2 = result["panel2_naive_baseline"]
    assert panel2["enabled"] is True
    assert panel2["naive_output"]["analysis"] == "未過濾分析結果摘要"

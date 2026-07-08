import pytest

from agent.orchestrator import run_pipeline
from agent.reasoning.pipeline import ReasoningResult
from agent.report.builder import EvidenceReferenceError, build_report_markdown, validate_evidence_references
from agent.schemas import Evidence, now_iso


def make_evidence(eid: str, coin: str = "BTC") -> Evidence:
    return Evidence(
        id=eid,
        coin=coin,
        source="test-source",
        fetched_at=now_iso(),
        content_reference="ref",
        related_claim="claim",
        source_type="price",
    )


def test_validate_evidence_references_passes_when_all_ids_exist():
    evidences = [make_evidence("ev-001"), make_evidence("ev-002")]
    result = ReasoningResult(
        question_type="multi_source",
        facts=[{"summary": "s", "evidence_ids": ["ev-001"]}],
        conclusion={"evidence_ids": ["ev-002"], "market_judgment": "x", "confidence": "低"},
    )
    validate_evidence_references(result, evidences)  # 不應拋出例外


def test_validate_evidence_references_raises_on_missing_id():
    evidences = [make_evidence("ev-001")]
    result = ReasoningResult(
        question_type="multi_source",
        facts=[{"summary": "s", "evidence_ids": ["ev-999"]}],
        conclusion={"evidence_ids": [], "market_judgment": "x", "confidence": "低"},
    )
    with pytest.raises(EvidenceReferenceError):
        validate_evidence_references(result, evidences)


def test_build_report_markdown_includes_conclusion_and_evidence_ids():
    evidences = [make_evidence("ev-001")]
    result = ReasoningResult(
        question_type="multi_source",
        facts=[{"summary": "摘要", "evidence_ids": ["ev-001"]}],
        conclusion={
            "market_judgment": "市場判斷內容",
            "confidence": "中",
            "limitations": ["限制A"],
            "invalidation_conditions": ["條件A"],
            "evidence_ids": ["ev-001"],
        },
    )
    md = build_report_markdown("BTC", "測試題目", result, evidences)
    assert "市場判斷內容" in md
    assert "ev-001" in md
    assert "限制A" in md


def test_dry_run_pipeline_end_to_end(tmp_path):
    result = run_pipeline(coin="BTC", question="分析 BTC 過去兩週市場表現", dry_run=True, output_dir=str(tmp_path))

    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "evidence.json").exists()
    assert (tmp_path / "execution_log.jsonl").exists()
    assert len(result.evidences) > 0
    assert "BTC" in result.report_markdown


def test_dry_run_comparison_auto_detects_second_coin_and_collects_both(tmp_path):
    result = run_pipeline(
        coin="BTC",
        question="比較 BTC 與 ETH 在流動性與風險敞口上的差異",
        dry_run=True,
        output_dir=str(tmp_path),
    )

    coins_in_evidence = {e.coin for e in result.evidences}
    assert coins_in_evidence == {"BTC", "ETH"}
    assert "BTC vs ETH" in result.report_markdown


def test_dry_run_comparison_with_explicit_coin2_override(tmp_path):
    result = run_pipeline(
        coin="BTC",
        question="分析看看",  # 題目文字本身沒提到第二幣種，靠 --coin2 明確指定
        dry_run=True,
        output_dir=str(tmp_path),
        coin2="SOL",
    )
    # 題目文字沒有比較關鍵字，所以會被分類成 multi_source，coin2 不會被採用
    assert result.reasoning.coin2 is None

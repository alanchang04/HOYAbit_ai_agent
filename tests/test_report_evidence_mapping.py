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


def test_build_report_markdown_executive_summary_with_debate():
    """執行摘要應包含信心／市場判斷／利多／風險／最需留意五個維度，一個都不能省。"""
    evidences = [make_evidence("ev-001"), make_evidence("ev-002")]
    result = ReasoningResult(
        question_type="multi_source",
        facts=[{"summary": "摘要", "evidence_ids": ["ev-001"]}],
        conclusion={
            "market_judgment": "市場判斷內容",
            "confidence": "中",
            "limitations": ["限制A"],
            "invalidation_conditions": ["若跌破關鍵支撐則判斷失效"],
            "evidence_ids": ["ev-001"],
        },
        debate={
            "bull_argument": "利多論證內容",
            "bull_evidence_ids": ["ev-001"],
            "bear_argument": "風險論證內容",
            "bear_evidence_ids": ["ev-002"],
        },
        confidence_score=62,
    )
    md = build_report_markdown("BTC", "測試題目", result, evidences)

    assert "## 執行摘要" in md
    exec_section = md.split("## 執行摘要")[1].split("## 1.")[0]
    assert "62%" in exec_section
    assert "（中）" in exec_section
    assert "市場判斷內容" in exec_section
    assert "利多論證內容" in exec_section
    assert "ev-001" in exec_section
    assert "風險論證內容" in exec_section
    assert "ev-002" in exec_section
    assert "若跌破關鍵支撐則判斷失效" in exec_section
    # 執行摘要必須出現在第 1 節之前
    assert md.index("## 執行摘要") < md.index("## 1. 結論")


def test_build_report_markdown_executive_summary_without_debate_falls_back():
    """無辯論（fallback 路徑）時，執行摘要要誠實標示，不能假裝有辯論內容。"""
    evidences = [make_evidence("ev-001")]
    result = ReasoningResult(
        question_type="multi_source",
        facts=[{"summary": "摘要", "evidence_ids": ["ev-001"]}],
        conclusion={
            "market_judgment": "市場判斷內容",
            "confidence": "低",
            "evidence_ids": ["ev-001"],
        },
        follow_up_watchpoints=["觀察後續資金流向"],
    )
    md = build_report_markdown("BTC", "測試題目", result, evidences)

    exec_section = md.split("## 執行摘要")[1].split("## 1.")[0]
    assert "未觸發正反辯論" in exec_section
    assert "觀察後續資金流向" in exec_section
    assert "最需留意的後續觀察" in exec_section


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
    assert {"BTC", "ETH"}.issubset(coins_in_evidence)
    # 比較題型現在還會產出雙幣相對指標（BTC/ETH）
    assert "BTC/ETH" in coins_in_evidence
    assert "BTC vs ETH" in result.report_markdown


def test_dry_run_comparison_no_duplicate_macro_evidence(tmp_path):
    """R1-3 回歸測試：比較題型 macro 證據不得重複。"""
    result = run_pipeline(
        coin="BTC",
        question="比較 BTC 與 ETH 在流動性與風險敞口上的差異",
        dry_run=True,
        output_dir=str(tmp_path),
    )

    # 過濾出 macro 類型證據
    macro_evidences = [e for e in result.evidences if e.source_type == "macro"]
    # 用 content_reference 判定是否重複：同 source_type==macro 下不得有兩筆 content_reference 相同
    content_refs = [e.content_reference for e in macro_evidences]
    assert len(content_refs) == len(set(content_refs)), (
        f"macro 證據出現重複 content_reference: {content_refs}"
    )


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

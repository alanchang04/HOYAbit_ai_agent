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


def test_build_report_markdown_executive_summary_cites_last_round_not_union():
    """回歸測試（隊友3發現）：執行摘要顯示的論證文字已經是最後一輪，
    引用 id 清單也要對齊最後一輪，不是所有輪次的聯集——否則會列出文字
    裡其實沒提到的證據 id（例如正方第 2 輪已經放棄引用的 ev-001）。"""
    evidences = [make_evidence("ev-001"), make_evidence("ev-002"), make_evidence("ev-003")]
    result = ReasoningResult(
        question_type="multi_source",
        facts=[{"summary": "摘要", "evidence_ids": ["ev-001"]}],
        conclusion={"market_judgment": "市場判斷內容", "confidence": "中", "evidence_ids": ["ev-001"]},
        debate={
            "rounds": [
                {
                    "round": 1,
                    "bull_argument": "第一輪正方論證",
                    "bull_evidence_ids": ["ev-001"],
                    "bear_critique": "第一輪批評",
                    "bear_argument": "第一輪反方論證",
                    "bear_evidence_ids": ["ev-002"],
                },
                {
                    "round": 2,
                    "bull_argument": "第二輪正方論證（修正版）",
                    "bull_evidence_ids": ["ev-003"],
                    "bear_critique": "第二輪批評",
                    "bear_argument": "第二輪反方論證（最終）",
                    "bear_evidence_ids": [],
                },
            ],
            "round_count": 2,
            "stopped_reason": "max_rounds",
            "bull_argument": "第二輪正方論證（修正版）",
            "bull_evidence_ids": ["ev-001", "ev-003"],  # 聯集，report 引用檢查用
            "bear_critique": "第二輪批評",
            "bear_argument": "第二輪反方論證（最終）",
            "bear_evidence_ids": ["ev-002"],
        },
        confidence_score=55,
    )
    md = build_report_markdown("BTC", "測試題目", result, evidences)
    exec_section = md.split("## 執行摘要")[1].split("## 1.")[0]

    assert "第二輪正方論證（修正版）" in exec_section
    bull_citation_line = [l for l in exec_section.splitlines() if l.startswith("（引用：")][0]
    assert bull_citation_line == "（引用：ev-003）"
    assert "ev-001" not in bull_citation_line


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


def _result_with_breakdown(**overrides):
    """帶三維信心分項的 ReasoningResult（R3-12/R3-13 呈現測試用）。"""
    breakdown = {
        "data_confidence": 83.3,
        "signal_consensus": 85.0,
        "evidence_strength": 76.2,
        "weights": {"data_confidence": 0.4, "signal_consensus": 0.4, "evidence_strength": 0.2},
        "base": 82.5,
        "debate_adjustment": -5,
        "debate_adjustment_reason": "反方對鏈上活躍度的批評成立",
        "final": 78,
        "why": ["✅ price 資料完整（3 筆，最長窗長 30 天）", "⚠ 辯論後下修 5 分：反方批評成立"],
        "signal_consensus_detail": {"degraded": False},
    }
    breakdown.update(overrides.pop("breakdown", {}))
    base = dict(
        question_type="multi_source",
        facts=[{"summary": "摘要", "evidence_ids": ["ev-001"]}],
        conclusion={"market_judgment": "判斷", "confidence": "中", "evidence_ids": ["ev-001"]},
        confidence_score=78,
        confidence_breakdown=breakdown,
    )
    base.update(overrides)
    return ReasoningResult(**base)


def test_report_confidence_section_shows_three_dimension_breakdown():
    """R3-12：第 4 節要攤開三維分數、權重、基底、辯論調整、最終分，可逐項對帳。"""
    md = build_report_markdown("BTC", "題目", _result_with_breakdown(), [make_evidence("ev-001")])
    section = md.split("## 4. 信心說明")[1].split("## 5.")[0]

    assert "資料品質" in section and "83.3" in section
    assert "訊號一致性" in section and "85.0" in section
    assert "證據強度" in section and "76.2" in section
    assert "40%" in section and "20%" in section
    assert "基底" in section and "82.5" in section
    assert "-5" in section and "反方對鏈上活躍度的批評成立" in section
    assert "78" in section


def test_report_confidence_section_shows_why_lines():
    """R3-13：不能只有分數，要有「這個分數怎麼來的」。"""
    md = build_report_markdown("BTC", "題目", _result_with_breakdown(), [make_evidence("ev-001")])
    section = md.split("## 4. 信心說明")[1].split("## 5.")[0]
    assert "這個分數怎麼來的" in section
    assert "price 資料完整" in section


def test_report_discloses_consensus_degradation():
    """R3-15：Step B 沒產出 direction_matrix 時，報告要講明共識是中性代入的，
    不能讓讀者以為 50 分是真的算出來的。"""
    md = build_report_markdown(
        "BTC",
        "題目",
        _result_with_breakdown(
            breakdown={
                "signal_consensus": 50.0,
                "signal_consensus_detail": {
                    "degraded": True,
                    "degraded_reason": "當前訊號帶的表態來源不足 2 個，訊號共識以中性 50 計算",
                },
            }
        ),
        [make_evidence("ev-001")],
    )
    section = md.split("## 4. 信心說明")[1].split("## 5.")[0]
    assert "訊號共識以中性 50 計算" in section


def test_report_without_breakdown_says_so_honestly():
    """舊格式結果／fallback 路徑沒有分項時，誠實標示而不是假裝有表格。"""
    result = ReasoningResult(
        question_type="multi_source",
        facts=[{"summary": "摘要", "evidence_ids": ["ev-001"]}],
        conclusion={"market_judgment": "判斷", "confidence": "低", "evidence_ids": ["ev-001"]},
        confidence_score=40,
    )
    md = build_report_markdown("BTC", "題目", result, [make_evidence("ev-001")])
    section = md.split("## 4. 信心說明")[1].split("## 5.")[0]
    assert "未產出分項計算明細" in section
    assert "| 資料品質 |" not in section


def test_structural_context_rendered_separately_from_contradictions():
    """R2-7/R2-8：跨尺度的位置關係不是矛盾，兩者必須分開呈現——
    混在一起會讓讀者以為資料在打架。"""
    result = ReasoningResult(
        question_type="multi_source",
        facts=[{"summary": "摘要", "evidence_ids": ["ev-001"]}],
        cross_validation={
            "consistent_signals": ["兩週價量同步走強"],
            "contradictions": ["社群情緒與鏈上流向不一致"],
            "structural_context": ["兩週情緒轉強，但價格仍處 5 年分佈第 88 百分位"],
        },
        conclusion={"market_judgment": "判斷", "confidence": "中", "evidence_ids": ["ev-001"]},
        confidence_score=60,
    )
    md = build_report_markdown("BTC", "題目", result, [make_evidence("ev-001")])
    section = md.split("## 3. ")[1].split("## 4.")[0]

    assert "### 矛盾訊號" in section
    assert "### 結構脈絡" in section
    assert "不計入矛盾" in section
    # 結構脈絡的內容不得出現在矛盾訊號段落裡
    contradiction_block = section.split("### 矛盾訊號")[1].split("###")[0]
    assert "5 年分佈第 88 百分位" not in contradiction_block


def test_executive_summary_splits_base_and_debate_adjustment():
    """R3-12：執行摘要第一眼就要看得出分數有沒有因辯論被下修。"""
    md = build_report_markdown("BTC", "題目", _result_with_breakdown(), [make_evidence("ev-001")])
    exec_section = md.split("## 執行摘要")[1].split("## 1.")[0]
    assert "基底" in exec_section
    assert "-5" in exec_section
    assert "辯論調整" in exec_section

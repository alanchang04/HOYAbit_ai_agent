"""組裝 report.md，並強制檢查報告中引用的 evidence id 必須存在於 evidence 清單中。"""

from __future__ import annotations

from agent.filters.source_weights import reputation_appendix_lines
from agent.reasoning.pipeline import ReasoningResult
from agent.reasoning.prompts import STOP_REASON_LABEL
from agent.report.text_formatting import normalize_embedded_lists
from agent.schemas import Evidence


class EvidenceReferenceError(ValueError):
    """報告引用了不存在於 evidence 清單中的 id 時拋出。"""


def _collect_referenced_ids(result: ReasoningResult) -> set[str]:
    ids: set[str] = set()
    for fact in result.facts:
        ids.update(fact.get("evidence_ids", []))
    for inf in result.inference:
        ids.update(inf.get("supporting_evidence_ids", []))
        ids.update(inf.get("opposing_evidence_ids", []))
    ids.update(result.conclusion.get("evidence_ids", []))
    ids.update(result.debate.get("bull_evidence_ids", []))
    ids.update(result.debate.get("bear_evidence_ids", []))
    return ids


def validate_evidence_references(result: ReasoningResult, evidences: list[Evidence]) -> None:
    known_ids = {e.id for e in evidences}
    referenced = _collect_referenced_ids(result)
    missing = referenced - known_ids
    if missing:
        raise EvidenceReferenceError(
            f"報告引用了不存在於 evidence.json 的 id: {sorted(missing)}"
        )


def _build_executive_summary_lines(result: ReasoningResult) -> list[str]:
    """組「執行摘要」：把信心／市場判斷／利多／風險／最需留意項濃縮到最上方，
    讓讀者不用翻完整份報告就能抓到重點；完整論述與逐筆證據仍保留在下方各節，
    這裡只是重組既有欄位、不新增 LLM 呼叫、不省略任何一個維度。
    """
    conclusion = result.conclusion or {}
    debate = result.debate or {}

    lines: list[str] = []
    lines.append("## 執行摘要")
    lines.append("")

    confidence_label = conclusion.get("confidence", "未知")
    lines.append(
        f"> 信心：{result.confidence_score}%（{confidence_label}）"
        "── 分項計算方式見「4. 信心說明」"
    )
    lines.append("")

    market_judgment = conclusion.get("market_judgment", "")
    if market_judgment:
        lines.append("**市場判斷：**")
        lines.append("")
        lines.append(normalize_embedded_lists(market_judgment))
    else:
        lines.append("**市場判斷：** （本次未產出市場判斷）")
    lines.append("")

    if debate.get("bull_argument") or debate.get("bear_argument"):
        bull_ids = debate.get("bull_evidence_ids", [])
        bear_ids = debate.get("bear_evidence_ids", [])
        lines.append("**利多依據：**")
        lines.append("")
        lines.append(normalize_embedded_lists(debate.get("bull_argument", "")))
        if bull_ids:
            lines.append(f"（引用：{', '.join(bull_ids)}）")
        lines.append("")
        lines.append("**風險依據：**")
        lines.append("")
        lines.append(normalize_embedded_lists(debate.get("bear_argument", "")))
        if bear_ids:
            lines.append(f"（引用：{', '.join(bear_ids)}）")
        lines.append("")
    else:
        lines.append(
            "**利多／風險依據：** 本次未觸發正反辯論（fallback 模式），"
            "完整推論假設與支持/反對證據見「3. 正反方分析與矛盾訊號處理」。"
        )
        lines.append("")

    watchpoint = ""
    invalidation_conditions = conclusion.get("invalidation_conditions", [])
    if invalidation_conditions:
        watchpoint = invalidation_conditions[0]
        watchpoint_label = "最需留意的推翻條件"
    elif result.follow_up_watchpoints:
        watchpoint = result.follow_up_watchpoints[0]
        watchpoint_label = "最需留意的後續觀察"
    if watchpoint:
        lines.append(f"**{watchpoint_label}：** {watchpoint}")
        lines.append("")

    return lines


def build_report_markdown(
    coin: str,
    question: str,
    result: ReasoningResult,
    evidences: list[Evidence],
    coin2: str | None = None,
) -> str:
    validate_evidence_references(result, evidences)
    ev_by_id = {e.id for e in evidences}
    ev_lookup = {e.id: e for e in evidences}
    coin2 = coin2 or result.coin2

    lines: list[str] = []
    lines.append(f"# {coin} vs {coin2} 市場分析報告" if coin2 else f"# {coin} 市場分析報告")
    lines.append("")
    lines.append(f"> 題目：{question}")
    lines.append(f"> 題型分類：{result.question_type}")
    lines.append("")

    lines.extend(_build_executive_summary_lines(result))

    lines.append("## 1. 結論／市場判斷")
    lines.append("")
    lines.append(normalize_embedded_lists(result.conclusion.get("market_judgment", "")))
    lines.append("")

    lines.append("## 2. 關鍵依據")
    lines.append("")
    for fact in result.facts:
        ids = fact.get("evidence_ids", [])
        coin_prefix = f"[{fact['coin']}] " if coin2 and fact.get("coin") else ""
        lines.append(f"- {coin_prefix}{fact.get('summary', '')}")
        for eid in ids:
            ev = ev_lookup.get(eid)
            if ev:
                lines.append(
                    f"  - `{eid}` | {ev.source} | {ev.fetched_at} | {ev.content_reference}"
                )
    lines.append("")

    lines.append("## 3. 正反方分析與矛盾訊號處理")
    lines.append("")
    consistent = result.cross_validation.get("consistent_signals", [])
    contradictions = result.cross_validation.get("contradictions", [])
    lines.append("### 一致訊號")
    lines.append("")
    for c in consistent:
        lines.append(f"- {c}")
    lines.append("")
    lines.append("### 矛盾訊號")
    lines.append("")
    if contradictions:
        for c in contradictions:
            lines.append(f"- {c}")
    else:
        lines.append("- 本次未偵測到明顯矛盾訊號")
    lines.append("")

    if result.debate:
        # 多輪辯論逐輪呈現；沒有 rounds 的舊單輪結構則收斂成一輪處理。
        debate_rounds = result.debate.get("rounds") or [
            {
                "round": 1,
                "bull_argument": result.debate.get("bull_argument", ""),
                "bull_evidence_ids": result.debate.get("bull_evidence_ids", []),
                "bear_critique": result.debate.get("bear_critique", ""),
                "bear_argument": result.debate.get("bear_argument", ""),
                "bear_evidence_ids": result.debate.get("bear_evidence_ids", []),
            }
        ]
        heading = "### 正方 vs 反方辯論"
        if len(debate_rounds) > 1:
            heading = f"### 正方 vs 反方辯論（共 {len(debate_rounds)} 輪）"
        lines.append(heading)
        lines.append("")
        for rd in debate_rounds:
            if len(debate_rounds) > 1:
                lines.append(f"**第 {rd.get('round', '?')} 輪**")
                lines.append("")
            lines.append("*正方論證：*")
            lines.append("")
            lines.append(normalize_embedded_lists(rd.get("bull_argument", "")))
            bull_ids = rd.get("bull_evidence_ids", [])
            if bull_ids:
                lines.append(f"- 引用證據：{', '.join(bull_ids)}")
            lines.append("")
            if rd.get("bear_critique"):
                lines.append("*反方對正方的批評：*")
                lines.append("")
                lines.append(normalize_embedded_lists(rd["bear_critique"]))
                lines.append("")
            lines.append("*反方論證：*")
            lines.append("")
            lines.append(normalize_embedded_lists(rd.get("bear_argument", "")))
            bear_ids = rd.get("bear_evidence_ids", [])
            if bear_ids:
                lines.append(f"- 引用證據：{', '.join(bear_ids)}")
            lines.append("")
        stopped = STOP_REASON_LABEL.get(result.debate.get("stopped_reason", ""))
        if stopped:
            lines.append(f"*辯論結束原因：* {stopped}")
            lines.append("")

    lines.append("### 推論假設")
    lines.append("")
    for inf in result.inference:
        lines.append(f"- {inf.get('hypothesis', '')}")
        support = inf.get("supporting_evidence_ids", [])
        oppose = inf.get("opposing_evidence_ids", [])
        if support:
            lines.append(f"  - 支持證據：{', '.join(support)}")
        if oppose:
            lines.append(f"  - 反對證據：{', '.join(oppose)}")
    lines.append("")

    lines.append("## 4. 信心說明")
    lines.append("")
    lines.append(f"### 信心等級：{result.conclusion.get('confidence', '未知')}")
    lines.append("")
    lines.append("### 已知限制")
    lines.append("")
    for lim in result.conclusion.get("limitations", []):
        lines.append(f"- {lim}")
    lines.append("")
    lines.append("### 可能推翻結論的條件")
    lines.append("")
    for cond in result.conclusion.get("invalidation_conditions", []):
        lines.append(f"- {cond}")
    lines.append("")

    lines.append("## 5. 後續觀察重點")
    lines.append("")
    if result.follow_up_watchpoints:
        for point in result.follow_up_watchpoints:
            lines.append(f"- {point}")
    else:
        lines.append("- （本次推理未產出具體後續觀察重點）")
    lines.append("")

    lines.append("## 附錄：信源分級依據（賽前信譽表）")
    lines.append("")
    lines.extend(reputation_appendix_lines())
    lines.append("")

    lines.append("---")
    lines.append(f"本報告共引用 {len(ev_by_id)} 筆證據，詳見 evidence.json。")

    return "\n".join(lines)

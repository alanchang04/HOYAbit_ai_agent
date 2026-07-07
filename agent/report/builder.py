"""組裝 report.md，並強制檢查報告中引用的 evidence id 必須存在於 evidence 清單中。"""

from __future__ import annotations

from agent.reasoning.pipeline import ReasoningResult
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
    return ids


def validate_evidence_references(result: ReasoningResult, evidences: list[Evidence]) -> None:
    known_ids = {e.id for e in evidences}
    referenced = _collect_referenced_ids(result)
    missing = referenced - known_ids
    if missing:
        raise EvidenceReferenceError(
            f"報告引用了不存在於 evidence.json 的 id: {sorted(missing)}"
        )


def build_report_markdown(
    coin: str,
    question: str,
    result: ReasoningResult,
    evidences: list[Evidence],
) -> str:
    validate_evidence_references(result, evidences)
    ev_by_id = {e.id for e in evidences}
    ev_lookup = {e.id: e for e in evidences}

    lines: list[str] = []
    lines.append(f"# {coin} 市場分析報告")
    lines.append("")
    lines.append(f"> 題目：{question}")
    lines.append(f"> 題型分類：{result.question_type}")
    lines.append("")

    lines.append("## 1. 結論／市場判斷")
    lines.append("")
    lines.append(result.conclusion.get("market_judgment", ""))
    lines.append("")

    lines.append("## 2. 關鍵依據")
    lines.append("")
    for fact in result.facts:
        ids = fact.get("evidence_ids", [])
        lines.append(f"- {fact.get('summary', '')}")
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
    lines.append("**一致訊號：**")
    for c in consistent:
        lines.append(f"- {c}")
    lines.append("")
    lines.append("**矛盾訊號：**")
    if contradictions:
        for c in contradictions:
            lines.append(f"- {c}")
    else:
        lines.append("- 本次未偵測到明顯矛盾訊號")
    lines.append("")
    lines.append("**推論假設：**")
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
    lines.append(f"- 信心等級：{result.conclusion.get('confidence', '未知')}")
    lines.append("- 已知限制：")
    for lim in result.conclusion.get("limitations", []):
        lines.append(f"  - {lim}")
    lines.append("- 可能推翻結論的條件：")
    for cond in result.conclusion.get("invalidation_conditions", []):
        lines.append(f"  - {cond}")
    lines.append("")

    lines.append("## 5. 後續觀察重點")
    lines.append("")
    lines.append("- （待補：依題型與市場狀況列出後續應追蹤的指標或事件）")
    lines.append("")

    lines.append("---")
    lines.append(f"本報告共引用 {len(ev_by_id)} 筆證據，詳見 evidence.json。")

    return "\n".join(lines)

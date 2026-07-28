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
    breakdown = result.confidence_breakdown or {}
    if breakdown:
        # 執行摘要就把「基底 vs 辯論調整」拆開，讀者第一眼就知道這個分數有沒有
        # 因為辯論而被下修，不用翻到第 4 節（R3-12）。
        adjustment = breakdown.get("debate_adjustment", 0)
        lines.append(
            f"> 信心：{result.confidence_score}%（{confidence_label}）"
            f"＝ 基底 {breakdown.get('base', 0):.0f} {adjustment:+d} 辯論調整"
            " ── 分項計算方式見「4. 信心說明」"
        )
    else:
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
        # 論證文字（bull_argument/bear_argument）已經是最後一輪，但頂層
        # bull_evidence_ids/bear_evidence_ids 是所有輪次的聯集——引用清單
        # 應該對齊「最後一輪」的文字，不然會列出文字裡其實沒提到的證據 id。
        rounds = debate.get("rounds", [])
        if rounds:
            last_round = rounds[-1]
            bull_ids = last_round.get("bull_evidence_ids", [])
            bear_ids = last_round.get("bear_evidence_ids", [])
        else:
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


HORIZON_LABEL: dict[str, str] = {
    "spot": "當日（日尺度）",
    "short": "近 10 日（短期）",
    "medium": "近一個月（中期）",
    "long": "近一季（長期）",
    "structural": "近一年以上（結構）",
}


def _describe_primary_horizon(result: ReasoningResult) -> str:
    """揭露本次的主判斷尺度與判定依據（R7-7）。

    讓讀者能檢查系統有沒有誤解題目的時間範圍——問「最近一年」卻判成中期，
    讀者一眼就能看出結論的尺度不對，這比默默用錯尺度分析好得多。
    """
    label = HORIZON_LABEL.get(result.primary_horizon, result.primary_horizon)
    if result.primary_horizon_basis:
        return f"{label}（依題目「{result.primary_horizon_basis}」判定）"
    return f"{label}（題目未明示時間範圍，採預設）"


def _build_confidence_breakdown_lines(result: ReasoningResult) -> list[str]:
    """信心分項表＋「這個分數怎麼來的」（R3-12/R3-13）。

    很多 AI 報告只給一個「High Confidence」就結束，讀者無從判斷該不該相信。
    這裡把三維分數、權重、辯論調整、以及每個未滿分項的具體原因全部攤開，
    讓讀者能逐項對帳。條列由 `confidence.build_why_lines()` 決定性生成，不經 LLM。
    """
    lines: list[str] = []
    breakdown = result.confidence_breakdown or {}

    if not breakdown:
        # 舊格式結果（或 fallback 路徑）沒有分項，誠實標示而不是假裝有。
        lines.append(f"### 信心等級：{result.conclusion.get('confidence', '未知')}")
        lines.append("")
        lines.append(f"本次信心分數：{result.confidence_score}%（未產出分項計算明細）")
        lines.append("")
        return lines

    weights = breakdown.get("weights", {})
    lines.append(f"### 信心分數：{breakdown.get('final', result.confidence_score)} / 100")
    lines.append("")
    lines.append("| 組成 | 分數 | 權重 | 說明 |")
    lines.append("|---|---:|---:|---|")
    for key, label, note in (
        ("data_confidence", "資料品質", "六類來源的完整度（筆數與窗長）"),
        ("signal_consensus", "訊號一致性", "來源之間的兩兩一致度"),
        ("evidence_strength", "證據強度", "來源權威度 × 類別覆蓋度"),
    ):
        weight_pct = f"{round(weights.get(key, 0) * 100)}%" if weights else "—"
        lines.append(f"| {label} | {breakdown.get(key, 0):.1f} | {weight_pct} | {note} |")
    lines.append(f"| **基底（三維加權）** | **{breakdown.get('base', 0):.1f}** | | |")

    adjustment = breakdown.get("debate_adjustment", 0)
    adjustment_reason = breakdown.get("debate_adjustment_reason", "") or "（本次未調整）"
    lines.append(f"| 辯論後調整 | {adjustment:+d} | | {adjustment_reason} |")
    lines.append(f"| **最終信心** | **{breakdown.get('final', result.confidence_score)}** | | |")
    lines.append("")

    if breakdown.get("signal_consensus_detail", {}).get("degraded"):
        reason = breakdown["signal_consensus_detail"].get("degraded_reason", "")
        lines.append(f"> ⚠ {reason}")
        lines.append("")

    why_lines = breakdown.get("why", [])
    if why_lines:
        lines.append("### 這個分數怎麼來的？")
        lines.append("")
        for line in why_lines:
            lines.append(f"- {line}")
        lines.append("")

    lines.append(f"### 信心等級：{result.conclusion.get('confidence', '未知')}")
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
    lines.append(f"> 主判斷尺度：{_describe_primary_horizon(result)}")
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

    # 結構脈絡與矛盾訊號**必須分開呈現**（R2-7/R2-8）。跨時間尺度的差異
    # （如「兩週情緒轉強，但價格仍處 5 年分佈第 88 百分位」）是位置關係，
    # 不是訊號衝突；混在矛盾裡會讓讀者以為資料在打架，也會讓信心被錯誤扣分。
    structural_context = result.cross_validation.get("structural_context", [])
    if structural_context:
        lines.append("### 結構脈絡（跨時間尺度的位置關係，不計入矛盾）")
        lines.append("")
        for item in structural_context:
            lines.append(f"- {item}")
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
    lines.extend(_build_confidence_breakdown_lines(result))
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

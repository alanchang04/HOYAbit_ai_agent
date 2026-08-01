"""組裝 report.md，並強制檢查報告中引用的 evidence id 必須存在於 evidence 清單中。"""

from __future__ import annotations

from agent.collectors.coin_map import SUPPORTED_COINS
from agent.filters.injection import escape_for_markdown
from agent.filters.source_weights import reputation_appendix_lines
from agent.reasoning.confidence import confidence_label
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
    for item in result.conclusion.get("debate_summary", []):
        ids.update(item.get("evidence_ids", []))
    return ids


def validate_evidence_references(result: ReasoningResult, evidences: list[Evidence]) -> None:
    known_ids = {e.id for e in evidences}
    referenced = _collect_referenced_ids(result)
    missing = referenced - known_ids
    if missing:
        raise EvidenceReferenceError(
            f"報告引用了不存在於 evidence.json 的 id: {sorted(missing)}"
        )


def _coins_with_evidence(coin: str, evidences: list[Evidence]) -> list[str]:
    """本次實際有證據的幣種（主幣在前，依證據出現順序去重）。

    **只認幣種池成員**：雙幣相對指標那筆證據的 `coin` 是 `"BTC/ETH"` 這種合成值，
    直接取 `e.coin` 會讓它變成一個假幣種混進清單。
    """
    seen = [coin.upper()]
    for e in evidences:
        c = (e.coin or "").upper()
        if c in SUPPORTED_COINS and c not in seen:
            seen.append(c)
    return seen


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

    label = _confidence_label_of(result)
    breakdown = result.confidence_breakdown or {}
    if breakdown:
        # 執行摘要就把「基底 vs 辯論調整」拆開，讀者第一眼就知道這個分數有沒有
        # 因為辯論而被下修，不用翻到第 4 節（R3-12）。
        adjustment = breakdown.get("debate_adjustment", 0)
        lines.append(
            f"> 信心：{result.confidence_score}%（{label}）"
            f"＝ 基底 {breakdown.get('base', 0):.0f} {adjustment:+d} 辯論調整"
            " ── 分項計算方式見「4. 信心說明」"
        )
    else:
        lines.append(
            f"> 信心：{result.confidence_score}%（{label}）"
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


def _build_debate_summary_lines(result: ReasoningResult) -> list[str]:
    """裁判整理的辯論重點摘要：讀者不用看完第 3 節兩輪逐字稿就能抓到攻防結果。

    放在執行摘要之後、結論之前——「快速看懂辯論打了什麼 → 再看最終結論」，
    完整逐字稿仍保留在第 3 節（收合呈現），滿足可回溯性但不強迫每個人都讀完。
    沒有辯論（fallback 路徑）或裁判未產出摘要時直接跳過整節，不硬擠一段空話。
    """
    points = result.conclusion.get("debate_summary", [])
    if not points:
        return []

    lines: list[str] = ["## 辯論重點摘要", ""]
    for item in points:
        point = item.get("point", "")
        ids = item.get("evidence_ids", [])
        # 無 id 的點必須看得出來。`_sanitize_debate_summary()` 只濾掉不存在的 evidence id，
        # 濾完變成空陣列時該點照樣保留——若這裡也不加註記，一條完全沒有證據支撐的
        # 「攻防結果」會跟有據可查的長得一模一樣，讀者無從分辨。
        suffix = f"（{', '.join(ids)}）" if ids else "（⚠ 未附可回溯的 evidence id）"
        lines.append(f"- {point}{suffix}")
    lines.append("")
    return lines


# markdown 表格儲存格放得下的字數上限；超過就改放摘要＋表格下方列完整版
TABLE_CELL_MAX_CHARS = 80


def _table_safe(text: str) -> str:
    """把可能含換行／過長的文字壓成適合放進 markdown 表格儲存格的單行摘要。"""
    flat = " ".join(text.split()).replace("|", "｜")
    if len(flat) <= TABLE_CELL_MAX_CHARS:
        return flat
    return flat[:TABLE_CELL_MAX_CHARS] + "…（完整理由見下方）"


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


def _primary_horizon_gap_note(result: ReasoningResult, evidences: list[Evidence]) -> str | None:
    """主視野帶完全無證據時的揭露（R7-6）。

    問「最近一年」但一年尺度一筆資料都沒有，系統實際上是用別的尺度回答的——
    這件事必須講明，否則讀者會以為結論真的建立在他問的那個時間尺度上。
    """
    primary = result.primary_horizon
    if any(e.horizon_class.value == primary for e in evidences):
        return None
    available = sorted(
        {e.horizon_class.value for e in evidences},
        key=lambda v: list(HORIZON_LABEL).index(v) if v in HORIZON_LABEL else 99,
    )
    if not available:
        return None
    label = HORIZON_LABEL.get(primary, primary)
    available_labels = "、".join(HORIZON_LABEL.get(v, v) for v in available)
    return (
        f"> ⚠ 本次主判斷尺度為{label}，但該尺度**無可用證據**；"
        f"以下判斷實際依據的是{available_labels}的資料，請據此調整對結論適用範圍的預期。"
    )


def _confidence_label_of(result: ReasoningResult) -> str:
    """報告顯示用的信心等級，一律由決定性分數推得（`confidence.confidence_label()`）。

    2026-08-01 前這裡讀的是 `conclusion["confidence"]`——LLM 在 Step D 自報的高/中/低。
    那個欄位與分數是兩套獨立系統、沒有任何一致性檢查，理論上可以印出「信心：92%（低）」；
    實測也證明兩者脫鉤（辯論調整從 −3 翻到 +3 時，自報等級一動也沒動）。
    LLM 的欄位仍保留在 JSON 裡，只是不再作為顯示來源，分歧時由
    `_confidence_divergence_note()` 揭露而非隱藏。
    """
    return confidence_label(result.confidence_score)


def _confidence_divergence_note(result: ReasoningResult) -> str:
    """決定性等級與 LLM 自報等級不一致時的揭露文字；一致或無自報值時回空字串。"""
    llm_label = (result.conclusion or {}).get("confidence", "")
    derived = _confidence_label_of(result)
    if llm_label in ("高", "中", "低") and llm_label != derived:
        return (
            f"> ℹ️ 裁判自報的信心等級為「{llm_label}」，與分數推得的「{derived}」不一致。"
            f"報告採用分數推得的等級（可複現）；此處揭露差異供對帳。"
        )
    return ""


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
        lines.append(f"### 信心等級：{_confidence_label_of(result)}")
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
    full_reason = breakdown.get("debate_adjustment_reason", "")
    # 表格儲存格必須是單行短文字。prompt 已限 80 字，但 LLM 不保證遵守——
    # 實測有回過 700+ 字的評析把表格整個撐爆，所以呈現層也要防守：
    # 表格放摘要，完整理由改列在表格下方。
    cell_reason = _table_safe(full_reason) if full_reason else "（本次未調整）"
    # 逐點判定加總時，儲存格優先放「怎麼算出來的」——讀者可以自己驗算，
    # 比裁判的散文理由更有稽核價值（散文理由仍完整列在表格下方）。
    verdict_detail = breakdown.get("debate_verdict_detail", "")
    if verdict_detail:
        cell_reason = _table_safe(verdict_detail)
    lines.append(f"| 辯論後調整 | {adjustment:+d} | | {cell_reason} |")
    lines.append(f"| **最終信心** | **{breakdown.get('final', result.confidence_score)}** | | |")
    lines.append("")

    if full_reason and (verdict_detail or len(full_reason) > TABLE_CELL_MAX_CHARS):
        lines.append("**辯論調整的完整理由：**")
        lines.append("")
        lines.append(normalize_embedded_lists(full_reason))
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

    lines.append(f"### 信心等級：{_confidence_label_of(result)}")
    lines.append("")
    divergence = _confidence_divergence_note(result)
    if divergence:
        lines.append(divergence)
        lines.append("")
    return lines


def build_report_markdown(
    coin: str,
    question: str,
    result: ReasoningResult,
    evidences: list[Evidence],
    coin2: str | None = None,
    uncovered_coins: list[str] | None = None,
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
    horizon_gap = _primary_horizon_gap_note(result, evidences)
    if horizon_gap:
        lines.append(horizon_gap)
        lines.append("")

    # 題目提到、但本次沒有蒐集到證據的幣種。放在報告最上方而不是塞進「已知限制」
    # 條列裡——讀者必須在讀任何比較結論之前就知道「這份比較少了誰」，
    # 否則會誤以為結論涵蓋了題目要求的全部對象。
    if uncovered_coins:
        # 涵蓋清單要用「實際有證據的所有幣種」，不能只印 coin/coin2——
        # 三個幣種時 coin2 只裝得下第二個，印出來會少報一個已分析的幣。
        covered_coins = _coins_with_evidence(coin, evidences)
        covered = "／".join(covered_coins)
        lines.append(
            f"> ⚠ 題目提到 **{'、'.join(uncovered_coins)}**，但本次**未蒐集其證據**，"
            f"以下比較僅涵蓋 {covered}。缺漏對象的任何結論都不應由本報告推得。"
        )
        lines.append("")

    lines.extend(_build_executive_summary_lines(result))
    lines.extend(_build_debate_summary_lines(result))

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
                # 這一列是 ` | ` 分欄，且 report.md 會被 Web UI 以 markdown 渲染後
                # `| safe` 輸出——外部來源的內文必須跳脫，否則一個 Reddit 標題就能
                # 拆掉欄位或在頁面上執行 JS（見 agent/filters/injection.py）。
                flag = "⚠️[疑似注入內容] " if ev.injection_flag else ""
                lines.append(
                    f"  - `{eid}` | {escape_for_markdown(ev.source)} | {ev.fetched_at} | "
                    f"{flag}{escape_for_markdown(ev.content_reference)}"
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
        # 有「辯論重點摘要」可看時，完整逐字稿改預設收合——讀者已經在最上方
        # 看過攻防結果，這裡是查證據用的原文，不需要強迫每個人往下讀兩輪。
        # 沒有摘要時（fallback／裁判未產出）逐字稿是唯一內容，不收合。
        collapse = bool(result.conclusion.get("debate_summary"))
        if collapse:
            lines.append('<details markdown="1">')
            lines.append(f"<summary>{heading.lstrip('# ').strip()}（點擊展開完整逐輪紀錄）</summary>")
            lines.append("")
        else:
            lines.append(heading)
        lines.append("")
        if len(debate_rounds) > 1:
            # 反方每輪有「批評＋論證」兩段、正方只有一段，版面音量天然是 2:1。
            # 那是輸出欄位的結構差異，不是論據強弱——不講明的話讀者（和裁判）
            # 容易把「講得多」讀成「比較有理」（STATUS.md 待辦 12⑥）。
            lines.append(
                "> 版面說明：反方每輪有「批評」與「論證」兩段，正方只有一段，"
                "篇幅差異來自輸出結構而非論據強弱。正方第 2 輪起的論證本身"
                "即包含對反方批評的逐項回應。"
            )
            lines.append("")
        for rd in debate_rounds:
            round_no = rd.get("round", 1)
            if len(debate_rounds) > 1:
                lines.append(f"**第 {round_no} 輪**")
                lines.append("")
            bull_label = (
                "*正方立論：*" if round_no == 1 else "*正方回應反方批評並修正論證：*"
            )
            lines.append(bull_label)
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
            lines.append("*反方立論：*")
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
        if collapse:
            lines.append("</details>")
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

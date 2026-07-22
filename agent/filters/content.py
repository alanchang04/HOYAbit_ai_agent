"""L2 內容層過濾：拉盤話術偵測（R12-4）＋F9 情緒分布分析（詞典法）。

全部 check 為純程式（零 LLM 呼叫、毫秒級），英文語料優先。

R12 改版後的角色分工：
- 拉盤話術：命中 → 來源等級降一級（在 source_weights 四因子的等級層處理，
  取代舊制 ×0.5；與 dedup_penalty 是獨立維度、允許疊加，非重複扣分）。
  本模組負責「掃描」與「產生 FilterDecision 紀錄」；權重數字由 L1 算定。
- 近重複/轉載偵測：已由 `agent/filters/dedup.py`（Phase 2 去重）接手，
  舊的模板相似度檢查（F10）退役。
- F9 情緒分布：詞典法 MVP——統計敘事類證據的正/負面情緒分布與單向偏斜，
  純觀察性指標（不改權重），供面板③與報告限制欄使用。
"""

from __future__ import annotations

import re

from agent.logging_utils import ExecutionLogger
from agent.schemas import (
    Evidence,
    FilterDecision,
    FilterVerdict,
    LogPhase,
    LogStatus,
    PipelineLayer,
    SourceType,
)

# --- 拉盤話術詞典（英文優先；與 Ken 詞庫的合併仍待對齊，見 team-division.md） ---

PR_TERMS: list[str] = [
    "skyrocket",
    "to the moon",
    "guaranteed",
    "once-in-a-lifetime",
    "can't miss",
    "100x",
    "explode",
    "moonshot",
    "暴漲",
    "千載難逢",
]

# --- F9 情緒詞典（詞典法 MVP：word-boundary 比對，只掃敘事類證據） ---

F9_POSITIVE_TERMS: list[str] = [
    "surge",
    "rally",
    "bullish",
    "breakout",
    "adoption",
    "inflow",
    "accumulation",
    "upgrade",
    "partnership",
    "approval",
    "record high",
    "all-time high",
    "soar",
    "institutional demand",
]

F9_NEGATIVE_TERMS: list[str] = [
    "crash",
    "plunge",
    "bearish",
    "hack",
    "exploit",
    "lawsuit",
    "ban",
    "outflow",
    "liquidation",
    "dump",
    "decline",
    "fraud",
    "bankruptcy",
    "capitulation",
]

# 單向情緒占比達此值且樣本足夠時，標記羊群/帶風向警示
F9_HERDING_THRESHOLD = 0.8
F9_MIN_SAMPLE = 5

F9_STATUS: dict = {"enabled": True, "method": "lexicon"}

_NARRATIVE_TYPES = (SourceType.NEWS, SourceType.SOCIAL)


# --- 拉盤話術 ---


def scan_pr_terms(evidences: list[Evidence]) -> dict[str, str]:
    """掃描全部證據，回傳 {evidence_id: 第一個命中的話術詞}。

    結果交給 L1 四因子權重做「來源等級降一級」（R12-4）。
    """
    hits: dict[str, str] = {}
    for ev in evidences:
        content_lower = ev.content_reference.lower()
        for term in PR_TERMS:
            if term.lower() in content_lower:
                hits[ev.id] = term
                break
    return hits


def check_pr_language(evidences: list[Evidence]) -> list[FilterDecision]:
    """舊制 PR 偵測（fallback 路徑用）：命中則權重 ×0.5（下限 0.05）。

    僅在信譽表載入失敗、L1 退回舊制規則表時使用（R12-5）。
    """
    decisions: list[FilterDecision] = []
    for ev in evidences:
        content_lower = ev.content_reference.lower()
        hit_term: str | None = None
        for term in PR_TERMS:
            if term.lower() in content_lower:
                hit_term = term
                break
        if hit_term is not None:
            weight_before = ev.source_weight
            weight_after = max(weight_before * 0.5, 0.05)
            decisions.append(
                FilterDecision(
                    evidence_id=ev.id,
                    check_code="PR",
                    verdict=FilterVerdict.DOWNWEIGHTED,
                    reason=f"命中 PR 話術「{hit_term}」，權重 {weight_before:.2f} → {weight_after:.2f}",
                    weight_before=weight_before,
                    weight_after=weight_after,
                )
            )
    return decisions


# --- F9 情緒分布（詞典法） ---


def _count_term_hits(text: str, terms: list[str]) -> int:
    text_lower = text.lower()
    count = 0
    for term in terms:
        if re.search(rf"(?<!\w){re.escape(term.lower())}(?!\w)", text_lower):
            count += 1
    return count


def check_sentiment_distribution(evidences: list[Evidence]) -> dict:
    """F9：統計敘事類（news/social）證據的情緒分布，回傳彙總 dict。

    - 已被 Phase 2 去重剔除的證據不納入（避免聯播稿灌高單向情緒）
    - 純觀察性：不產生權重變更；單向占比 ≥80% 且樣本 ≥5 時標 herding_flag
    """
    labels: dict[str, str] = {}
    positive = negative = neutral = 0
    for ev in evidences:
        if ev.source_type not in _NARRATIVE_TYPES:
            continue
        if ev.duplicate_of is not None:
            continue
        pos = _count_term_hits(ev.content_reference, F9_POSITIVE_TERMS)
        neg = _count_term_hits(ev.content_reference, F9_NEGATIVE_TERMS)
        if pos > neg:
            labels[ev.id] = "positive"
            positive += 1
        elif neg > pos:
            labels[ev.id] = "negative"
            negative += 1
        else:
            labels[ev.id] = "neutral"
            neutral += 1

    sample = len(labels)
    directional_max = max(positive, negative)
    one_sided_ratio = round(directional_max / sample, 4) if sample else 0.0
    herding_flag = sample >= F9_MIN_SAMPLE and one_sided_ratio >= F9_HERDING_THRESHOLD

    note = f"敘事類樣本 {sample} 筆：正面 {positive}／負面 {negative}／中性 {neutral}"
    if herding_flag:
        note += f"；單向情緒占比 {one_sided_ratio:.0%}，注意羊群/帶風向風險"
    elif sample == 0:
        note = "無敘事類證據可分析"

    return {
        "enabled": True,
        "method": "lexicon",
        "sample": sample,
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "one_sided_ratio": one_sided_ratio,
        "herding_flag": herding_flag,
        "note": note,
        "labels": labels,
    }


# --- 主入口 ---


def apply_content_filters(
    evidences: list[Evidence],
    logger: ExecutionLogger,
    pr_hits: dict[str, str] | None = None,
    breakdowns: dict | None = None,
) -> list[FilterDecision]:
    """執行 L2 內容層過濾，回傳 FilterDecision 清單。

    - 四因子模式（breakdowns 內有 formula="four_factor"）：PR 命中的權重
      變化已由 L1 在等級層算定，這裡只產生對帳用的 FilterDecision
    - 舊制 fallback 模式：沿用 ×0.5 降權並實際修改權重（R12-5）
    - F9 情緒分布：兩種模式都執行（觀察性，不動權重）
    """
    if pr_hits is None:
        pr_hits = scan_pr_terms(evidences)

    four_factor_mode = bool(breakdowns) and any(
        getattr(b, "formula", "") == "four_factor" for b in breakdowns.values()
    )

    decisions: list[FilterDecision] = []
    if four_factor_mode:
        for ev_id, term in pr_hits.items():
            b = breakdowns.get(ev_id)
            if b is None or getattr(b, "pr_term", None) is None:
                continue  # 例如已被去重剔除者，不再重複記 PR
            decisions.append(
                FilterDecision(
                    evidence_id=ev_id,
                    check_code="PR",
                    verdict=FilterVerdict.DOWNWEIGHTED,
                    reason=(
                        f"命中拉盤話術「{term}」→來源等級 "
                        f"{b.level_name_before_demotion}→{b.level_name}"
                        f"（{b.weight_before_demotion:.2f}→{b.final_weight:.2f}）；"
                        "與 dedup_penalty 為獨立維度、允許疊加（非重複扣分）"
                    ),
                    weight_before=b.weight_before_demotion,
                    weight_after=b.final_weight,
                )
            )
    else:
        pr_decisions = check_pr_language(evidences)
        decisions.extend(pr_decisions)
        # 舊制路徑：實際套用 ×0.5 權重
        weight_map = {d.evidence_id: d.weight_after for d in pr_decisions}
        for ev in evidences:
            if ev.id in weight_map and weight_map[ev.id] is not None:
                ev.source_weight = weight_map[ev.id]

    for d in decisions:
        logger.log(
            phase=LogPhase.COLLECT,
            action=f"l2_{d.check_code.lower()}_filter",
            detail=f"{d.evidence_id}: {d.reason}",
            status=LogStatus.OK,
            layer=PipelineLayer.CONTENT,
            metrics={
                "evidence_id": d.evidence_id,
                "check_code": d.check_code,
                "verdict": d.verdict.value,
                "weight_before": d.weight_before,
                "weight_after": d.weight_after,
            },
        )

    # F9 情緒分布（觀察性）
    f9_summary = check_sentiment_distribution(evidences)
    logger.log(
        phase=LogPhase.COLLECT,
        action="l2_f9_sentiment",
        detail=f9_summary["note"],
        status=LogStatus.OK,
        layer=PipelineLayer.CONTENT,
        metrics={k: v for k, v in f9_summary.items() if k != "labels"},
    )

    pr_count = sum(1 for d in decisions if d.check_code == "PR")
    logger.log(
        phase=LogPhase.COLLECT,
        action="l2_content_summary",
        detail=(
            f"PR_hits={pr_count}, mode={'four_factor' if four_factor_mode else 'legacy'}, "
            f"F9_sample={f9_summary['sample']}"
        ),
        status=LogStatus.OK,
        layer=PipelineLayer.CONTENT,
        metrics={
            "pr_hits": pr_count,
            "downweighted_total": sum(
                1 for d in decisions if d.verdict == FilterVerdict.DOWNWEIGHTED
            ),
            "mode": "four_factor" if four_factor_mode else "legacy",
            "f9": {
                "enabled": True,
                "sample": f9_summary["sample"],
                "herding_flag": f9_summary["herding_flag"],
            },
            "total_evidences": len(evidences),
        },
    )

    return decisions

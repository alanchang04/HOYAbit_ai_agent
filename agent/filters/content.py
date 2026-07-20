"""L2 內容層過濾：PR 話術偵測＋模板相似度＋F9 佔位。

全部 check 為純程式（零 LLM 呼叫、毫秒級），英文語料優先。
"""

from __future__ import annotations

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

# --- PR 話術詞典（英文優先） ---

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

# --- F9 情緒分布佔位 ---

F9_STATUS: dict[str, bool] = {"enabled": False}


# --- 內部工具函式 ---


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """計算兩段文字的小寫 token 集合 Jaccard 相似度。"""
    tokens_a = set(text_a.lower().split())
    tokens_b = set(text_b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _clamp_weight(weight: float, lower: float = 0.05) -> float:
    """確保權重不低於下限。"""
    return max(weight, lower)


# --- 檢查函式 ---


def check_pr_language(evidences: list[Evidence]) -> list[FilterDecision]:
    """PR 話術偵測：命中 PR_TERMS 的證據降權 ×0.5（下限 0.05）。

    每筆證據最多產出一個 FilterDecision（即使命中多個詞，只記第一個命中詞）。
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
            weight_after = _clamp_weight(weight_before * 0.5)
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


def check_template_similarity(evidences: list[Evidence]) -> list[FilterDecision]:
    """模板相似度：news/social 證據的 content_reference Jaccard ≥0.8 → 非獨立來源。

    配對中 index 較大者（後到者）權重 ×0.6。兩筆都產出 FilterDecision。
    """
    decisions: list[FilterDecision] = []
    # 只比較 news/social 類型的證據
    eligible = [
        (i, ev)
        for i, ev in enumerate(evidences)
        if ev.source_type in (SourceType.NEWS, SourceType.SOCIAL)
    ]

    # 追蹤已標記的 evidence_id，避免同一筆因多組配對重複標記
    marked: set[str] = set()

    for idx_a in range(len(eligible)):
        for idx_b in range(idx_a + 1, len(eligible)):
            _, ev_a = eligible[idx_a]
            _, ev_b = eligible[idx_b]

            sim = _jaccard_similarity(ev_a.content_reference, ev_b.content_reference)
            if sim < 0.8:
                continue

            # 兩筆都標記 FilterDecision
            if ev_a.id not in marked:
                decisions.append(
                    FilterDecision(
                        evidence_id=ev_a.id,
                        check_code="F10",
                        verdict=FilterVerdict.DOWNWEIGHTED,
                        reason=f"near-duplicate of {ev_b.id}（非獨立來源）",
                        weight_before=ev_a.source_weight,
                        weight_after=ev_a.source_weight,  # 先到者不調權
                    )
                )
                marked.add(ev_a.id)

            if ev_b.id not in marked:
                # 後到者降權 ×0.6
                weight_before = ev_b.source_weight
                weight_after = _clamp_weight(weight_before * 0.6)
                decisions.append(
                    FilterDecision(
                        evidence_id=ev_b.id,
                        check_code="F10",
                        verdict=FilterVerdict.DOWNWEIGHTED,
                        reason=f"near-duplicate of {ev_a.id}（非獨立來源）",
                        weight_before=weight_before,
                        weight_after=weight_after,
                    )
                )
                marked.add(ev_b.id)

    return decisions


def apply_content_filters(
    evidences: list[Evidence], logger: ExecutionLogger
) -> list[FilterDecision]:
    """執行全部 L2 內容層過濾，回傳所有 FilterDecision。

    1. PR check
    2. Template similarity check
    3. Apply weight changes to evidences
    4. Log each FilterDecision individually (layer=L2_content)
    5. Log summary metrics
    """
    all_decisions: list[FilterDecision] = []

    # 1. PR 話術偵測
    pr_decisions = check_pr_language(evidences)
    all_decisions.extend(pr_decisions)

    # 2. 模板相似度偵測
    sim_decisions = check_template_similarity(evidences)
    all_decisions.extend(sim_decisions)

    # 3. Apply weight changes to evidences
    weight_map: dict[str, float] = {}
    for d in all_decisions:
        if d.weight_after is not None:
            # 如果同一筆有多個 decision，取最低權重
            if d.evidence_id in weight_map:
                weight_map[d.evidence_id] = min(weight_map[d.evidence_id], d.weight_after)
            else:
                weight_map[d.evidence_id] = d.weight_after

    for ev in evidences:
        if ev.id in weight_map:
            ev.source_weight = weight_map[ev.id]

    # 4. Log each FilterDecision individually
    for d in all_decisions:
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

    # 5. Log summary metrics
    pr_hits = sum(1 for d in all_decisions if d.check_code == "PR")
    sim_pairs = sum(1 for d in all_decisions if d.check_code == "F10")
    downweighted_count = sum(
        1 for d in all_decisions if d.verdict == FilterVerdict.DOWNWEIGHTED
    )

    logger.log(
        phase=LogPhase.COLLECT,
        action="l2_content_summary",
        detail=(
            f"PR_hits={pr_hits}, similarity_marks={sim_pairs}, "
            f"downweighted={downweighted_count}, F9={F9_STATUS}"
        ),
        status=LogStatus.OK,
        layer=PipelineLayer.CONTENT,
        metrics={
            "pr_hits": pr_hits,
            "similarity_marks": sim_pairs,
            "downweighted_total": downweighted_count,
            "f9": F9_STATUS,
            "total_evidences": len(evidences),
        },
    )

    return all_decisions

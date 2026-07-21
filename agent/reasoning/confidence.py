"""L5 數值信心公式：base＋權威加成−矛盾−缺口，夾 5–95。

公式各項 SHALL 寫入 log metrics 可對帳（layer=L5_conclusion）。
"""

from __future__ import annotations

from agent.schemas import Evidence, SourceType

# 五類來源完整集合
SOURCE_TYPE_CATEGORIES: set[SourceType] = {
    SourceType.PRICE,
    SourceType.ONCHAIN,
    SourceType.NEWS,
    SourceType.SOCIAL,
    SourceType.MACRO,
}

# 信心基底值
CONFIDENCE_BASE: dict[str, int] = {"高": 75, "中": 55, "低": 35}


def compute_confidence_score(
    conclusion_confidence: str,
    evidences: list[Evidence],
    contradictions_count: int,
) -> tuple[int, dict]:
    """計算 L5 數值信心分數，回傳 (score, breakdown_dict)。

    公式：
        base(高75/中55/低35)
        + 權威源占比加成(≤+10)
        − 矛盾訊號×5(下限−15)
        − 缺失來源類別×5(下限−15)
    結果夾在 5–95。
    """
    base = CONFIDENCE_BASE.get(conclusion_confidence, 35)

    # 權威源占比加成（weight ≥ 0.7 的證據數 / 總數 × 10，取整，上限 10）
    auth_count = sum(1 for e in evidences if e.source_weight >= 0.7)
    total = len(evidences)
    auth_bonus = round(10 * auth_count / total) if total > 0 else 0
    auth_bonus = min(auth_bonus, 10)

    # 矛盾訊號懲罰（每個 ×5，上限 15）
    contradiction_penalty = min(15, 5 * contradictions_count)

    # 缺失來源類別懲罰（5 類中證據數為 0 的類別 ×5，上限 15）
    present_types = {e.source_type for e in evidences}
    missing_types = SOURCE_TYPE_CATEGORIES - present_types
    gap_penalty = min(15, 5 * len(missing_types))

    # Clamp 5–95
    raw = base + auth_bonus - contradiction_penalty - gap_penalty
    score = max(5, min(95, raw))

    breakdown = {
        "base": base,
        "base_label": conclusion_confidence,
        "auth_bonus": auth_bonus,
        "auth_count": auth_count,
        "total_evidences": total,
        "contradiction_penalty": contradiction_penalty,
        "contradictions_count": contradictions_count,
        "gap_penalty": gap_penalty,
        "missing_source_types": sorted(t.value for t in missing_types),
        "final": score,
    }
    return score, breakdown

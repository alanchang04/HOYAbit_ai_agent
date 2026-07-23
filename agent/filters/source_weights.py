"""L1 信源權重：靜態查表為每筆證據分配 source_weight + weight_reason。

規則依序比對，第一個命中即回傳（first match wins）。
"""

from __future__ import annotations

from agent.logging_utils import ExecutionLogger
from agent.schemas import Evidence, LogPhase, LogStatus, PipelineLayer, SourceType

# --- 靜態權重規則表（順序決定優先權） ---

_SOURCE_KEYWORD_RULES: list[tuple[list[str], float, str]] = [
    (
        ["HOYA BIT 共同基準", "本地技術指標"],
        0.95,
        "官方基準資料／決定性本地運算",
    ),
]

_SOURCE_TYPE_RULES_BEFORE_KEYWORD: list[tuple[SourceType, float, str]] = [
    # onchain 在關鍵字規則之後、其他 source 關鍵字規則之前
]

_SOURCE_KEYWORD_RULES_AFTER_ONCHAIN: list[tuple[list[str], float, str]] = [
    (
        ["CoinGecko", "CryptoCompare"],
        0.80,
        "交易所聚合行情 API",
    ),
]

_SOURCE_TYPE_FALLBACK: dict[SourceType, tuple[float, str]] = {
    SourceType.ONCHAIN: (0.85, "鏈上公開 RPC，數據不可竄改"),
    SourceType.DERIVATIVES: (0.80, "交易所/CFTC 公開衍生品數據（費率、OI、倉位），非個人言論；比照 onchain 定性，略低是因為單一交易所報價可能有做市偏差"),
    SourceType.MACRO: (0.65, "公開指數/央行匯率"),
    SourceType.NEWS: (0.60, "主流媒體，未逐篇查證"),
    SourceType.SOCIAL: (0.30, "未經查證社群內容"),
}

# 若所有規則都未命中的兜底值（理論上不應發生，但防禦性設計）
_DEFAULT_WEIGHT = 0.50
_DEFAULT_REASON = "未匹配任何靜態規則，使用預設權重"


def assign_source_weight(evidence: Evidence) -> tuple[float, str]:
    """根據靜態權重表為證據分配信源權重，回傳 (weight, reason)。

    比對順序：
    1. source 含 "HOYA BIT 共同基準" 或 "本地技術指標" → 0.95
    2. source_type == onchain → 0.85
    3. source 含 "CoinGecko" 或 "CryptoCompare" → 0.80
    4. source_type == macro → 0.65
    5. source_type == news → 0.60
    6. source_type == social → 0.30
    """
    source_lower = evidence.source.lower()

    # Rule 1: 官方基準 / 本地指標（關鍵字）
    for keyword in _SOURCE_KEYWORD_RULES[0][0]:
        if keyword.lower() in source_lower:
            return _SOURCE_KEYWORD_RULES[0][1], _SOURCE_KEYWORD_RULES[0][2]

    # Rule 2: onchain source_type
    if evidence.source_type == SourceType.ONCHAIN:
        return _SOURCE_TYPE_FALLBACK[SourceType.ONCHAIN]

    # Rule 3: CoinGecko / CryptoCompare（關鍵字）
    for keyword in _SOURCE_KEYWORD_RULES_AFTER_ONCHAIN[0][0]:
        if keyword.lower() in source_lower:
            return _SOURCE_KEYWORD_RULES_AFTER_ONCHAIN[0][1], _SOURCE_KEYWORD_RULES_AFTER_ONCHAIN[0][2]

    # Rule 4-6: source_type fallback
    if evidence.source_type in _SOURCE_TYPE_FALLBACK:
        return _SOURCE_TYPE_FALLBACK[evidence.source_type]

    # 兜底
    return _DEFAULT_WEIGHT, _DEFAULT_REASON


def apply_source_weights(evidences: list[Evidence], logger: ExecutionLogger) -> None:
    """對所有證據統一補權重並寫 L1 彙總 log。"""
    weight_distribution: dict[str, int] = {}

    for e in evidences:
        weight, reason = assign_source_weight(e)
        e.source_weight = weight
        e.weight_reason = reason

        # 統計各權重級距分佈
        bucket = f"{weight:.2f}"
        weight_distribution[bucket] = weight_distribution.get(bucket, 0) + 1

    avg_weight = (
        sum(e.source_weight for e in evidences) / len(evidences) if evidences else 0.0
    )

    logger.log(
        phase=LogPhase.COLLECT,
        action="l1_source_weights",
        detail=f"total={len(evidences)}, avg_weight={avg_weight:.3f}",
        status=LogStatus.OK,
        layer=PipelineLayer.SOURCE,
        metrics={
            "total": len(evidences),
            "avg_weight": round(avg_weight, 4),
            "distribution": weight_distribution,
        },
    )

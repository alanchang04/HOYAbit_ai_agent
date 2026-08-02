"""v1 執行完整性判定：區分完整、資料部分缺失與管線降級。"""

from __future__ import annotations

from dataclasses import dataclass

from agent.schemas import Evidence


COIN_SOURCE_TYPES = {"price", "onchain", "news", "social", "derivatives"}
GLOBAL_SOURCE_TYPES = {"macro"}


@dataclass(frozen=True)
class IntegrityAssessment:
    status: str
    reasons: list[str]


def assess_integrity(
    evidences: list[Evidence],
    coins: list[str],
    degraded_reasons: list[str] | None = None,
) -> IntegrityAssessment:
    """判定 INTACT / PARTIAL / DEGRADED。

    - DEGRADED：硬性 deadline、推理或管線層失敗，或完全沒有證據。
    - PARTIAL：主流程完成，但指定幣種缺少一個以上預期資料類型。
    - INTACT：所有預期類型皆至少有一筆可回溯證據。
    """
    hard_failures = list(dict.fromkeys(degraded_reasons or []))
    if not evidences:
        hard_failures.append("未取得任何可用證據")
    if hard_failures:
        return IntegrityAssessment("DEGRADED", hard_failures)

    missing: list[str] = []
    for coin in coins:
        available = {
            evidence.source_type.value
            for evidence in evidences
            if evidence.coin.upper() == coin.upper() and evidence.duplicate_of is None
        }
        for source_type in sorted(COIN_SOURCE_TYPES - available):
            missing.append(f"{coin.upper()} 缺少 {source_type} 資料")

    available_global = {
        evidence.source_type.value
        for evidence in evidences
        if evidence.duplicate_of is None
    }
    for source_type in sorted(GLOBAL_SOURCE_TYPES - available_global):
        missing.append(f"缺少 {source_type} 全域資料")

    if missing:
        return IntegrityAssessment("PARTIAL", missing)
    return IntegrityAssessment("INTACT", [])

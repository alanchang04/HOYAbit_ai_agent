"""L1 信源權重：四因子信任評分（R12-3，設計權威 Ken《07_流程圖迭代定案.md》）。

    w = 新鮮度 × 來源等級 × 覆蓋度 × dedup_penalty

- 新鮮度：fetched_at 距執行當下的小時數，查 static/source_reputation.json 分級
- 來源等級：查賽前信譽表（first match wins），拉盤話術命中則降一級（R12-4，
  取代舊制 ×0.5；與 dedup_penalty 是獨立維度、允許疊加）
- 覆蓋度：去重後獨立來源數（僅敘事類適用；≠「覆蓋率」＝collector 成功率，
  該量用於 L5 信心公式，兩者不可混用）
- dedup_penalty：dedup_rate 分段映射（暫定曲線待 Ken 校準）；raw_count <
  min_sample 固定為 1（R12-3d）

信譽表載入失敗或計算出錯時，退回本檔底部的舊制靜態規則表（R12-5 fallback，
不中斷流程），並在 L1 彙總 log 標 formula=legacy_fallback。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent.filters.trust_config import load_reputation_config
from agent.logging_utils import ExecutionLogger
from agent.schemas import Evidence, LogPhase, LogStatus, PipelineLayer, SourceType

if TYPE_CHECKING:  # 僅型別標註用，避免 runtime 循環匯入
    from agent.filters.dedup import DedupResult

# 權重下限（與 L2 舊制一致）
WEIGHT_FLOOR = 0.05
# 被去重剔除者直接壓到下限
DUPLICATE_WEIGHT = WEIGHT_FLOOR


@dataclass
class WeightBreakdown:
    """單筆證據的四因子分解，供 L2 產生 FilterDecision 與面板對帳。"""

    evidence_id: str
    formula: str  # "four_factor" | "legacy_fallback" | "duplicate"
    freshness: float = 1.0
    level_name: str = ""
    level_factor: float = 1.0
    level_rationale: str = ""
    coverage_factor: float = 1.0
    dedup_factor: float = 1.0
    final_weight: float = 0.0
    # PR 話術降級紀錄（R12-4）
    pr_term: str | None = None
    level_name_before_demotion: str | None = None
    weight_before_demotion: float | None = None


# --- 四因子各項計算 ---


def _freshness_factor(fetched_at: str, config: dict, now: datetime) -> tuple[float, float]:
    """回傳 (factor, age_hours)。fetched_at 已由 schema 驗證為 ISO8601。"""
    fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - fetched).total_seconds() / 3600)
    fresh_cfg = config.get("freshness", {})
    for tier in fresh_cfg.get("tiers", []):
        if age_hours <= tier["max_age_hours"]:
            return float(tier["factor"]), age_hours
    return float(fresh_cfg.get("default_factor", 1.0)), age_hours


def _match_level(evidence: Evidence, config: dict) -> tuple[str, str]:
    """信譽表 first match wins，回傳 (level_name, rationale)。"""
    source_lower = evidence.source.lower()
    for rule in config["rules"]:
        keywords = rule.get("keywords")
        if keywords:
            if any(kw.lower() in source_lower for kw in keywords):
                return rule["level"], rule.get("rationale", "")
            continue
        if rule.get("source_type") == evidence.source_type.value:
            return rule["level"], rule.get("rationale", "")
    default = config.get("default", {})
    return default.get("level", config["level_order"][-1]), default.get(
        "rationale", "未匹配任何信譽表規則"
    )


def _demote_level(level_name: str, config: dict) -> str:
    """來源等級降 demote_levels 級（R12-4），到底線後不再降。"""
    order: list[str] = config["level_order"]
    steps = int(config.get("pr_demotion", {}).get("demote_levels", 1))
    idx = order.index(level_name) if level_name in order else len(order) - 1
    return order[min(idx + steps, len(order) - 1)]


def _coverage_factor(evidence: Evidence, config: dict, dedup_result: "DedupResult | None") -> tuple[float, int | None]:
    """覆蓋度因子：去重後獨立來源數 → 分段映射。非適用類型固定 1.0。"""
    cov_cfg = config.get("coverage", {})
    if evidence.source_type.value not in cov_cfg.get("applies_to", []):
        return 1.0, None
    if dedup_result is None:
        return 1.0, None
    stats = dedup_result.stats_for(evidence)
    if stats is None:
        return 1.0, None
    distinct = stats.distinct_sources
    # tiers 依 min_distinct_sources 由大到小比對
    tiers = sorted(
        cov_cfg.get("tiers", []), key=lambda t: t["min_distinct_sources"], reverse=True
    )
    for tier in tiers:
        if distinct >= tier["min_distinct_sources"]:
            return float(tier["factor"]), distinct
    return float(cov_cfg.get("default_factor", 1.0)), distinct


def _dedup_penalty_factor(evidence: Evidence, config: dict, dedup_result: "DedupResult | None") -> tuple[float, float | None]:
    """dedup_penalty 因子：小樣本固定 1（R12-3d），否則依 dedup_rate 分段。"""
    pen_cfg = config.get("dedup_penalty", {})
    if evidence.source_type.value not in pen_cfg.get("applies_to", []):
        return 1.0, None
    if dedup_result is None:
        return 1.0, None
    stats = dedup_result.stats_for(evidence)
    if stats is None:
        return 1.0, None
    if stats.small_sample:
        return 1.0, stats.dedup_rate
    for tier in pen_cfg.get("tiers", []):
        if stats.dedup_rate <= tier["max_dedup_rate"]:
            return float(tier["factor"]), stats.dedup_rate
    return float(pen_cfg.get("default_factor", 1.0)), stats.dedup_rate


def compute_four_factor_weight(
    evidence: Evidence,
    config: dict,
    dedup_result: "DedupResult | None" = None,
    pr_term: str | None = None,
    now: datetime | None = None,
) -> WeightBreakdown:
    """計算單筆證據的四因子權重與可對帳的 reason 字串。"""
    now = now or datetime.now(timezone.utc)
    levels: dict[str, float] = config["levels"]

    freshness, age_hours = _freshness_factor(evidence.fetched_at, config, now)
    level_name, rationale = _match_level(evidence, config)
    coverage, distinct = _coverage_factor(evidence, config, dedup_result)
    dedup_factor, dedup_rate = _dedup_penalty_factor(evidence, config, dedup_result)

    breakdown = WeightBreakdown(
        evidence_id=evidence.id,
        formula="four_factor",
        freshness=freshness,
        coverage_factor=coverage,
        dedup_factor=dedup_factor,
    )

    # R12-4：拉盤話術命中 → 來源等級降一級（在等級層處理，非乘係數）
    if pr_term is not None:
        demoted = _demote_level(level_name, config)
        breakdown.pr_term = pr_term
        breakdown.level_name_before_demotion = level_name
        breakdown.weight_before_demotion = max(
            WEIGHT_FLOOR,
            round(freshness * levels[level_name] * coverage * dedup_factor, 4),
        )
        level_name = demoted

    level_factor = levels[level_name]
    breakdown.level_name = level_name
    breakdown.level_factor = level_factor
    breakdown.level_rationale = rationale
    breakdown.final_weight = max(
        WEIGHT_FLOOR, round(freshness * level_factor * coverage * dedup_factor, 4)
    )
    return breakdown


def _build_reason(breakdown: WeightBreakdown) -> str:
    parts = [
        f"四因子 w={breakdown.final_weight:.2f}",
        f"新鮮度{breakdown.freshness:.2f}",
        f"×來源等級{breakdown.level_factor:.2f}"
        f"({breakdown.level_name}:{breakdown.level_rationale})",
        f"×覆蓋度{breakdown.coverage_factor:.2f}",
        f"×dedup{breakdown.dedup_factor:.2f}",
    ]
    reason = parts[0] + "｜" + "".join(parts[1:])
    if breakdown.pr_term is not None:
        reason += (
            f"｜命中拉盤話術「{breakdown.pr_term}」→來源等級 "
            f"{breakdown.level_name_before_demotion}→{breakdown.level_name}"
        )
    return reason


# --- 主入口 ---


def apply_source_weights(
    evidences: list[Evidence],
    logger: ExecutionLogger,
    dedup_result: "DedupResult | None" = None,
    pr_demotions: dict[str, str] | None = None,
) -> dict[str, WeightBreakdown]:
    """對所有證據統一補權重並寫 L1 彙總 log，回傳各筆的四因子分解。

    信譽表載入失敗或任何計算錯誤 → 整批退回舊制規則表（R12-5），
    不中斷流程；回傳的 breakdown 標 formula=legacy_fallback。
    """
    pr_demotions = pr_demotions or {}
    config = load_reputation_config()
    breakdowns: dict[str, WeightBreakdown] = {}
    formula = "four_factor"

    if config is None:
        formula = "legacy_fallback"
        logger.log(
            phase=LogPhase.COLLECT,
            action="l1_reputation_fallback",
            detail="static/source_reputation.json 載入失敗，退回舊制靜態規則表（R12-5）",
            status=LogStatus.ERROR,
            layer=PipelineLayer.SOURCE,
        )
        _apply_legacy_weights(evidences, breakdowns)
    else:
        try:
            now = datetime.now(timezone.utc)
            for ev in evidences:
                if dedup_result is not None and ev.id in dedup_result.duplicate_of:
                    canon = dedup_result.duplicate_of[ev.id]
                    ev.source_weight = DUPLICATE_WEIGHT
                    ev.weight_reason = (
                        f"Phase 2 去重剔除（與 {canon} 重複），權重壓至下限 "
                        f"{DUPLICATE_WEIGHT}"
                    )
                    breakdowns[ev.id] = WeightBreakdown(
                        evidence_id=ev.id,
                        formula="duplicate",
                        final_weight=DUPLICATE_WEIGHT,
                    )
                    continue
                breakdown = compute_four_factor_weight(
                    ev,
                    config,
                    dedup_result=dedup_result,
                    pr_term=pr_demotions.get(ev.id),
                    now=now,
                )
                ev.source_weight = breakdown.final_weight
                ev.weight_reason = _build_reason(breakdown)
                breakdowns[ev.id] = breakdown
        except Exception as exc:
            formula = "legacy_fallback"
            logger.log(
                phase=LogPhase.COLLECT,
                action="l1_four_factor_failed",
                detail=f"四因子計算失敗，退回舊制規則表（R12-5）: {exc}",
                status=LogStatus.ERROR,
                layer=PipelineLayer.SOURCE,
            )
            breakdowns.clear()
            _apply_legacy_weights(evidences, breakdowns)

    weight_distribution: dict[str, int] = {}
    for e in evidences:
        bucket = f"{e.source_weight:.2f}"
        weight_distribution[bucket] = weight_distribution.get(bucket, 0) + 1
    avg_weight = (
        sum(e.source_weight for e in evidences) / len(evidences) if evidences else 0.0
    )

    logger.log(
        phase=LogPhase.COLLECT,
        action="l1_source_weights",
        detail=f"total={len(evidences)}, avg_weight={avg_weight:.3f}, formula={formula}",
        status=LogStatus.OK,
        layer=PipelineLayer.SOURCE,
        metrics={
            "total": len(evidences),
            "avg_weight": round(avg_weight, 4),
            "distribution": weight_distribution,
            "formula": formula,
        },
    )
    return breakdowns


def _apply_legacy_weights(
    evidences: list[Evidence], breakdowns: dict[str, WeightBreakdown]
) -> None:
    for ev in evidences:
        weight, reason = assign_source_weight(ev)
        ev.source_weight = weight
        ev.weight_reason = reason
        breakdowns[ev.id] = WeightBreakdown(
            evidence_id=ev.id, formula="legacy_fallback", final_weight=weight
        )


def reputation_appendix_lines() -> list[str]:
    """產生報告附錄用的信譽表摘要（R12-3a：分級理由印進報告附錄）。"""
    config = load_reputation_config()
    if config is None:
        return [
            "- （信譽表載入失敗，本次執行使用舊制靜態規則表：官方基準 0.95／"
            "鏈上 0.85／行情聚合 0.80／總經 0.65／新聞 0.60／社群 0.30）"
        ]
    lines = [
        "權重公式：`w = 新鮮度 × 來源等級 × 覆蓋度 × dedup_penalty`"
        "（來源等級查賽前信譽表；拉盤話術命中降一級；覆蓋度＝去重後獨立來源數；"
        "dedup_penalty 依重複率分段，去重前 <5 則不觸發）",
        "",
    ]
    levels: dict[str, float] = config["levels"]
    for rule in config["rules"]:
        target = "／".join(rule["keywords"]) if rule.get("keywords") else rule.get("source_type", "?")
        lines.append(
            f"- {rule['level']}（{levels[rule['level']]:.2f}）{target}：{rule.get('rationale', '')}"
        )
    default = config.get("default", {})
    if default:
        lines.append(
            f"- {default.get('level', '?')}"
            f"（{levels.get(default.get('level', ''), 0):.2f}）其他未匹配來源：{default.get('rationale', '')}"
        )
    return lines


# --- 舊制靜態權重規則表（R12-5 fallback 路徑，保留原樣） ---

_SOURCE_KEYWORD_RULES: list[tuple[list[str], float, str]] = [
    (
        ["HOYA BIT 共同基準", "本地技術指標"],
        0.95,
        "官方基準資料／決定性本地運算",
    ),
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
    SourceType.MACRO: (0.65, "公開指數/央行匯率"),
    SourceType.NEWS: (0.60, "主流媒體，未逐篇查證"),
    SourceType.SOCIAL: (0.30, "未經查證社群內容"),
}

_DEFAULT_WEIGHT = 0.50
_DEFAULT_REASON = "未匹配任何靜態規則，使用預設權重"


def assign_source_weight(evidence: Evidence) -> tuple[float, str]:
    """舊制靜態權重表（fallback 用），回傳 (weight, reason)。

    比對順序：
    1. source 含 "HOYA BIT 共同基準" 或 "本地技術指標" → 0.95
    2. source_type == onchain → 0.85
    3. source 含 "CoinGecko" 或 "CryptoCompare" → 0.80
    4. source_type == macro → 0.65
    5. source_type == news → 0.60
    6. source_type == social → 0.30
    """
    source_lower = evidence.source.lower()

    for keyword in _SOURCE_KEYWORD_RULES[0][0]:
        if keyword.lower() in source_lower:
            return _SOURCE_KEYWORD_RULES[0][1], _SOURCE_KEYWORD_RULES[0][2]

    if evidence.source_type == SourceType.ONCHAIN:
        return _SOURCE_TYPE_FALLBACK[SourceType.ONCHAIN]

    for keyword in _SOURCE_KEYWORD_RULES_AFTER_ONCHAIN[0][0]:
        if keyword.lower() in source_lower:
            return (
                _SOURCE_KEYWORD_RULES_AFTER_ONCHAIN[0][1],
                _SOURCE_KEYWORD_RULES_AFTER_ONCHAIN[0][2],
            )

    if evidence.source_type in _SOURCE_TYPE_FALLBACK:
        return _SOURCE_TYPE_FALLBACK[evidence.source_type]

    return _DEFAULT_WEIGHT, _DEFAULT_REASON

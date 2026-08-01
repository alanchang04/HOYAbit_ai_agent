"""從 Evidence 產生可稽核的結構化 feature。

這一層只接受顯式欄位或具有固定標籤的數值，不做語意猜測、不呼叫 LLM。解析失敗
時寧可少一個 feature，也不把敘事詞彙硬轉成數值或方向。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from agent.research.models import FeatureQuality, StructuredFeature


_NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"


def _get(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value or ""))


def _number(raw: str) -> float | int:
    value = float(raw.replace(",", ""))
    return int(value) if value.is_integer() else value


def _window_of(evidence: Any) -> str | None:
    start = _get(evidence, "window_start")
    end = _get(evidence, "window_end")
    if start and end:
        return f"{start}~{end}"
    if end:
        return f"~{end}"
    horizon = _enum_value(_get(evidence, "horizon_class"))
    return horizon or None


def _as_of(evidence: Any) -> str | None:
    return _get(evidence, "window_end") or _get(evidence, "fetched_at")


def _feature(
    evidence: Any,
    name: str,
    value: float | int | str | bool,
    *,
    unit: str = "",
    method: str,
    mode: str = "deterministic_parser",
    sample_size: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> StructuredFeature:
    evidence_id = str(_get(evidence, "id", ""))
    return StructuredFeature(
        id=f"feature:{evidence_id}:{name}",
        evidence_id=evidence_id,
        coin=str(_get(evidence, "coin", "")),
        name=name,
        value=value,
        unit=unit,
        window=_window_of(evidence),
        as_of=_as_of(evidence),
        method=method,
        extraction_mode=mode,
        quality=FeatureQuality(sample_size=sample_size),
        metadata=metadata or {},
    )


def _explicit_features(evidence: Any) -> list[StructuredFeature]:
    raw = _get(evidence, "structured_features")
    if raw is None:
        extra = _get(evidence, "model_extra") or {}
        raw = extra.get("structured_features") if isinstance(extra, dict) else None
    if isinstance(raw, dict):
        raw = raw.get("features", [raw])
    if not isinstance(raw, list):
        return []

    features: list[StructuredFeature] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("feature_name") or item.get("factor")
        value = item.get("value", item.get("current_value"))
        if not isinstance(name, str) or not name.strip() or value is None:
            continue
        quality_raw = item.get("quality") if isinstance(item.get("quality"), dict) else {}
        feature = _feature(
            evidence,
            name.strip(),
            value,
            unit=str(item.get("unit", "")),
            method=str(item.get("method") or item.get("calculation_method") or "producer_provided"),
            mode="explicit",
            sample_size=item.get("sample_size") or quality_raw.get("sample_size"),
            metadata={k: v for k, v in item.items() if k not in {
                "name", "feature_name", "factor", "value", "current_value", "unit",
                "method", "calculation_method", "sample_size", "quality",
            }},
        )
        if quality_raw.get("missing_ratio") is not None:
            feature.quality.missing_ratio = float(quality_raw["missing_ratio"])
        features.append(feature)
    return features


def _labelled_number_features(evidence: Any, content: str) -> list[StructuredFeature]:
    specs = [
        ("sma_7", rf"SMA7=({_NUMBER})", "USD", "simple_moving_average_7d"),
        ("sma_14", rf"SMA14=({_NUMBER})", "USD", "simple_moving_average_14d"),
        ("ma_20", rf"MA20=({_NUMBER})", "USD", "moving_average_20d"),
        ("ma_60", rf"MA60=({_NUMBER})", "USD", "moving_average_60d"),
        ("ma_120", rf"MA120=({_NUMBER})", "USD", "moving_average_120d"),
        ("rsi_14", rf"RSI14=({_NUMBER})", "index", "wilder_rsi_14d"),
        ("volatility_14d_pct", rf"近14日日報酬波動率=({_NUMBER})%", "%", "std_daily_return_14d"),
        ("volume_change_7d_pct", rf"近7日量能較前7日變化=({_NUMBER})%", "%", "volume_sum_7d_vs_previous_7d"),
        ("volatility_percentile_alltime", rf"全歷史(?:\d+)筆樣本百分位=({_NUMBER})", "percentile", "percentile_rank_full_history"),
        ("volatility_percentile_90d", rf"90天滾動百分位=({_NUMBER})", "percentile", "rolling_percentile_90d"),
        ("spot_price_usd", rf"現價\s*({_NUMBER})\s*USD", "USD", "source_reported_spot_price"),
        ("price_change_24h_pct", rf"24h\s*漲跌\s*({_NUMBER})%", "%", "source_reported_24h_change"),
        ("volume_24h_usd", rf"24h\s*成交量\s*({_NUMBER})\s*USD", "USD", "source_reported_24h_volume"),
        ("mark_price", rf"markPrice\s*({_NUMBER})", "USD", "binance_mark_price"),
        ("index_price", rf"indexPrice\s*({_NUMBER})", "USD", "binance_index_price"),
        ("basis_pct", rf"基差\s*({_NUMBER})%", "%", "mark_minus_index_over_index"),
        ("funding_rate_pct", rf"最新資金費率\s*({_NUMBER})%", "%", "source_reported_funding_rate"),
        ("funding_rate_percentile", rf"百分位\s*({_NUMBER})", "percentile", "percentile_rank_observed_window"),
        ("open_interest", rf"最新\s*OI\s*({_NUMBER})", "contracts", "binance_open_interest"),
        ("gas_price_gwei", rf"Gas Price\s*({_NUMBER})\s*Gwei", "Gwei", "evm_eth_gasPrice"),
        ("block_height", rf"最新區塊\s*({_NUMBER})", "block", "evm_eth_blockNumber"),
        ("fear_greed_index", rf"(?:^|[,，；\s])value=({_NUMBER})", "index", "alternative_me_fng"),
    ]
    features: list[StructuredFeature] = []
    sample_match = re.search(rf"近\s*(\d+)\s*筆", content)
    sample_size = int(sample_match.group(1)) if sample_match else None
    for name, pattern, unit, method in specs:
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if match:
            features.append(
                _feature(
                    evidence,
                    name,
                    _number(match.group(1)),
                    unit=unit,
                    method=method,
                    sample_size=sample_size if "funding" in name else None,
                )
            )
    return features


def _onchain_key_values(evidence: Any, content: str) -> list[StructuredFeature]:
    if _enum_value(_get(evidence, "source_type")) != "onchain":
        return []
    allowed = {
        "blocks": ("block_count", "block"),
        "mempool_tx_count": ("mempool_tx_count", "transaction"),
        "24h_tx_count": ("transaction_count_24h", "transaction"),
        "hashrate_24h": ("hashrate_24h", "H/s"),
    }
    features: list[StructuredFeature] = []
    for raw_name, (name, unit) in allowed.items():
        match = re.search(rf"(?:^|[,，；\s]){re.escape(raw_name)}=({_NUMBER})", content)
        if match:
            features.append(
                _feature(evidence, name, _number(match.group(1)), unit=unit, method="source_key_value")
            )
    return features


def _qualitative_metadata(features: list[StructuredFeature], content: str) -> None:
    oi_direction = re.search(rf"最新\s*OI\s*{_NUMBER}（([^）]+)）", content)
    price_direction = re.search(rf"價格\s*{_NUMBER}（([^）]+)）", content)
    aligned = re.search(r"對齊\s*(\d+)\s*個共同時間桶", content)
    for feature in features:
        if feature.name == "open_interest" and oi_direction:
            feature.metadata["direction"] = oi_direction.group(1)
            if aligned:
                feature.quality.sample_size = int(aligned.group(1))
        if feature.name in {"spot_price_usd", "index_price"} and price_direction:
            feature.metadata["direction"] = price_direction.group(1)


def extract_structured_features(evidences: Iterable[Any]) -> list[StructuredFeature]:
    """回傳穩定排序、可回溯 Evidence ID 的 feature 清單。"""

    output: list[StructuredFeature] = []
    for evidence in evidences:
        evidence_id = str(_get(evidence, "id", ""))
        if not evidence_id:
            continue
        explicit = _explicit_features(evidence)
        if explicit:
            candidates = explicit
        else:
            content = str(_get(evidence, "content_reference", "") or "")
            candidates = _labelled_number_features(evidence, content)
            candidates.extend(_onchain_key_values(evidence, content))
            _qualitative_metadata(candidates, content)

        seen: set[str] = set()
        for feature in candidates:
            if feature.name in seen:
                continue
            seen.add(feature.name)
            output.append(feature)

    return sorted(output, key=lambda item: (item.evidence_id, item.name))

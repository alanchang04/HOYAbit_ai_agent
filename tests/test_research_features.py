from __future__ import annotations

from types import SimpleNamespace

from agent.research.feature_extraction import extract_structured_features
from agent.research.knowledge import knowledge_for_features, load_knowledge_catalog
from agent.schemas import Evidence


def _evidence(content: str, *, eid: str = "ev-001", source_type: str = "price") -> Evidence:
    return Evidence(
        id=eid,
        coin="BTC",
        source="test",
        fetched_at="2026-08-01T00:00:00Z",
        content_reference=content,
        related_claim="BTC 測試主題",
        source_type=source_type,
        window_start="2026-07-18",
        window_end="2026-08-01",
    )


def _by_name(features):
    return {feature.name: feature for feature in features}


def test_extracts_current_technical_indicators_without_llm() -> None:
    evidence = _evidence(
        "SMA7=118000.25, SMA14=116500.10（現價站上 SMA7）, RSI14=63.2（中性區間）, "
        "近14日日報酬波動率=2.35%, 近7日量能較前7日變化=-12.40%, MA20=115000.00（站上）"
    )
    features = _by_name(extract_structured_features([evidence]))

    assert features["rsi_14"].value == 63.2
    assert features["volatility_14d_pct"].value == 2.35
    assert features["volume_change_7d_pct"].value == -12.4
    assert features["rsi_14"].evidence_id == "ev-001"
    assert features["rsi_14"].window == "2026-07-18~2026-08-01"
    assert all(item.extraction_mode == "deterministic_parser" for item in features.values())


def test_extracts_funding_rate_and_preserves_sample_size() -> None:
    evidence = _evidence(
        "query: symbol=BTCUSDT&limit=90 | 最新資金費率 +0.00316%，近 90 筆（約 30 天）"
        "百分位 15.6（偏低）。正費率本身是常態",
        source_type="derivatives",
    )
    features = _by_name(extract_structured_features([evidence]))

    assert features["funding_rate_pct"].value == 0.00316
    assert features["funding_rate_percentile"].value == 15.6
    assert features["funding_rate_percentile"].quality.sample_size == 90


def test_extracts_onchain_key_values_from_declared_fields_only() -> None:
    evidence = _evidence(
        "blocks=900000, mempool_tx_count=12345, 24h_tx_count=500000, hashrate_24h=750000000",
        source_type="onchain",
    )
    features = _by_name(extract_structured_features([evidence]))

    assert features["block_count"].value == 900000
    assert features["mempool_tx_count"].value == 12345
    assert features["transaction_count_24h"].value == 500000
    assert features["hashrate_24h"].value == 750000000


def test_explicit_features_take_priority_over_text_fallback() -> None:
    evidence = SimpleNamespace(
        id="ev-009",
        coin="ETH",
        fetched_at="2026-08-01T00:00:00Z",
        window_start=None,
        window_end="2026-08-01",
        horizon_class="spot",
        content_reference="RSI14=99.9",
        structured_features=[
            {
                "name": "rsi_14",
                "value": 51.5,
                "unit": "index",
                "calculation_method": "producer_test_method",
                "quality": {"sample_size": 14, "missing_ratio": 0},
            }
        ],
    )
    features = extract_structured_features([evidence])

    assert len(features) == 1
    assert features[0].value == 51.5
    assert features[0].extraction_mode == "explicit"
    assert features[0].quality.sample_size == 14


def test_narrative_without_labelled_value_is_not_guessed() -> None:
    evidence = _evidence("市場看起來可能偏熱，RSI 似乎不低，但來源沒有給明確數值。")
    assert extract_structured_features([evidence]) == []


def test_knowledge_catalog_is_neutral_and_only_matches_known_features() -> None:
    evidence = _evidence("RSI14=63.2，最新資金費率 +0.00316%", source_type="derivatives")
    features = extract_structured_features([evidence])
    cards = knowledge_for_features(features)
    names = {card.feature_name for card in cards}

    assert {"rsi_14", "funding_rate_pct"} <= names
    serialized = " ".join(card.model_dump_json() for card in cards).lower()
    assert all(word not in serialized for word in ("bullish", "bearish", "看多", "看空"))
    assert load_knowledge_catalog()


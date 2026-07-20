"""Tests for agent/filters/source_weights.py — L1 靜態權重查表規則。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.filters.source_weights import apply_source_weights, assign_source_weight
from agent.logging_utils import ExecutionLogger
from agent.schemas import Evidence, PipelineLayer, SourceType


def _make_evidence(
    source: str = "TestSource",
    source_type: SourceType = SourceType.PRICE,
    ev_id: str = "ev-001",
) -> Evidence:
    """建立測試用 Evidence 物件。"""
    return Evidence(
        id=ev_id,
        coin="BTC",
        source=source,
        source_url=None,
        fetched_at="2025-01-01T00:00:00Z",
        content_reference="test content",
        related_claim="test claim",
        source_type=source_type,
    )


# --- 各規則的單元測試 ---


class TestAssignSourceWeight:
    """測試靜態權重表每條規則。"""

    def test_rule1_hoya_bit_keyword(self):
        """source 含 'HOYA BIT 共同基準' → 0.95"""
        ev = _make_evidence(source="HOYA BIT 共同基準 BTC 日線", source_type=SourceType.PRICE)
        weight, reason = assign_source_weight(ev)
        assert weight == 0.95
        assert "官方基準資料" in reason

    def test_rule1_local_indicator_keyword(self):
        """source 含 '本地技術指標' → 0.95"""
        ev = _make_evidence(source="本地技術指標 RSI/MACD", source_type=SourceType.PRICE)
        weight, reason = assign_source_weight(ev)
        assert weight == 0.95
        assert "本地運算" in reason

    def test_rule2_onchain_source_type(self):
        """source_type == onchain → 0.85"""
        ev = _make_evidence(source="Etherscan API", source_type=SourceType.ONCHAIN)
        weight, reason = assign_source_weight(ev)
        assert weight == 0.85
        assert "鏈上" in reason

    def test_rule3_coingecko_keyword(self):
        """source 含 'CoinGecko' → 0.80"""
        ev = _make_evidence(source="CoinGecko API v3", source_type=SourceType.PRICE)
        weight, reason = assign_source_weight(ev)
        assert weight == 0.80
        assert "交易所聚合" in reason

    def test_rule3_cryptocompare_keyword(self):
        """source 含 'CryptoCompare' → 0.80"""
        ev = _make_evidence(source="CryptoCompare OHLCV", source_type=SourceType.PRICE)
        weight, reason = assign_source_weight(ev)
        assert weight == 0.80
        assert "交易所聚合" in reason

    def test_rule4_macro_source_type(self):
        """source_type == macro → 0.65"""
        ev = _make_evidence(source="FRED API", source_type=SourceType.MACRO)
        weight, reason = assign_source_weight(ev)
        assert weight == 0.65
        assert "公開指數" in reason

    def test_rule5_news_source_type(self):
        """source_type == news → 0.60"""
        ev = _make_evidence(source="CryptoPanic RSS", source_type=SourceType.NEWS)
        weight, reason = assign_source_weight(ev)
        assert weight == 0.60
        assert "主流媒體" in reason

    def test_rule6_social_source_type(self):
        """source_type == social → 0.30"""
        ev = _make_evidence(source="Reddit r/CryptoCurrency", source_type=SourceType.SOCIAL)
        weight, reason = assign_source_weight(ev)
        assert weight == 0.30
        assert "社群" in reason


class TestFirstMatchWins:
    """測試優先權：規則依序比對，第一個命中即回傳。"""

    def test_hoya_bit_on_onchain_still_gets_095(self):
        """即使 source_type=onchain，但 source 含 'HOYA BIT 共同基準' 應優先命中 Rule 1 → 0.95"""
        ev = _make_evidence(source="HOYA BIT 共同基準", source_type=SourceType.ONCHAIN)
        weight, _ = assign_source_weight(ev)
        assert weight == 0.95

    def test_coingecko_on_news_gets_080(self):
        """source 含 'CoinGecko' 但 source_type=news → 應命中 Rule 3 (0.80) 而非 Rule 5 (0.60)"""
        ev = _make_evidence(source="CoinGecko Market Data", source_type=SourceType.NEWS)
        weight, _ = assign_source_weight(ev)
        assert weight == 0.80

    def test_onchain_beats_coingecko_keyword(self):
        """source_type=onchain 且 source 含 'CoinGecko' → 應命中 Rule 2 (0.85) 而非 Rule 3 (0.80)"""
        ev = _make_evidence(source="CoinGecko Onchain Data", source_type=SourceType.ONCHAIN)
        weight, _ = assign_source_weight(ev)
        assert weight == 0.85


class TestApplySourceWeights:
    """測試 apply_source_weights 批次補權重與 L1 log。"""

    def test_all_evidences_get_weight_assigned(self, tmp_path: Path):
        """所有證據都應被賦予 source_weight 和 weight_reason。"""
        logger = ExecutionLogger(tmp_path / "test.jsonl")
        evidences = [
            _make_evidence(source="HOYA BIT 共同基準", source_type=SourceType.PRICE, ev_id="ev-001"),
            _make_evidence(source="Etherscan", source_type=SourceType.ONCHAIN, ev_id="ev-002"),
            _make_evidence(source="Reddit", source_type=SourceType.SOCIAL, ev_id="ev-003"),
        ]

        apply_source_weights(evidences, logger)

        assert evidences[0].source_weight == 0.95
        assert evidences[1].source_weight == 0.85
        assert evidences[2].source_weight == 0.30

        # 所有都有 weight_reason
        for e in evidences:
            assert e.weight_reason != ""

    def test_l1_log_entry_written(self, tmp_path: Path):
        """apply_source_weights 應寫入一筆 L1 彙總 log。"""
        logger = ExecutionLogger(tmp_path / "test.jsonl")
        evidences = [
            _make_evidence(source="CoinGecko API", source_type=SourceType.PRICE, ev_id="ev-001"),
            _make_evidence(source="Reddit", source_type=SourceType.SOCIAL, ev_id="ev-002"),
        ]

        apply_source_weights(evidences, logger)

        entries = logger.read_all()
        l1_entries = [e for e in entries if e.layer == PipelineLayer.SOURCE]
        assert len(l1_entries) == 1

        entry = l1_entries[0]
        assert entry.action == "l1_source_weights"
        assert entry.layer == PipelineLayer.SOURCE
        assert "total" in entry.detail
        assert entry.metrics["total"] == 2
        assert "avg_weight" in entry.metrics
        assert "distribution" in entry.metrics

    def test_empty_evidences(self, tmp_path: Path):
        """空證據清單不應報錯。"""
        logger = ExecutionLogger(tmp_path / "test.jsonl")
        apply_source_weights([], logger)

        entries = logger.read_all()
        l1_entries = [e for e in entries if e.layer == PipelineLayer.SOURCE]
        assert len(l1_entries) == 1
        assert l1_entries[0].metrics["total"] == 0
        assert l1_entries[0].metrics["avg_weight"] == 0.0

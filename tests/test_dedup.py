"""Tests for agent/filters/dedup.py — Phase 2 去重（R12-1／R12-3d）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.filters.dedup import (
    DEDUP_SIMILARITY_THRESHOLD,
    DedupGroupStats,
    DedupResult,
    apply_dedup,
    jaccard_similarity,
)
from agent.logging_utils import ExecutionLogger
from agent.schemas import Evidence, FilterVerdict, PipelineLayer, SourceType


def _ev(
    ev_id: str,
    content: str,
    source_type: SourceType = SourceType.NEWS,
    coin: str = "BTC",
    source: str = "CoinDesk RSS",
) -> Evidence:
    return Evidence(
        id=ev_id,
        coin=coin,
        source=source,
        source_url=None,
        fetched_at="2025-01-01T00:00:00Z",
        content_reference=content,
        related_claim="test claim",
        source_type=source_type,
    )


class TestApplyDedup:
    def test_exact_duplicate_removed(self, tmp_path: Path):
        """完全相同內容 → 後到者被剔除，duplicate_of 指向先到者。"""
        logger = ExecutionLogger(tmp_path / "log.jsonl")
        evs = [
            _ev("ev-001", "Bitcoin surges past 70000 on institutional demand"),
            _ev("ev-002", "Bitcoin surges past 70000 on institutional demand",
                source="Cointelegraph RSS"),
        ]
        result = apply_dedup(evs, logger)

        assert result.duplicate_of == {"ev-002": "ev-001"}
        assert evs[1].duplicate_of == "ev-001"
        assert evs[0].duplicate_of is None

        assert len(result.decisions) == 1
        d = result.decisions[0]
        assert d.evidence_id == "ev-002"
        assert d.check_code == "DEDUP"
        assert d.verdict == FilterVerdict.REMOVED
        assert "ev-001" in d.reason

    def test_group_stats_math(self, tmp_path: Path):
        """raw_count／deduped_count／dedup_rate 計算正確且回寫到每筆證據。"""
        logger = ExecutionLogger(tmp_path / "log.jsonl")
        evs = [
            _ev("ev-001", "alpha beta gamma delta"),
            _ev("ev-002", "alpha beta gamma delta", source="B"),
            _ev("ev-003", "totally different independent report here", source="C"),
        ]
        result = apply_dedup(evs, logger)

        assert len(result.stats) == 1
        s = result.stats[0]
        assert (s.raw_count, s.deduped_count) == (3, 2)
        assert s.dedup_rate == pytest.approx(1 - 2 / 3, abs=1e-4)
        assert s.distinct_sources == 2  # CoinDesk RSS + C（B 被去重）
        assert s.small_sample is True  # 3 < 5

        # R12-1：統計隨證據保存
        for ev in evs:
            assert ev.dedup_raw_count == 3
            assert ev.dedup_deduped_count == 2
            assert ev.dedup_rate == pytest.approx(1 - 2 / 3, abs=1e-4)

    def test_below_threshold_not_removed(self, tmp_path: Path):
        logger = ExecutionLogger(tmp_path / "log.jsonl")
        evs = [
            _ev("ev-001", "alpha beta gamma"),
            _ev("ev-002", "alpha beta gamma delta epsilon"),  # Jaccard 0.6
        ]
        result = apply_dedup(evs, logger)
        assert result.decisions == []
        assert result.stats[0].deduped_count == 2

    def test_boundary_exactly_08_removed(self, tmp_path: Path):
        """Jaccard 恰為 0.8（≥ 門檻）→ 剔除。"""
        logger = ExecutionLogger(tmp_path / "log.jsonl")
        evs = [
            _ev("ev-001", "alpha beta gamma delta"),
            _ev("ev-002", "alpha beta gamma delta epsilon"),  # 4/5 = 0.8
        ]
        result = apply_dedup(evs, logger)
        assert list(result.duplicate_of) == ["ev-002"]

    def test_different_coins_not_compared(self, tmp_path: Path):
        logger = ExecutionLogger(tmp_path / "log.jsonl")
        evs = [
            _ev("ev-001", "same headline content here", coin="BTC"),
            _ev("ev-002", "same headline content here", coin="ETH"),
        ]
        result = apply_dedup(evs, logger)
        assert result.decisions == []
        assert len(result.stats) == 2  # 兩個群組各自統計

    def test_news_social_are_separate_groups(self, tmp_path: Path):
        logger = ExecutionLogger(tmp_path / "log.jsonl")
        evs = [
            _ev("ev-001", "same headline content here", source_type=SourceType.NEWS),
            _ev("ev-002", "same headline content here", source_type=SourceType.SOCIAL),
        ]
        result = apply_dedup(evs, logger)
        assert result.decisions == []

    def test_non_narrative_types_untouched(self, tmp_path: Path):
        """price/onchain/macro 不參與去重，dedup 欄位維持 None。"""
        logger = ExecutionLogger(tmp_path / "log.jsonl")
        evs = [
            _ev("ev-001", "same content", source_type=SourceType.PRICE),
            _ev("ev-002", "same content", source_type=SourceType.ONCHAIN),
            _ev("ev-003", "same content", source_type=SourceType.MACRO),
        ]
        result = apply_dedup(evs, logger)
        assert result.decisions == []
        assert result.stats == []
        for ev in evs:
            assert ev.dedup_raw_count is None
            assert ev.duplicate_of is None

    def test_min_sample_override(self, tmp_path: Path):
        """min_sample 參數可覆寫（設 2 時 3 筆樣本不再視為小樣本）。"""
        logger = ExecutionLogger(tmp_path / "log.jsonl")
        evs = [
            _ev("ev-001", "alpha beta gamma delta"),
            _ev("ev-002", "alpha beta gamma delta", source="B"),
            _ev("ev-003", "independent different report", source="C"),
        ]
        result = apply_dedup(evs, logger, min_sample=2)
        assert result.stats[0].small_sample is False

    def test_logs_written(self, tmp_path: Path):
        logger = ExecutionLogger(tmp_path / "log.jsonl")
        evs = [
            _ev("ev-001", "same headline content here"),
            _ev("ev-002", "same headline content here", source="B"),
        ]
        apply_dedup(evs, logger)

        entries = logger.read_all()
        actions = [e.action for e in entries]
        assert "l2_dedup" in actions
        assert "l2_dedup_summary" in actions
        summary = next(e for e in entries if e.action == "l2_dedup_summary")
        assert summary.layer == PipelineLayer.CONTENT
        assert summary.metrics["removed_total"] == 1
        assert summary.metrics["groups"][0]["raw_count"] == 2

    def test_empty_evidences(self, tmp_path: Path):
        logger = ExecutionLogger(tmp_path / "log.jsonl")
        result = apply_dedup([], logger)
        assert result.stats == []
        assert result.decisions == []
        summary = [e for e in logger.read_all() if e.action == "l2_dedup_summary"]
        assert len(summary) == 1


class TestDedupResultHelpers:
    def test_stats_for_matches_coin_and_type(self):
        stats = DedupGroupStats(
            coin="BTC", source_type="news", raw_count=3, deduped_count=2,
            dedup_rate=0.3333, distinct_sources=2, small_sample=True,
        )
        result = DedupResult(stats=[stats])
        assert result.stats_for(_ev("ev-001", "x")) is stats
        assert result.stats_for(_ev("ev-002", "x", coin="ETH")) is None
        assert result.stats_for(_ev("ev-003", "x", source_type=SourceType.SOCIAL)) is None


class TestJaccard:
    def test_identical(self):
        assert jaccard_similarity("hello world", "Hello World") == 1.0

    def test_disjoint(self):
        assert jaccard_similarity("alpha beta", "gamma delta") == 0.0

    def test_empty(self):
        assert jaccard_similarity("", "hello") == 0.0

    def test_threshold_constant(self):
        assert DEDUP_SIMILARITY_THRESHOLD == 0.8

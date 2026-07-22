"""Tests for agent/filters/source_weights.py — L1 四因子信任評分（R12-3）＋舊制 fallback。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import agent.filters.source_weights as sw
from agent.filters.dedup import DedupGroupStats, DedupResult
from agent.filters.source_weights import (
    apply_source_weights,
    assign_source_weight,
    compute_four_factor_weight,
    reputation_appendix_lines,
    _demote_level,
)
from agent.filters.trust_config import load_reputation_config
from agent.logging_utils import ExecutionLogger
from agent.reasoning.confidence import compute_confidence_score
from agent.schemas import Evidence, PipelineLayer, SourceType


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_evidence(
    source: str = "TestSource",
    source_type: SourceType = SourceType.PRICE,
    ev_id: str = "ev-001",
    fetched_at: str | None = None,
    coin: str = "BTC",
) -> Evidence:
    return Evidence(
        id=ev_id,
        coin=coin,
        source=source,
        source_url=None,
        fetched_at=fetched_at or _now_iso(),
        content_reference="test content",
        related_claim="test claim",
        source_type=source_type,
    )


def _dedup_result(
    distinct_sources: int = 3,
    dedup_rate: float = 0.0,
    small_sample: bool = False,
    coin: str = "BTC",
    source_type: str = "news",
) -> DedupResult:
    return DedupResult(
        stats=[
            DedupGroupStats(
                coin=coin,
                source_type=source_type,
                raw_count=10,
                deduped_count=int(10 * (1 - dedup_rate)),
                dedup_rate=dedup_rate,
                distinct_sources=distinct_sources,
                small_sample=small_sample,
            )
        ]
    )


CONFIG = load_reputation_config()


class TestLevelMapping:
    """新鮮證據＋無 dedup 資訊時，四因子退化為單純等級值（與舊制數字對齊）。"""

    @pytest.mark.parametrize(
        "source,source_type,expected",
        [
            ("HOYA BIT 共同基準 BTC 日線", SourceType.PRICE, 0.95),
            ("本地技術指標 RSI/MACD", SourceType.PRICE, 0.95),
            ("本地雙幣相對指標計算", SourceType.PRICE, 0.95),
            ("Etherscan API", SourceType.ONCHAIN, 0.85),
            ("CoinGecko API v3", SourceType.PRICE, 0.80),
            ("CryptoCompare OHLCV", SourceType.PRICE, 0.80),
            ("FRED API", SourceType.MACRO, 0.65),
            ("CoinDesk RSS", SourceType.NEWS, 0.60),
            ("Reddit r/CryptoCurrency", SourceType.SOCIAL, 0.30),
        ],
    )
    def test_fresh_no_dedup_equals_level(self, source, source_type, expected):
        ev = _make_evidence(source=source, source_type=source_type)
        b = compute_four_factor_weight(ev, CONFIG)
        assert b.final_weight == pytest.approx(expected)
        assert b.freshness == 1.0
        assert b.coverage_factor == 1.0
        assert b.dedup_factor == 1.0

    def test_first_match_wins_keyword_over_type(self):
        ev = _make_evidence(source="HOYA BIT 共同基準", source_type=SourceType.ONCHAIN)
        b = compute_four_factor_weight(ev, CONFIG)
        assert b.level_name == "A+"

    def test_unmatched_gets_default_level(self):
        ev = _make_evidence(source="UnknownSource", source_type=SourceType.PRICE)
        b = compute_four_factor_weight(ev, CONFIG)
        assert b.level_name == "D"
        assert b.final_weight == pytest.approx(0.45)


class TestFreshnessFactor:
    def test_old_evidence_gets_default_factor(self):
        """超過 168 小時 → 0.7。"""
        old = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        ev = _make_evidence(
            source="CoinDesk RSS", source_type=SourceType.NEWS, fetched_at=old
        )
        b = compute_four_factor_weight(ev, CONFIG)
        assert b.freshness == pytest.approx(0.7)
        assert b.final_weight == pytest.approx(0.7 * 0.60)

    def test_mid_tier(self):
        """48 小時 → 0.9。"""
        mid = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        ev = _make_evidence(source="CoinDesk RSS", source_type=SourceType.NEWS, fetched_at=mid)
        b = compute_four_factor_weight(ev, CONFIG)
        assert b.freshness == pytest.approx(0.9)


class TestCoverageFactor:
    """覆蓋度＝去重後獨立來源數（僅敘事類適用）。"""

    @pytest.mark.parametrize("distinct,factor", [(1, 0.7), (2, 0.85), (3, 1.0), (5, 1.0)])
    def test_tiers(self, distinct, factor):
        ev = _make_evidence(source="CoinDesk RSS", source_type=SourceType.NEWS)
        b = compute_four_factor_weight(
            ev, CONFIG, dedup_result=_dedup_result(distinct_sources=distinct)
        )
        assert b.coverage_factor == pytest.approx(factor)

    def test_not_applied_to_price(self):
        ev = _make_evidence(source="CoinGecko API", source_type=SourceType.PRICE)
        b = compute_four_factor_weight(
            ev, CONFIG, dedup_result=_dedup_result(distinct_sources=1, source_type="news")
        )
        assert b.coverage_factor == 1.0


class TestDedupPenaltyFactor:
    @pytest.mark.parametrize(
        "rate,factor", [(0.1, 1.0), (0.3, 1.0), (0.4, 0.9), (0.6, 0.75), (0.8, 0.6)]
    )
    def test_tiers(self, rate, factor):
        ev = _make_evidence(source="CoinDesk RSS", source_type=SourceType.NEWS)
        b = compute_four_factor_weight(
            ev, CONFIG, dedup_result=_dedup_result(dedup_rate=rate)
        )
        assert b.dedup_factor == pytest.approx(factor)

    def test_small_sample_fixed_to_one(self):
        """R12-3d：去重前 <5 則 → dedup_penalty 固定 1，不論 dedup_rate。"""
        ev = _make_evidence(source="CoinDesk RSS", source_type=SourceType.NEWS)
        b = compute_four_factor_weight(
            ev, CONFIG, dedup_result=_dedup_result(dedup_rate=0.9, small_sample=True)
        )
        assert b.dedup_factor == 1.0

    def test_independent_from_coverage(self):
        """R12-3c：dedup_penalty 與覆蓋度獨立——兩者同時生效且各自對應設定值。"""
        ev = _make_evidence(source="CoinDesk RSS", source_type=SourceType.NEWS)
        b = compute_four_factor_weight(
            ev, CONFIG, dedup_result=_dedup_result(distinct_sources=2, dedup_rate=0.6)
        )
        assert b.coverage_factor == pytest.approx(0.85)
        assert b.dedup_factor == pytest.approx(0.75)
        assert b.final_weight == pytest.approx(
            round(1.0 * 0.60 * 0.85 * 0.75, 4)
        )


class TestPRDemotion:
    """R12-4：話術命中 → 來源等級降一級（非 ×0.5），可與 dedup 疊加。"""

    def test_news_demoted_c_to_d(self):
        ev = _make_evidence(source="CoinDesk RSS", source_type=SourceType.NEWS)
        b = compute_four_factor_weight(ev, CONFIG, pr_term="to the moon")
        assert b.level_name_before_demotion == "C"
        assert b.level_name == "D"
        assert b.weight_before_demotion == pytest.approx(0.60)
        assert b.final_weight == pytest.approx(0.45)

    def test_social_demoted_e_to_f(self):
        ev = _make_evidence(source="Reddit", source_type=SourceType.SOCIAL)
        b = compute_four_factor_weight(ev, CONFIG, pr_term="100x")
        assert (b.level_name_before_demotion, b.level_name) == ("E", "F")
        assert b.final_weight == pytest.approx(0.15)

    def test_demote_floor_stays_at_bottom(self):
        assert _demote_level("F", CONFIG) == "F"

    def test_stacks_with_dedup_penalty(self):
        """降級與 dedup_penalty 疊加（獨立維度，非重複扣分）。"""
        ev = _make_evidence(source="CoinDesk RSS", source_type=SourceType.NEWS)
        b = compute_four_factor_weight(
            ev,
            CONFIG,
            dedup_result=_dedup_result(distinct_sources=2, dedup_rate=0.8),
            pr_term="guaranteed",
        )
        # 1.0(新鮮) × 0.45(D) × 0.85(覆蓋2源) × 0.6(rate 0.8) = 0.2295
        assert b.final_weight == pytest.approx(0.2295)


class TestApplySourceWeights:
    def test_weights_and_reasons_assigned(self, tmp_path: Path):
        logger = ExecutionLogger(tmp_path / "t.jsonl")
        evs = [
            _make_evidence(source="HOYA BIT 共同基準", ev_id="ev-001"),
            _make_evidence(source="Etherscan", source_type=SourceType.ONCHAIN, ev_id="ev-002"),
            _make_evidence(source="Reddit", source_type=SourceType.SOCIAL, ev_id="ev-003"),
        ]
        breakdowns = apply_source_weights(evs, logger)

        assert evs[0].source_weight == pytest.approx(0.95)
        assert evs[1].source_weight == pytest.approx(0.85)
        assert evs[2].source_weight == pytest.approx(0.30)
        for e in evs:
            assert "四因子" in e.weight_reason
            assert breakdowns[e.id].formula == "four_factor"

    def test_duplicate_evidence_floored(self, tmp_path: Path):
        """被 Phase 2 去重剔除者 → 權重壓至下限 0.05。"""
        logger = ExecutionLogger(tmp_path / "t.jsonl")
        evs = [
            _make_evidence(source="CoinDesk RSS", source_type=SourceType.NEWS, ev_id="ev-001"),
            _make_evidence(source="Copycat", source_type=SourceType.NEWS, ev_id="ev-002"),
        ]
        dedup = _dedup_result()
        dedup.duplicate_of = {"ev-002": "ev-001"}
        breakdowns = apply_source_weights(evs, logger, dedup_result=dedup)

        assert evs[1].source_weight == pytest.approx(0.05)
        assert "去重剔除" in evs[1].weight_reason
        assert breakdowns["ev-002"].formula == "duplicate"

    def test_l1_log_has_formula_tag(self, tmp_path: Path):
        logger = ExecutionLogger(tmp_path / "t.jsonl")
        apply_source_weights([_make_evidence()], logger)
        entry = next(
            e for e in logger.read_all() if e.action == "l1_source_weights"
        )
        assert entry.layer == PipelineLayer.SOURCE
        assert entry.metrics["formula"] == "four_factor"
        assert "avg_weight" in entry.metrics
        assert "distribution" in entry.metrics

    def test_empty_evidences(self, tmp_path: Path):
        logger = ExecutionLogger(tmp_path / "t.jsonl")
        assert apply_source_weights([], logger) == {}
        entry = next(e for e in logger.read_all() if e.action == "l1_source_weights")
        assert entry.metrics["total"] == 0


class TestLegacyFallback:
    """R12-5：信譽表載入失敗 → 整批退回舊制規則表，不中斷。"""

    def test_fallback_uses_legacy_table(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(sw, "load_reputation_config", lambda *a, **k: None)
        logger = ExecutionLogger(tmp_path / "t.jsonl")
        evs = [
            _make_evidence(source="HOYA BIT 共同基準", ev_id="ev-001"),
            _make_evidence(source="CoinDesk", source_type=SourceType.NEWS, ev_id="ev-002"),
        ]
        breakdowns = apply_source_weights(evs, logger)

        assert evs[0].source_weight == 0.95
        assert evs[1].source_weight == 0.60
        assert evs[1].weight_reason == "主流媒體，未逐篇查證"
        assert all(b.formula == "legacy_fallback" for b in breakdowns.values())

        actions = [e.action for e in logger.read_all()]
        assert "l1_reputation_fallback" in actions
        summary = next(
            e for e in logger.read_all() if e.action == "l1_source_weights"
        )
        assert summary.metrics["formula"] == "legacy_fallback"

    def test_legacy_assign_source_weight_intact(self):
        """舊制查表函式行為不變（fallback 的正確性基礎）。"""
        cases = [
            ("HOYA BIT 共同基準", SourceType.PRICE, 0.95),
            ("Etherscan", SourceType.ONCHAIN, 0.85),
            ("CoinGecko API", SourceType.PRICE, 0.80),
            ("FRED", SourceType.MACRO, 0.65),
            ("CoinDesk", SourceType.NEWS, 0.60),
            ("Reddit", SourceType.SOCIAL, 0.30),
        ]
        for source, st, expected in cases:
            weight, reason = assign_source_weight(_make_evidence(source=source, source_type=st))
            assert weight == expected
            assert reason != ""


class TestCoverageVsCoverageRateNotConflated:
    """回歸測試（tasks.md 7.7）：覆蓋度（去重後獨立來源數，L1 四因子）與
    覆蓋率（collector 成功比例，L5 信心公式）不可混用——改變 dedup 統計
    只影響權重、不影響信心公式的 gap_penalty。"""

    def test_dedup_stats_affect_weight_not_confidence_inputs(self):
        ev = _make_evidence(source="CoinDesk RSS", source_type=SourceType.NEWS)

        b_many = compute_four_factor_weight(
            ev, CONFIG, dedup_result=_dedup_result(distinct_sources=3)
        )
        b_single = compute_four_factor_weight(
            ev, CONFIG, dedup_result=_dedup_result(distinct_sources=1)
        )
        # 覆蓋度變動 → 權重變動
        assert b_many.final_weight > b_single.final_weight

        # 信心公式只看 source_type 是否到齊（覆蓋率維度），與 dedup 統計無關：
        # 相同證據集合下，無論 dedup 統計如何，分數完全一致
        evidences = [
            _make_evidence(source="CoinGecko", source_type=SourceType.PRICE, ev_id="ev-001"),
            _make_evidence(source="CoinDesk RSS", source_type=SourceType.NEWS, ev_id="ev-002"),
        ]
        score_a, breakdown_a = compute_confidence_score("中", evidences, 0)
        for e in evidences:
            e.dedup_raw_count, e.dedup_rate = 10, 0.9  # 模擬極端灌水統計
        score_b, breakdown_b = compute_confidence_score("中", evidences, 0)
        assert score_a == score_b
        assert breakdown_a["gap_penalty"] == breakdown_b["gap_penalty"]


class TestReputationAppendix:
    def test_appendix_lists_levels_and_rationales(self):
        lines = reputation_appendix_lines()
        text = "\n".join(lines)
        assert "四因子" in text or "新鮮度" in text
        assert "官方基準資料" in text
        assert "未經查證社群內容" in text

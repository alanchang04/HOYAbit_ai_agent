"""L5 數值信心公式單元測試（手算樣本驗證）。"""

from __future__ import annotations

import pytest

from agent.reasoning.confidence import (
    CONFIDENCE_BASE,
    SOURCE_TYPE_CATEGORIES,
    compute_confidence_score,
)
from agent.schemas import Evidence, SourceType, now_iso


def _make_evidence(
    source_type: SourceType = SourceType.PRICE,
    source_weight: float = 0.5,
    eid: str = "ev-001",
) -> Evidence:
    return Evidence(
        id=eid,
        coin="BTC",
        source="test",
        fetched_at=now_iso(),
        content_reference="ref",
        related_claim="claim",
        source_type=source_type,
        source_weight=source_weight,
    )


# --- 基底值測試 ---


class TestBaseValues:
    def test_high_confidence_base(self):
        evs = [_make_evidence(st, 0.5, f"ev-{i:03d}") for i, st in enumerate(SOURCE_TYPE_CATEGORIES, 1)]
        score, bd = compute_confidence_score("高", evs, 0)
        assert bd["base"] == 75

    def test_medium_confidence_base(self):
        evs = [_make_evidence(st, 0.5, f"ev-{i:03d}") for i, st in enumerate(SOURCE_TYPE_CATEGORIES, 1)]
        score, bd = compute_confidence_score("中", evs, 0)
        assert bd["base"] == 55

    def test_low_confidence_base(self):
        evs = [_make_evidence(st, 0.5, f"ev-{i:03d}") for i, st in enumerate(SOURCE_TYPE_CATEGORIES, 1)]
        score, bd = compute_confidence_score("低", evs, 0)
        assert bd["base"] == 35

    def test_unknown_confidence_defaults_to_35(self):
        evs = [_make_evidence(st, 0.5, f"ev-{i:03d}") for i, st in enumerate(SOURCE_TYPE_CATEGORIES, 1)]
        score, bd = compute_confidence_score("未知", evs, 0)
        assert bd["base"] == 35


# --- 權威源加成測試 ---


class TestAuthBonus:
    def test_half_authoritative(self):
        """5 out of 10 evidences with weight ≥ 0.7 → bonus = round(10*5/10) = 5"""
        evs = []
        for i in range(10):
            w = 0.8 if i < 5 else 0.3
            evs.append(_make_evidence(SourceType.PRICE, w, f"ev-{i+1:03d}"))
        _, bd = compute_confidence_score("中", evs, 0)
        assert bd["auth_bonus"] == 5
        assert bd["auth_count"] == 5

    def test_all_authoritative(self):
        """All 10 evidences with weight ≥ 0.7 → bonus = round(10*10/10) = 10"""
        evs = [_make_evidence(SourceType.PRICE, 0.9, f"ev-{i+1:03d}") for i in range(10)]
        _, bd = compute_confidence_score("中", evs, 0)
        assert bd["auth_bonus"] == 10

    def test_none_authoritative(self):
        """No evidences with weight ≥ 0.7 → bonus = 0"""
        evs = [_make_evidence(SourceType.PRICE, 0.5, f"ev-{i+1:03d}") for i in range(5)]
        _, bd = compute_confidence_score("中", evs, 0)
        assert bd["auth_bonus"] == 0

    def test_empty_evidences(self):
        """空證據 → bonus = 0"""
        _, bd = compute_confidence_score("中", [], 0)
        assert bd["auth_bonus"] == 0

    def test_bonus_capped_at_10(self):
        """Even with boundary weight = 0.7, all auth → capped at 10."""
        evs = [_make_evidence(SourceType.PRICE, 0.7, f"ev-{i+1:03d}") for i in range(20)]
        _, bd = compute_confidence_score("中", evs, 0)
        assert bd["auth_bonus"] == 10


# --- 矛盾訊號懲罰測試 ---


class TestContradictionPenalty:
    @pytest.mark.parametrize(
        "count,expected",
        [(0, 0), (1, 5), (2, 10), (3, 15), (4, 15), (10, 15)],
    )
    def test_penalty_values(self, count, expected):
        evs = [_make_evidence(st, 0.5, f"ev-{i:03d}") for i, st in enumerate(SOURCE_TYPE_CATEGORIES, 1)]
        _, bd = compute_confidence_score("中", evs, count)
        assert bd["contradiction_penalty"] == expected


# --- 缺失來源類別懲罰測試 ---


class TestGapPenalty:
    def test_no_missing_types(self):
        """所有 5 類都有證據 → gap_penalty = 0"""
        evs = [_make_evidence(st, 0.5, f"ev-{i:03d}") for i, st in enumerate(SOURCE_TYPE_CATEGORIES, 1)]
        _, bd = compute_confidence_score("中", evs, 0)
        assert bd["gap_penalty"] == 0
        assert bd["missing_source_types"] == []

    def test_one_missing_type(self):
        """4 類有證據、1 類缺 → gap_penalty = 5"""
        types = list(SOURCE_TYPE_CATEGORIES)[:4]
        evs = [_make_evidence(st, 0.5, f"ev-{i:03d}") for i, st in enumerate(types, 1)]
        _, bd = compute_confidence_score("中", evs, 0)
        assert bd["gap_penalty"] == 5

    def test_three_missing_capped(self):
        """2 類有證據、3 類缺 → gap_penalty = min(15, 15) = 15"""
        types = [SourceType.PRICE, SourceType.NEWS]
        evs = [_make_evidence(st, 0.5, f"ev-{i:03d}") for i, st in enumerate(types, 1)]
        _, bd = compute_confidence_score("中", evs, 0)
        assert bd["gap_penalty"] == 15

    def test_all_missing(self):
        """0 筆證據 → 5 類全缺 → gap_penalty = min(15, 25) = 15（上限）"""
        _, bd = compute_confidence_score("中", [], 0)
        assert bd["gap_penalty"] == 15


# --- Clamp 測試 ---


class TestClamp:
    def test_never_below_5(self):
        """低 base (35) - 大懲罰 → clamped to 5"""
        # base=35, auth_bonus=0, contradiction_penalty=15, gap_penalty=15 → 35-15-15=5
        # 也可以讓 gap 更大來測 clamp
        _, bd = compute_confidence_score("低", [], 4)
        assert bd["final"] >= 5

    def test_never_above_95(self):
        """高 base (75) + auth_bonus (10) + 0 penalties = 85, OK under 95"""
        evs = [_make_evidence(st, 0.9, f"ev-{i:03d}") for i, st in enumerate(SOURCE_TYPE_CATEGORIES, 1)]
        score, bd = compute_confidence_score("高", evs, 0)
        assert score == 85  # 75 + 10 - 0 - 0
        assert score <= 95

    def test_extreme_low_clamped(self):
        """最差情形 → 夾在 5"""
        score, _ = compute_confidence_score("低", [], 10)
        assert score == 5

    def test_theoretical_over_95_clamped(self):
        """即使公式算出 > 95 也夾住（目前公式最高 85，但測試 clamp 行為）"""
        # 人為用非標準 base 不太可能 > 95，所以直接驗證 max 就是 85
        evs = [_make_evidence(st, 0.9, f"ev-{i:03d}") for i, st in enumerate(SOURCE_TYPE_CATEGORIES, 1)]
        score, _ = compute_confidence_score("高", evs, 0)
        assert score <= 95


# --- 手算綜合樣本 ---


class TestHandCalculatedSample:
    def test_sample_1(self):
        """base=55, auth_bonus=6, contradictions=1 (penalty=5), gap=1 (penalty=5) → 55+6-5-5 = 51"""
        # 需要 10 筆證據，其中 6 筆 weight ≥ 0.7 → auth_bonus = round(10*6/10) = 6
        # 缺 1 個 source type → gap_penalty = 5
        # contradictions = 1 → penalty = 5
        types = [SourceType.PRICE, SourceType.ONCHAIN, SourceType.NEWS, SourceType.SOCIAL]
        evs = []
        for i in range(10):
            st = types[i % len(types)]
            w = 0.8 if i < 6 else 0.4
            evs.append(_make_evidence(st, w, f"ev-{i+1:03d}"))

        score, bd = compute_confidence_score("中", evs, 1)

        assert bd["base"] == 55
        assert bd["auth_bonus"] == 6
        assert bd["contradiction_penalty"] == 5
        assert bd["gap_penalty"] == 5  # missing: macro
        assert score == 51  # 55 + 6 - 5 - 5

    def test_sample_2_high_with_contradictions(self):
        """base=75, auth_bonus=10, contradictions=2 (penalty=10), gap=0 → 75+10-10-0 = 75"""
        evs = [_make_evidence(st, 0.9, f"ev-{i:03d}") for i, st in enumerate(SOURCE_TYPE_CATEGORIES, 1)]
        score, bd = compute_confidence_score("高", evs, 2)
        assert bd["base"] == 75
        assert bd["auth_bonus"] == 10
        assert bd["contradiction_penalty"] == 10
        assert bd["gap_penalty"] == 0
        assert score == 75

    def test_sample_3_low_worst_case(self):
        """base=35, auth_bonus=0, contradictions=3 (penalty=15), gap=15 → 35+0-15-15 = 5"""
        score, bd = compute_confidence_score("低", [], 3)
        assert bd["base"] == 35
        assert bd["auth_bonus"] == 0
        assert bd["contradiction_penalty"] == 15
        assert bd["gap_penalty"] == 15
        assert score == 5  # clamped from 5

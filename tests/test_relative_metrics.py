"""數學單元測試：雙幣相對指標計算（R2-1, R2-4）。"""
from __future__ import annotations

import csv
import math
import tempfile
from pathlib import Path

import pytest

from agent.collectors.relative import (
    _beta,
    _daily_returns,
    _load_closes,
    _max_drawdown,
    _pearson_correlation,
    _relative_strength_percentile,
    compute_relative_metrics,
)


# --- Helper ---

def _create_csv(tmp_dir: Path, ticker: str, closes: list[float]) -> None:
    """在臨時目錄建立 OHLCV CSV。"""
    csv_path = tmp_dir / f"{ticker}_daily_ohlcv.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        for i, c in enumerate(closes):
            writer.writerow([f"2026-01-{i+1:02d}", c, c, c, c, 1000])


# --- Pearson correlation tests ---

def test_pearson_perfect_positive_correlation():
    """完全正相關：兩組線性遞增序列 → corr = 1.0"""
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [2.0, 4.0, 6.0, 8.0, 10.0]
    assert math.isclose(_pearson_correlation(x, y), 1.0, abs_tol=1e-10)


def test_pearson_perfect_negative_correlation():
    """完全負相關：一組遞增一組遞減 → corr = -1.0"""
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [10.0, 8.0, 6.0, 4.0, 2.0]
    assert math.isclose(_pearson_correlation(x, y), -1.0, abs_tol=1e-10)


def test_pearson_zero_correlation():
    """零相關：一組常數 → corr = 0.0"""
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [5.0, 5.0, 5.0, 5.0, 5.0]
    assert _pearson_correlation(x, y) == 0.0


def test_pearson_empty_input():
    """空輸入 → 0.0"""
    assert _pearson_correlation([], []) == 0.0


# --- Beta tests ---

def test_beta_same_returns():
    """A 報酬完全等於 B 報酬 → beta = 1.0"""
    r = [0.01, -0.02, 0.03, -0.01, 0.02]
    assert math.isclose(_beta(r, r), 1.0, abs_tol=1e-10)


def test_beta_double_returns():
    """A 報酬 = 2*B 報酬 → beta = 2.0"""
    rb = [0.01, -0.02, 0.03, -0.01, 0.02]
    ra = [x * 2 for x in rb]
    assert math.isclose(_beta(ra, rb), 2.0, abs_tol=1e-10)


def test_beta_zero_variance():
    """B 報酬為零（零變異數）→ beta = 0.0"""
    ra = [0.01, -0.02, 0.03]
    rb = [0.0, 0.0, 0.0]
    assert _beta(ra, rb) == 0.0


# --- Max drawdown tests ---

def test_max_drawdown_known_series():
    """[100, 90, 80, 90, 70] → peak=100, 最低=70 → max_dd = 0.30"""
    closes = [100.0, 90.0, 80.0, 90.0, 70.0]
    assert math.isclose(_max_drawdown(closes), 0.30, abs_tol=1e-10)


def test_max_drawdown_monotonic_increase():
    """單調遞增 → max_dd = 0.0"""
    closes = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert _max_drawdown(closes) == 0.0


def test_max_drawdown_empty():
    """空列表 → 0.0"""
    assert _max_drawdown([]) == 0.0


def test_max_drawdown_single_drop():
    """[100, 50] → max_dd = 0.50"""
    assert math.isclose(_max_drawdown([100.0, 50.0]), 0.50, abs_tol=1e-10)


# --- Relative strength percentile tests ---

def test_relative_strength_percentile_highest():
    """A/B 比值目前為最高 → 百分位 100.0"""
    closes_a = [10.0, 20.0, 30.0, 40.0, 50.0]
    closes_b = [10.0, 10.0, 10.0, 10.0, 10.0]
    pct = _relative_strength_percentile(closes_a, closes_b)
    assert pct == 100.0


def test_relative_strength_percentile_lowest():
    """A/B 比值目前為最低 → 百分位 20.0（1/5）"""
    closes_a = [50.0, 40.0, 30.0, 20.0, 10.0]
    closes_b = [10.0, 10.0, 10.0, 10.0, 10.0]
    pct = _relative_strength_percentile(closes_a, closes_b)
    # 目前值 1.0 是序列中最小的，count_below = 1（<=1.0 只有自己）
    assert pct == 20.0  # 1/5 * 100


def test_relative_strength_percentile_insufficient_data():
    """不足 2 筆 → 回傳 50.0"""
    assert _relative_strength_percentile([100.0], [50.0]) == 50.0


# --- Daily returns tests ---

def test_daily_returns_basic():
    """[100, 110, 99] → [0.1, -0.1]"""
    rets = _daily_returns([100.0, 110.0, 99.0])
    assert math.isclose(rets[0], 0.1, abs_tol=1e-10)
    assert math.isclose(rets[1], -0.1, abs_tol=1e-10)


# --- Integration tests with CSV ---

def test_compute_relative_metrics_with_csv():
    """用臨時 CSV 測試 compute_relative_metrics 回傳 EvidenceDraft。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # 產生 20 筆資料（>10 日門檻）
        closes_a = [100.0 + i * 0.5 for i in range(20)]
        closes_b = [200.0 + i * 0.3 for i in range(20)]
        _create_csv(tmp_path, "AAA", closes_a)
        _create_csv(tmp_path, "BBB", closes_b)

        result = compute_relative_metrics("AAA", "BBB", data_dir=tmp_path)

        assert result.coin == "AAA/BBB"
        assert result.source == "本地雙幣相對指標計算"
        assert result.source_type == "price"
        assert result.source_weight == 0.95
        assert "日報酬相關係數" in result.content_reference
        assert "Beta" in result.content_reference
        assert "最大回撤" in result.content_reference
        assert "相對強弱比值百分位" in result.content_reference


def test_compute_relative_metrics_real_data():
    """用真實 CSV（BTC vs ETH）驗證不會拋出例外。"""
    data_dir = Path(__file__).resolve().parent.parent / "data"
    if not (data_dir / "BTC_daily_ohlcv.csv").exists():
        pytest.skip("本地 CSV 不存在，跳過真實資料測試")
    result = compute_relative_metrics("BTC", "ETH", data_dir=data_dir)
    assert result.coin == "BTC/ETH"
    assert result.source_type == "price"
    # 相關係數應在 [-1, 1] 範圍
    assert "日報酬相關係數" in result.content_reference


def test_compute_relative_metrics_file_not_found():
    """不存在的 ticker → 拋 FileNotFoundError。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with pytest.raises(FileNotFoundError):
            compute_relative_metrics("NONEXIST", "ALSO_NONE", data_dir=tmp_path)


def test_compute_relative_metrics_insufficient_data():
    """資料不足 10 日 → 拋 ValueError。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _create_csv(tmp_path, "X", [100.0, 101.0, 102.0])
        _create_csv(tmp_path, "Y", [200.0, 201.0, 202.0])
        with pytest.raises(ValueError, match="資料不足"):
            compute_relative_metrics("X", "Y", data_dir=tmp_path)

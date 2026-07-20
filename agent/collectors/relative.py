"""雙幣相對指標計算（純 Python 標準庫 + csv 模組，零外部 API）。

比較題型時由 orchestrator 呼叫，計算兩幣種間的量化相對表現指標。
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

from agent.schemas import EvidenceDraft, now_iso

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
WINDOW = 90  # 90 日窗口


def _load_closes(ticker: str, data_dir: Path | None = None) -> list[float]:
    """從本地 CSV 讀取收盤價（按日期升序）。"""
    base = data_dir if data_dir else DATA_DIR
    csv_path = base / f"{ticker}_daily_ohlcv.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"找不到 {ticker} 的 OHLCV CSV: {csv_path}")
    closes: list[float] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            closes.append(float(row["close"]))
    return closes


def _daily_returns(closes: list[float]) -> list[float]:
    """計算日報酬率 (close[i] - close[i-1]) / close[i-1]。"""
    return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]


def _pearson_correlation(x: list[float], y: list[float]) -> float:
    """皮爾森相關係數。"""
    n = len(x)
    if n == 0:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / n
    std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x) / n)
    std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y) / n)
    if std_x == 0 or std_y == 0:
        return 0.0
    return cov / (std_x * std_y)


def _beta(returns_a: list[float], returns_b: list[float]) -> float:
    """beta = Cov(A,B) / Var(B)（母體變異數）。"""
    n = len(returns_a)
    if n == 0:
        return 0.0
    mean_a = sum(returns_a) / n
    mean_b = sum(returns_b) / n
    cov = sum((returns_a[i] - mean_a) * (returns_b[i] - mean_b) for i in range(n)) / n
    var_b = sum((returns_b[i] - mean_b) ** 2 for i in range(n)) / n
    if var_b == 0:
        return 0.0
    return cov / var_b


def _max_drawdown(closes: list[float]) -> float:
    """最大回撤（百分比，正值表示跌幅）。"""
    if not closes:
        return 0.0
    peak = closes[0]
    max_dd = 0.0
    for price in closes:
        if price > peak:
            peak = price
        dd = (peak - price) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _relative_strength_percentile(closes_a: list[float], closes_b: list[float]) -> float:
    """相對強弱比值 (A/B) 目前值在 90 日分布中的百分位。"""
    ratios = [a / b for a, b in zip(closes_a, closes_b) if b != 0]
    if len(ratios) < 2:
        return 50.0
    current = ratios[-1]
    count_below = sum(1 for r in ratios if r <= current)
    return round(100 * count_below / len(ratios), 1)


def compute_relative_metrics(
    coin: str, coin2: str, data_dir: Path | None = None
) -> EvidenceDraft:
    """計算雙幣相對指標，回傳一筆 price 類 EvidenceDraft。

    若資料不足會 raise（由呼叫端隔離處理）。
    """
    closes_a = _load_closes(coin, data_dir=data_dir)
    closes_b = _load_closes(coin2, data_dir=data_dir)

    # 取最近 90+1 天（需要 90 個報酬率需 91 個收盤價）
    closes_a = closes_a[-(WINDOW + 1):]
    closes_b = closes_b[-(WINDOW + 1):]

    min_len = min(len(closes_a), len(closes_b))
    if min_len < 10:
        raise ValueError(
            f"資料不足：{coin} 有 {len(closes_a)} 日、{coin2} 有 {len(closes_b)} 日（需至少 10 日）"
        )

    closes_a = closes_a[-min_len:]
    closes_b = closes_b[-min_len:]

    returns_a = _daily_returns(closes_a)
    returns_b = _daily_returns(closes_b)

    corr = _pearson_correlation(returns_a, returns_b)
    beta_val = _beta(returns_a, returns_b)
    mdd_a = _max_drawdown(closes_a)
    mdd_b = _max_drawdown(closes_b)
    rs_pct = _relative_strength_percentile(closes_a, closes_b)

    content = (
        f"雙幣相對指標（{coin} vs {coin2}，近 {min_len - 1} 日）：\n"
        f"• 日報酬相關係數: {corr:.4f}\n"
        f"• Beta（{coin} 對 {coin2}）: {beta_val:.4f}\n"
        f"• {coin} 最大回撤: {mdd_a * 100:.2f}%\n"
        f"• {coin2} 最大回撤: {mdd_b * 100:.2f}%\n"
        f"• 相對強弱比值百分位: {rs_pct:.1f}%（{coin} 相對 {coin2} 在期間分布中的位置）"
    )

    return EvidenceDraft(
        coin=f"{coin}/{coin2}",
        source="本地雙幣相對指標計算",
        source_url=None,
        fetched_at=now_iso(),
        content_reference=content,
        related_claim=f"{coin} 與 {coin2} 的量化相對表現",
        source_type="price",
        source_weight=0.95,
        weight_reason="決定性本地運算",
    )

"""相對強弱比值 A/B 的 90 天位置：讀兩幣 CSV → 算比值序列 → 每日在近 90 天
比值分布中的百分位排名。對照 02_資料來源設計筆記.md「CSV 再榨」清單第一項、
02改_資料網格.html 的 relative-strength spec：這是「比較題」證據，A/B 由題目
指定哪兩幣比較，不是固定配對。網格上 5 幣各自掛一顆「X/對手幣」chip，A/B 跟
B/A 雖然互為倒數，但證據句分別掛在 A、B 各自名下（題目可能問「BTC 相對
ETH」也可能問「ETH 相對 BTC」），所以算全部 5×4=20 個方向組合，不是 10 個
不分方向的組合。

跟 compute_ma.py 同一套 prototype，一樣讀
raw_data/price/{COIN}/{COIN}_daily_ohlcv.csv，是 Ken 自己驗證邏輯用的腳本，
不是正式 collector；定案後才會跟 alanchang 對、併進 agent/collectors/price.py。

用法：
    python pipeline/compute_relative_strength.py
"""

from __future__ import annotations

import csv
from itertools import permutations
from pathlib import Path

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
WINDOW = 90
RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "price"
OUTPUT_DIR = RAW_DATA_DIR / "relative_strength"


def load_closes(coin: str) -> list[dict]:
    """讀 CSV，回傳 date/close 對照（沿用 compute_ma.py 的讀法）。"""
    path = RAW_DATA_DIR / coin / f"{coin}_daily_ohlcv.csv"
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [{"date": r["date"], "close": float(r["close"])} for r in rows]


def percentile_rank(window: list[float], value: float) -> float:
    """value 在 window 裡的百分位排名：window 中 <= value 的比例。"""
    return sum(1 for v in window if v <= value) / len(window) * 100


def compute_relative_strength_series(rows_a: list[dict], rows_b: list[dict]) -> list[dict]:
    """算 A/B 比值序列，並算每天在近 WINDOW 天比值分布中的百分位排名。前面天數
    不夠湊滿 90 天窗口，percentile_90d 留空字串，不是 0，避免誤讀（跟
    compute_ma.py 的 MA120 資料不足處理方式一致）。
    """
    assert len(rows_a) == len(rows_b), "兩幣天數不一致，CSV 對不上"
    ratios: list[float] = []
    series = []
    for a, b in zip(rows_a, rows_b):
        assert a["date"] == b["date"], f"日期對不上：{a['date']} vs {b['date']}"
        ratio = a["close"] / b["close"]
        ratios.append(ratio)
        entry = {"date": a["date"], "ratio": round(ratio, 8)}
        if len(ratios) >= WINDOW:
            entry["percentile_90d"] = round(percentile_rank(ratios[-WINDOW:], ratio), 2)
        else:
            entry["percentile_90d"] = ""
        series.append(entry)
    return series


def build_relative_strength_block(coin_a: str, coin_b: str, entry: dict) -> str:
    """比較題證據句：比值 + 90 天百分位 + 偏強/偏弱解讀。"""
    ratio = entry["ratio"]
    pct = entry["percentile_90d"]
    if pct == "":
        return f"[{coin_a}/{coin_b}] 比值={ratio:.6f}，天數不足 {WINDOW} 天，尚無 90 天位置"
    lean = "偏強" if pct > 50 else "偏弱" if pct < 50 else "持平"
    return (
        f"[{coin_a}/{coin_b}] 比值={ratio:.6f}，90 天位置={pct:.1f} 百分位"
        f"（{coin_a} 相對 {coin_b} 處於 90 天內{lean}區間）"
    )


def write_series_output(coin_a: str, coin_b: str, series: list[dict]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = ["date", "ratio", "percentile_90d"]
    out_path = OUTPUT_DIR / f"{coin_a}_{coin_b}_series.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(series)
    return out_path


def main() -> None:
    closes = {coin: load_closes(coin) for coin in COINS}
    for coin_a, coin_b in permutations(COINS, 2):
        series = compute_relative_strength_series(closes[coin_a], closes[coin_b])
        print(build_relative_strength_block(coin_a, coin_b, series[-1]))

        series_path = write_series_output(coin_a, coin_b, series)
        print(f"→ 已寫入完整歷史序列（{len(series)} 天）{series_path}")
        print()


if __name__ == "__main__":
    main()

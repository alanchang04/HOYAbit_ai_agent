"""Price 方向的個人 prototype：讀 CSV → 算 MA20/60/120 → 組成兩個 evidence 區塊。

跟 agent/collectors/price.py 的正式實作分開放，這裡是 Ken 自己驗證邏輯用的
腳本，資料來源固定讀 raw_data/price/{COIN}/{COIN}_daily_ohlcv.csv（跟主辦方
data/ 裡的 CSV 內容一致，只是路徑換成 Ken 自己整理的 raw_data/ 結構）。

用法：
    python pipeline/compute_ma.py
"""

from __future__ import annotations

import csv
from pathlib import Path

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
MA_WINDOWS = [20, 60, 120]
RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "price"


def load_closes(coin: str) -> tuple[list[float], list[dict]]:
    """Step 1：讀 CSV，回傳收盤價序列與完整列（供後續兩個區塊共用）。"""
    path = RAW_DATA_DIR / coin / f"{coin}_daily_ohlcv.csv"
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    closes = [float(r["close"]) for r in rows]
    return closes, rows


def compute_ma(closes: list[float]) -> dict:
    """Step 2：算 MA20/MA60/MA120。資料不足對應天數時該項回傳 None。"""
    last_close = closes[-1]
    result = {"last_close": last_close}
    for window in MA_WINDOWS:
        if len(closes) >= window:
            ma = sum(closes[-window:]) / window
            result[f"ma{window}"] = ma
            result[f"ma{window}_position"] = "站上" if last_close >= ma else "跌破"
        else:
            result[f"ma{window}"] = None
            result[f"ma{window}_position"] = "資料不足"
    return result


def build_ohlcv_block(coin: str, rows: list[dict], n: int = 14) -> str:
    """區塊①：近兩週 OHLCV 摘要（對照 price.py 的 summarize_ohlcv）。"""
    window = rows[-n:]
    start, end = window[0], window[-1]
    start_close, end_close = float(start["close"]), float(end["close"])
    pct_change = (end_close - start_close) / start_close * 100 if start_close else 0.0
    high = max(float(r["high"]) for r in window)
    low = min(float(r["low"]) for r in window)
    volume = sum(float(r["volume"]) for r in window)
    return (
        f"[{coin}] 期間 {start['date']} ~ {end['date']}（共 {len(window)} 日）："
        f"收盤價 {start_close:.2f} → {end_close:.2f}（{pct_change:+.2f}%），"
        f"期間最高 {high:.2f}／最低 {low:.2f}，總成交量約 {volume:.2f}"
    )


def build_ma_block(coin: str, ma: dict) -> str:
    """區塊②：MA20/60/120 位置解讀。"""
    parts = [f"收盤={ma['last_close']:.2f}"]
    for window in MA_WINDOWS:
        val = ma[f"ma{window}"]
        pos = ma[f"ma{window}_position"]
        parts.append(f"MA{window}={val:.2f}（{pos}）" if val is not None else f"MA{window}=資料不足")
    return f"[{coin}] " + "，".join(parts)


def main() -> None:
    for coin in COINS:
        closes, rows = load_closes(coin)
        ma = compute_ma(closes)
        print(build_ohlcv_block(coin, rows))
        print(build_ma_block(coin, ma))
        print()


if __name__ == "__main__":
    main()

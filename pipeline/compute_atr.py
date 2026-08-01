"""ATR（Average True Range，平均真實區間）：讀 CSV → 逐日算 True Range →
近 14 天簡單平均 → 換算成價格百分比。對照 02改_資料網格.html 的 price-atr
spec：不新增來源，複用 Price 方向已下載的 CSV（含 high/low/close），純本地
計算，零外部 API。

跟 compute_ma.py / compute_volatility_compression.py 同一套 prototype，是
Ken 自己驗證邏輯用的腳本，不是正式 collector。

窗口刻意選 14 天，跟 compute_historical_volatility_percentile.py 的
vol_14d、agent/collectors/price.py 現有 volatility_pct 窗口一致（也是
Wilder 提出 ATR 時原本用的窗口）。

⚠️ 方法論標記：ATR 本身就是「用 high/low 算的 range-based 估計量」，是
流程紀錄.md 底部 vol-compression 待辦筆記提到的 Parkinson/Garman-Klass
同類方法之一，之後那邊的方法論比較可以直接拿這份的數字當其中一版對照。
另外這版用簡單移動平均，不是 Wilder 原始論文的平滑（RMA/EMA 變體）——
先用簡單版驗證邏輯，之後有空再加 Wilder 平滑版本對照，跟其他章節「先
簡單版、留方法論比較項」的做法一致。

用法：
    python pipeline/compute_atr.py
"""

from __future__ import annotations

import csv
from pathlib import Path

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
ATR_WINDOW = 14  # True Range 簡單移動平均的窗口

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "price"


def load_ohlc(coin: str) -> list[dict]:
    path = RAW_DATA_DIR / coin / f"{coin}_daily_ohlcv.csv"
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [
        {
            "date": r["date"],
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        }
        for r in rows
    ]


def compute_atr_series(rows: list[dict]) -> list[dict]:
    """逐日算 True Range，再取近 ATR_WINDOW 天簡單平均當 ATR。第一天沒有
    前一天收盤價，TR 退化成單純 high-low；前面天數不夠湊滿窗口的 ATR 欄位
    留空字串，不是 0，避免誤讀（跟 compute_ma.py 的處理方式一致）。
    """
    tr_series: list[float] = []
    for i, row in enumerate(rows):
        if i == 0:
            tr = row["high"] - row["low"]
        else:
            prev_close = rows[i - 1]["close"]
            tr = max(
                row["high"] - row["low"],
                abs(row["high"] - prev_close),
                abs(row["low"] - prev_close),
            )
        tr_series.append(tr)

    series = []
    for i, row in enumerate(rows):
        entry = {
            "date": row["date"],
            "close": row["close"],
            "tr": round(tr_series[i], 4),
        }
        if i + 1 >= ATR_WINDOW:
            window_tr = tr_series[i - ATR_WINDOW + 1 : i + 1]
            atr = sum(window_tr) / ATR_WINDOW
            entry["atr_14"] = round(atr, 4)
            entry["atr_14_pct"] = round(atr / row["close"] * 100, 4) if row["close"] else ""
        else:
            entry["atr_14"] = ""
            entry["atr_14_pct"] = ""
        series.append(entry)
    return series


def build_block(coin: str, entry: dict) -> str:
    if entry["atr_14"] == "":
        return f"[{coin}] 資料不足，還算不出 14 天 ATR"
    return (
        f"[{coin}] ATR(14)={entry['atr_14']:.2f}（{entry['atr_14_pct']:.2f}% "
        f"of close={entry['close']:.2f}）"
    )


def write_series_output(coin: str, series: list[dict]) -> Path:
    fieldnames = ["date", "close", "tr", "atr_14", "atr_14_pct"]
    out_path = RAW_DATA_DIR / coin / "atr_series.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(series)
    return out_path


def main() -> None:
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    for coin in COINS:
        rows = load_ohlc(coin)
        series = compute_atr_series(rows)
        print(build_block(coin, series[-1]))
        out_path = write_series_output(coin, series)
        print(f"→ 已寫入完整歷史序列（{len(series)} 天）{out_path}")
        print()


if __name__ == "__main__":
    main()

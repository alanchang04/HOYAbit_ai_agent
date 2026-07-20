"""波動壓縮度百分位：讀 CSV → 算近 20 天日報酬標準差 → 跟過去 90 天這個
20 天滾動標準差的歷史分佈比大小 → 換算成百分位。對照
02改_資料網格.html 的 vol-compression spec：不新增來源，複用 Price 方向
已下載的 CSV，純本地計算，零外部 API。

跟 compute_ma.py / compute_relative_strength.py 同一套 prototype，是 Ken
自己驗證邏輯用的腳本，不是正式 collector。

⚠️ 方法論標記：目前用的是「歷史滾動標準差的百分位排名」，最簡單但假設
報酬服從穩態分佈、且對極端值不敏感。之後有空可以加一版 GARCH(1,1)（或
EWMA、Parkinson/Garman-Klass 這類用 high/low 的 range-based 估計量）算出
的波動度序列，跟這版做同一天的數字對照，看哪個對「盤整/噴出」的分類
更準——這是待辦，見流程紀錄.md 底部。

用法：
    python pipeline/compute_volatility_compression.py
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
VOL_WINDOW = 20  # 算日報酬標準差的窗口
PCTL_WINDOW = 90  # 拿最近幾天的滾動標準差序列來排百分位

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "price"


def load_closes(coin: str) -> list[dict]:
    path = RAW_DATA_DIR / coin / f"{coin}_daily_ohlcv.csv"
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [{"date": r["date"], "close": float(r["close"])} for r in rows]


def percentile_rank(window: list[float], value: float) -> float:
    """value 在 window 裡的百分位排名：window 中 <= value 的比例（跟
    compute_relative_strength.py 的 percentile_rank 同一個定義，維持一致）。"""
    return sum(1 for v in window if v <= value) / len(window) * 100


def compute_volatility_series(rows: list[dict]) -> list[dict]:
    """逐日算：日報酬% → 近 VOL_WINDOW 天日報酬的母體標準差(%) → 該標準差在
    近 PCTL_WINDOW 天標準差序列中的百分位。前面天數不夠湊滿窗口的欄位留空
    字串，不是 0，避免誤讀（跟 compute_ma.py／compute_relative_strength.py
    的處理方式一致）。
    """
    closes = [r["close"] for r in rows]
    returns: list[float] = [0.0]  # index 0 無報酬，用 0.0 佔位但不會被用到（下面用 [1:] 切）
    for i in range(1, len(closes)):
        returns.append((closes[i] - closes[i - 1]) / closes[i - 1] * 100 if closes[i - 1] else 0.0)

    vol_series: list[float | None] = [None] * len(rows)
    for i in range(len(rows)):
        if i + 1 >= VOL_WINDOW:  # 從 index 1 開始才有真報酬，所以要有 VOL_WINDOW 筆真報酬
            window_returns = returns[i - VOL_WINDOW + 1 : i + 1]
            vol_series[i] = statistics.pstdev(window_returns)

    series = []
    vol_history: list[float] = []
    for i, row in enumerate(rows):
        entry = {"date": row["date"], "close": row["close"], "daily_return_pct": round(returns[i], 4)}
        vol = vol_series[i]
        if vol is not None:
            entry["vol_20d_pct"] = round(vol, 4)
            vol_history.append(vol)
            if len(vol_history) >= PCTL_WINDOW:
                entry["percentile_90d"] = round(percentile_rank(vol_history[-PCTL_WINDOW:], vol), 2)
            else:
                entry["percentile_90d"] = ""
        else:
            entry["vol_20d_pct"] = ""
            entry["percentile_90d"] = ""
        series.append(entry)
    return series


def build_block(coin: str, entry: dict) -> str:
    if entry["percentile_90d"] == "":
        return f"[{coin}] 資料不足，還算不出 90 天百分位"
    pct = entry["percentile_90d"]
    lean = "偏悶（盤整彈藥）" if pct < 50 else "偏熱（相對高波動期）"
    return f"[{coin}] 近{VOL_WINDOW}天日報酬波動率={entry['vol_20d_pct']:.2f}%，90天百分位={pct:.1f}（{lean}）"


def write_series_output(coin: str, series: list[dict]) -> Path:
    fieldnames = ["date", "close", "daily_return_pct", "vol_20d_pct", "percentile_90d"]
    out_path = RAW_DATA_DIR / coin / "volatility_compression_series.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(series)
    return out_path


def main() -> None:
    for coin in COINS:
        rows = load_closes(coin)
        series = compute_volatility_series(rows)
        print(build_block(coin, series[-1]))
        out_path = write_series_output(coin, series)
        print(f"→ 已寫入完整歷史序列（{len(series)} 天）{out_path}")
        print()


if __name__ == "__main__":
    main()

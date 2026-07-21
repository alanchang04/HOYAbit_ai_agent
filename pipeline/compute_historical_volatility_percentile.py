"""歷史波動率百分位：讀 CSV → 算近 14 天日報酬標準差（跟 price.py 現有的
`volatility_pct` 同一個窗口）→ 這個數字相對「過去至今全部歷史」排百分位。

對照 `pipeline/待辦筆記/price_波動率百分位.md`：現況
`compute_technical_indicators()` 的 `volatility_pct` 只回傳原始標準差
數字，不是百分位——讀報告的人不知道這個數字算高還算低，02改_資料網格.html
的 `tech-indicators` read 欄本來就寫「波動率數字要跟該幣自己的歷史比才有
意義」，但程式碼還沒真的做這件事。

視窗策略：用擴張視窗（expanding window），不是固定 90 天滾動視窗。第 i 天
的百分位 = 第 i 天的 vol_14d 跟「從第一天有 vol_14d 值到第 i 天」這整段
歷史比大小，不是只比近 90 天。這樣寫最新一天（序列最後一列）的百分位天然
就等於「相對過去 5 年全部歷史的位置」，符合待辦筆記要的效果；同時每一天
的百分位都只用得到「當天以前」的資料，不會拿未來資料去排名過去某一天
（look-ahead bias）。

跟 `compute_volatility_compression.py` 同一套 prototype 邏輯
（`percentile_rank()` 定義完全一致），差別只在視窗策略：那支是固定 90 天
滾動視窗（回答「近期是否相對近期悶」），這支是擴張全歷史視窗（回答「現在
相對整個資料集歷史上是否悶」），兩者回答不同問題，不是重複實作，兩份可以
並存給不同題型用。

用法：
    python pipeline/compute_historical_volatility_percentile.py
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
VOL_WINDOW = 14  # 跟 agent/collectors/price.py 的 volatility_pct 同一個窗口，方便併回時邏輯對得上
MIN_SAMPLE = 90  # 累積不到 90 筆 vol_14d 前不給百分位，樣本太少會失真（跟其他 prototype 的門檻一致）

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "price"


def load_closes(coin: str) -> list[dict]:
    path = RAW_DATA_DIR / coin / f"{coin}_daily_ohlcv.csv"
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [{"date": r["date"], "close": float(r["close"])} for r in rows]


def percentile_rank(window: list[float], value: float) -> float:
    """value 在 window 裡的百分位排名：window 中 <= value 的比例（跟
    compute_relative_strength.py／compute_volatility_compression.py 的
    percentile_rank 同一個定義，維持一致）。"""
    return sum(1 for v in window if v <= value) / len(window) * 100


def compute_series(rows: list[dict]) -> list[dict]:
    """逐日算：日報酬% → 近 VOL_WINDOW 天日報酬的母體標準差(%) → 該標準差
    在「當天以前累積的全部歷史」中的百分位。前面天數不夠湊滿窗口，或累積
    樣本數不到 MIN_SAMPLE 的欄位留空字串，不是 0，避免誤讀（跟
    compute_ma.py／compute_volatility_compression.py 的處理方式一致）。
    """
    closes = [r["close"] for r in rows]
    returns: list[float] = [0.0]  # index 0 無報酬，用 0.0 佔位但不會被用到（下面用切片跳過）
    for i in range(1, len(closes)):
        returns.append((closes[i] - closes[i - 1]) / closes[i - 1] * 100 if closes[i - 1] else 0.0)

    series = []
    vol_history: list[float] = []  # 擴張視窗：只累加、不砍尾，跟固定滾動視窗不同
    for i, row in enumerate(rows):
        entry = {"date": row["date"], "close": row["close"], "daily_return_pct": round(returns[i], 4)}
        if i + 1 >= VOL_WINDOW:
            window_returns = returns[i - VOL_WINDOW + 1 : i + 1]
            vol = statistics.pstdev(window_returns)
            entry["vol_14d_pct"] = round(vol, 4)
            vol_history.append(vol)
            if len(vol_history) >= MIN_SAMPLE:
                entry["percentile_alltime"] = round(percentile_rank(vol_history, vol), 2)
            else:
                entry["percentile_alltime"] = ""
        else:
            entry["vol_14d_pct"] = ""
            entry["percentile_alltime"] = ""
        series.append(entry)
    return series


def build_block(coin: str, entry: dict, sample_size: int) -> str:
    if entry["percentile_alltime"] == "":
        return f"[{coin}] 資料不足，還算不出全歷史百分位"
    pct = entry["percentile_alltime"]
    lean = "偏悶（相對全歷史低波動）" if pct < 50 else "偏熱（相對全歷史高波動）"
    return (
        f"[{coin}] 近{VOL_WINDOW}天日報酬波動率={entry['vol_14d_pct']:.2f}%，"
        f"全歷史（{sample_size}筆樣本）百分位={pct:.1f}（{lean}）"
    )


def write_series_output(coin: str, series: list[dict]) -> Path:
    fieldnames = ["date", "close", "daily_return_pct", "vol_14d_pct", "percentile_alltime"]
    out_path = RAW_DATA_DIR / coin / "volatility_percentile_series.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(series)
    return out_path


def main() -> None:
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    for coin in COINS:
        rows = load_closes(coin)
        series = compute_series(rows)
        sample_size = sum(1 for e in series if e["vol_14d_pct"] != "")
        print(build_block(coin, series[-1], sample_size))
        out_path = write_series_output(coin, series)
        print(f"→ 已寫入完整歷史序列（{len(series)} 天）{out_path}")
        print()


if __name__ == "__main__":
    main()

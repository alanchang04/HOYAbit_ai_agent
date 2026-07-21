"""OI × 價格四象限（對照 02改_資料網格.html 的 `oi-price-quadrant` spec）。跟
正式 `agent/collectors/` 還沒有對應模組，這裡先是 Ken 自己驗證用的 prototype。

Binance USDⓈ-M 合約公開端點，免 key：
- 當前 OI：GET /fapi/v1/openInterest?symbol={PERP}
- 近 30 小時 OI 序列：GET /futures/data/openInterestHist?symbol={PERP}&period=1h&limit=30
- 同期價格：openInterestHist 本身沒有價格欄位，02 筆記只寫「跟同期價格序列對齊
  時間戳後比對方向」沒指名端點，這裡補抓 GET /fapi/v1/klines?symbol={PERP}&
  interval=1h&limit=30 的收盤價，用「取整到小時」的 bucket 對齊兩個端點的
  時間戳（openInterestHist 跟 klines 是不同端點，不保證每筆剛好對齊到同一毫秒）

讀法（02 筆記原話）：OI↑價↑＝新多頭進場（順勢）；OI↑價↓＝新空頭進場（順勢）；
OI↓價↓＝多頭停損離場（可能止跌）；OI↓價↑＝空頭回補（可能追高風險）。四象限
各自對應不同市場結構解讀，不能只看 OI 單一方向。

5 幣種都是 Binance 自家永續合約，跟訂單簿深度那組不一樣，BNB 不用另外找補位。

用法：
    python pipeline/fetch_oi_price_quadrant.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
PERP_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT", "XRP": "XRPUSDT"}
PERIOD = "1h"
LIMIT = 30
HOUR_MS = 3_600_000

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "derivatives"
FAPI_BASE = "https://fapi.binance.com/fapi/v1"
FUTURES_DATA_BASE = "https://fapi.binance.com/futures/data"
HTTP_TIMEOUT = 20.0

QUADRANT_LABEL = {
    ("up", "up"): "多頭增倉（順勢，新多頭進場）",
    ("up", "down"): "空頭增倉（順勢，新空頭進場）",
    ("down", "down"): "多頭停損離場（可能止跌）",
    ("down", "up"): "空頭回補（可能追高風險）",
    ("flat", "up"): "價漲 OI 持平（方向不明）",
    ("flat", "down"): "價跌 OI 持平（方向不明）",
    ("up", "flat"): "OI 增加價格持平（方向不明）",
    ("down", "flat"): "OI 減少價格持平（方向不明）",
    ("flat", "flat"): "OI 價格皆持平（無明顯訊號）",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hour_bucket(ts_ms: int) -> int:
    return ts_ms // HOUR_MS


def move_direction(latest: float, prev: float) -> str:
    if latest > prev:
        return "up"
    if latest < prev:
        return "down"
    return "flat"


def fetch_current_oi(client: httpx.Client, symbol: str) -> dict:
    resp = client.get(f"{FAPI_BASE}/openInterest", params={"symbol": symbol})
    resp.raise_for_status()
    data = resp.json()
    return {"openInterest": float(data["openInterest"]), "time": int(data["time"])}


def fetch_oi_hist(client: httpx.Client, symbol: str) -> list[dict]:
    resp = client.get(
        f"{FUTURES_DATA_BASE}/openInterestHist",
        params={"symbol": symbol, "period": PERIOD, "limit": LIMIT},
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise RuntimeError("openInterestHist 回傳空序列")
    return rows


def fetch_klines(client: httpx.Client, symbol: str) -> list[dict]:
    resp = client.get(
        f"{FAPI_BASE}/klines",
        params={"symbol": symbol, "interval": PERIOD, "limit": LIMIT},
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise RuntimeError("klines 回傳空序列")
    # kline: [openTime, open, high, low, close, volume, closeTime, ...]
    return [{"openTime": int(r[0]), "close": float(r[4])} for r in rows]


def fetch_coin(client: httpx.Client, coin: str) -> dict:
    symbol = PERP_SYMBOL[coin]
    current = fetch_current_oi(client, symbol)
    oi_rows = fetch_oi_hist(client, symbol)
    kline_rows = fetch_klines(client, symbol)

    oi_by_bucket = {hour_bucket(int(r["timestamp"])): float(r["sumOpenInterest"]) for r in oi_rows}
    price_by_bucket = {hour_bucket(r["openTime"]): r["close"] for r in kline_rows}
    shared_buckets = sorted(set(oi_by_bucket) & set(price_by_bucket))
    unmatched_oi = len(oi_by_bucket) - len(shared_buckets)
    unmatched_price = len(price_by_bucket) - len(shared_buckets)

    trend = []
    for i, bucket in enumerate(shared_buckets):
        oi_val = oi_by_bucket[bucket]
        price_val = price_by_bucket[bucket]
        if i == 0:
            trend.append({
                "hour_bucket": bucket,
                "oi": oi_val,
                "price": price_val,
                "oi_direction": None,
                "price_direction": None,
                "quadrant": None,
            })
            continue
        prev_oi = oi_by_bucket[shared_buckets[i - 1]]
        prev_price = price_by_bucket[shared_buckets[i - 1]]
        oi_dir = move_direction(oi_val, prev_oi)
        price_dir = move_direction(price_val, prev_price)
        trend.append({
            "hour_bucket": bucket,
            "oi": oi_val,
            "price": price_val,
            "oi_direction": oi_dir,
            "price_direction": price_dir,
            "quadrant": QUADRANT_LABEL[(oi_dir, price_dir)],
        })

    latest = trend[-1]
    if latest["quadrant"] is None:
        raise RuntimeError("對齊後樣本數不足以判斷方向（少於 2 個共同時間桶）")

    return {
        "perp": symbol,
        "source": "Binance Futures /fapi/v1/openInterest + /futures/data/openInterestHist + /fapi/v1/klines",
        "oi_current": current["openInterest"],
        "oi_current_time": current["time"],
        "aligned_hours": len(shared_buckets),
        "unmatched_oi_points": unmatched_oi,
        "unmatched_price_points": unmatched_price,
        "latest_oi": latest["oi"],
        "latest_price": latest["price"],
        "oi_direction": latest["oi_direction"],
        "price_direction": latest["price_direction"],
        "quadrant": latest["quadrant"],
        f"trend_last_{LIMIT}h": trend,
        "fetched_at": now_iso(),
    }


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "oi_price_quadrant_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"coin": coin, **result}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        for coin in COINS:
            try:
                result = fetch_coin(client, coin)
            except Exception as exc:  # noqa: BLE001
                print(f"[{coin}] 抓取失敗：{exc}")
                continue
            out_path = write_output(coin, result)
            print(f"[{coin}] 已寫入 {out_path}")
            print(
                f"  OI {result['oi_direction']} / 價格 {result['price_direction']} "
                f"→ {result['quadrant']}"
            )
            print(
                f"  對齊 {result['aligned_hours']} 小時（未對齊：OI {result['unmatched_oi_points']} 筆 / "
                f"價格 {result['unmatched_price_points']} 筆）"
            )
            print()


if __name__ == "__main__":
    main()

"""多空帳戶比 vs 大戶持倉比背離（對照 02改_資料網格.html 的 `long-short-ratio`
spec）。跟正式 `agent/collectors/` 還沒有對應模組，這裡先是 Ken 自己驗證用的
prototype。

Binance Futures 公開端點，免 key：
- 散戶（全市場帳戶數比）：GET /futures/data/globalLongShortAccountRatio
- 大戶（top trader 持倉量比，smart money 代理指標）：
  GET /futures/data/topLongShortPositionRatio
兩者都回傳 `longShortRatio` 序列，period=1h、limit=30（近 30 小時）。

讀法（02 筆記原話）：散戶與大戶比值同向＝訊號一致性高；背離（例如散戶瘋狂
做多、大戶持倉卻偏空）是經典的「反指標」強訊號，市場上常認為大戶（smart
money）方向更可信。這裡只做「同向/背離」二元分類＋兩邊各自的最新值與跟上
一小時比的變化，不做更複雜的訊號強度評分。

5 幣種都是 Binance 自家永續合約（perp symbol 見 02 網格的 COINS 定義），跟
訂單簿深度那組不一樣，BNB 不用另外找補位來源。

用法：
    python pipeline/fetch_long_short_ratio.py
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

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "derivatives"
BASE_URL = "https://fapi.binance.com/futures/data"
HTTP_TIMEOUT = 20.0


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def direction(ratio: float) -> str:
    return "偏多" if ratio > 1 else "偏空"


def fetch_series(client: httpx.Client, endpoint: str, symbol: str) -> list[dict]:
    resp = client.get(
        f"{BASE_URL}/{endpoint}",
        params={"symbol": symbol, "period": PERIOD, "limit": LIMIT},
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise RuntimeError(f"{endpoint} 回傳空序列")
    return rows


def fetch_coin(client: httpx.Client, coin: str) -> dict:
    symbol = PERP_SYMBOL[coin]
    retail_rows = fetch_series(client, "globalLongShortAccountRatio", symbol)
    smart_rows = fetch_series(client, "topLongShortPositionRatio", symbol)

    retail_by_ts = {row["timestamp"]: float(row["longShortRatio"]) for row in retail_rows}
    smart_by_ts = {row["timestamp"]: float(row["longShortRatio"]) for row in smart_rows}
    shared_ts = sorted(set(retail_by_ts) & set(smart_by_ts))
    trend = [
        {"timestamp": ts, "retail_ratio": retail_by_ts[ts], "smart_money_ratio": smart_by_ts[ts]}
        for ts in shared_ts
    ]

    retail_latest = trend[-1]["retail_ratio"]
    smart_latest = trend[-1]["smart_money_ratio"]
    retail_prev = trend[-2]["retail_ratio"] if len(trend) >= 2 else None
    smart_prev = trend[-2]["smart_money_ratio"] if len(trend) >= 2 else None

    return {
        "perp": symbol,
        "source": "Binance Futures /futures/data/globalLongShortAccountRatio + topLongShortPositionRatio",
        "retail_ratio_latest": retail_latest,
        "retail_ratio_change": None if retail_prev is None else retail_latest - retail_prev,
        "retail_direction": direction(retail_latest),
        "smart_money_ratio_latest": smart_latest,
        "smart_money_ratio_change": None if smart_prev is None else smart_latest - smart_prev,
        "smart_money_direction": direction(smart_latest),
        "diverged": direction(retail_latest) != direction(smart_latest),
        f"trend_last_{LIMIT}h": trend,
        "fetched_at": now_iso(),
    }


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "long_short_ratio_snapshot.json"
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
                f"  散戶 {result['retail_ratio_latest']:.4f}（{result['retail_direction']}） vs "
                f"大戶 {result['smart_money_ratio_latest']:.4f}（{result['smart_money_direction']}）"
                f"{' → 背離' if result['diverged'] else ' → 同向'}"
            )
            print()


if __name__ == "__main__":
    main()

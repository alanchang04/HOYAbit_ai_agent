"""訂單簿深度與價差（微結構流動性，對照 02改_資料網格.html 的
`orderbook-depth-spread` / `hyperliquid-l2book` spec）。這是 02 筆記排在
「優先序：微結構流動性 → CSV 再榨 → 費率擁擠度 → 其餘」第一位的新方向，還沒有
對應的正式 collector，這裡先是 Ken 自己驗證用的 prototype。

BTC/ETH/SOL/XRP：Kraken `/0/public/Depth` 為主，失敗退 Coinbase Exchange
`/products/{pair}/book?level=2`，皆免 key、不擋美國 IP。BNB 兩家都不上架，改用
Hyperliquid 公開 `l2Book`（鏈上 DEX 深度，不是 CEX，讀的時候要註明樣本偏差）。

算法（兩個資料源共用同一套）：
- top-of-book 價差 = (best_ask - best_bid) / mid_price，換算成 bps
- ±1% 深度 = bid 方向price >= best_bid*0.99 的量、ask 方向 price <=
  best_ask*1.01 的量，各自加總（price*qty，USD 計）

Kraken pair 命名跟 02 筆記警告的不一樣：BTC 是 XBTUSD 不是 BTCUSD，其餘
ETH/SOL/XRP 這次已實測確認 `{TICKER}USD` 可直接用（不用再猜）。Kraken `count`
參數要拉到 500 才夠涵蓋 ±1%（count=50 只夠 ~0.06-0.08%，覆蓋不到 1%，是這次
實測才發現的坑）；Coinbase level=2 本來就回傳全深度聚合簿，不用另外設定。

跟即時報價／onchain 快照一樣，這幾個欄位本質是「當下一個時間點」的快照，沒有
歷史序列版本，每次跑都會覆蓋掉上一次的結果。

用法：
    python pipeline/fetch_orderbook_depth.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
KRAKEN_PAIR = {"BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "XRP": "XRPUSD"}
KRAKEN_COUNT = 500
DEPTH_PCT = 0.01  # ±1%

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "microstructure"
HTTP_TIMEOUT = 20.0


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_depth_metrics(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> dict:
    best_bid = bids[0][0]
    best_ask = asks[0][0]
    mid = (best_bid + best_ask) / 2
    spread_bps = (best_ask - best_bid) / mid * 10000
    bid_floor = best_bid * (1 - DEPTH_PCT)
    ask_ceiling = best_ask * (1 + DEPTH_PCT)
    bid_depth_usd = sum(price * qty for price, qty in bids if price >= bid_floor)
    ask_depth_usd = sum(price * qty for price, qty in asks if price <= ask_ceiling)
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid_price": mid,
        "spread_bps": spread_bps,
        "bid_depth_usd_1pct": bid_depth_usd,
        "ask_depth_usd_1pct": ask_depth_usd,
        "depth_usd_1pct_total": bid_depth_usd + ask_depth_usd,
    }


def fetch_kraken(client: httpx.Client, coin: str) -> dict:
    pair = KRAKEN_PAIR[coin]
    resp = client.get(
        "https://api.kraken.com/0/public/Depth",
        params={"pair": pair, "count": KRAKEN_COUNT},
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("error"):
        raise RuntimeError(f"Kraken error: {payload['error']}")
    book = next(iter(payload["result"].values()))
    bids = [(float(p), float(q)) for p, q, *_ in book["bids"]]
    asks = [(float(p), float(q)) for p, q, *_ in book["asks"]]
    metrics = compute_depth_metrics(bids, asks)
    return {"source": f"Kraken /0/public/Depth (pair={pair})", "fetched_at": now_iso(), **metrics}


def fetch_coinbase(client: httpx.Client, coin: str) -> dict:
    product = f"{coin}-USD"
    resp = client.get(
        f"https://api.exchange.coinbase.com/products/{product}/book",
        params={"level": 2},
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()
    data = resp.json()
    bids = [(float(p), float(q)) for p, q, *_ in data["bids"]]
    asks = [(float(p), float(q)) for p, q, *_ in data["asks"]]
    metrics = compute_depth_metrics(bids, asks)
    return {
        "source": f"Coinbase Exchange /products/{product}/book?level=2（Kraken 備援）",
        "fetched_at": now_iso(),
        **metrics,
    }


def fetch_hyperliquid_bnb(client: httpx.Client) -> dict:
    resp = client.post(
        "https://api.hyperliquid.xyz/info",
        json={"type": "l2Book", "coin": "BNB"},
    )
    resp.raise_for_status()
    levels = resp.json()["levels"]
    bids = [(float(lvl["px"]), float(lvl["sz"])) for lvl in levels[0]]
    asks = [(float(lvl["px"]), float(lvl["sz"])) for lvl in levels[1]]
    metrics = compute_depth_metrics(bids, asks)
    return {
        "source": "Hyperliquid l2Book（BNB 補位，鏈上 DEX 深度，非 CEX、不代表 BNB 全市場流動性）",
        "fetched_at": now_iso(),
        **metrics,
    }


def fetch_orderbook(client: httpx.Client, coin: str) -> dict:
    if coin == "BNB":
        return fetch_hyperliquid_bnb(client)
    try:
        result = fetch_kraken(client, coin)
        print(f"[{coin}] Kraken 成功")
        return result
    except Exception as exc:  # noqa: BLE001
        print(f"[{coin}] Kraken 失敗（{exc}），退 Coinbase")
        return fetch_coinbase(client, coin)


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "orderbook_depth.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"coin": coin, **result}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        for coin in COINS:
            try:
                result = fetch_orderbook(client, coin)
            except Exception as exc:  # noqa: BLE001
                print(f"[{coin}] 抓取失敗：{exc}")
                continue
            out_path = write_output(coin, result)
            print(
                f"  價差 {result['spread_bps']:.2f} bps，±1% 深度 "
                f"{result['depth_usd_1pct_total']:,.0f} USD → 已寫入 {out_path}"
            )
            print()


if __name__ == "__main__":
    main()

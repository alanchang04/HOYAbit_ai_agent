"""Price 方向第 3 塊：即時報價（對照 02改_資料網格.html 的「即時報價」色塊）。

主來源 CoinGecko /simple/price，失敗自動退 CryptoCompare /pricemultifull，
皆免 key。跟 agent/collectors/price.py 的正式實作邏輯一致，這裡是 Ken 自己
驗證用的 prototype，抓完直接落地存進 raw_data/price/{COIN}/realtime_price.json。

用法：
    python pipeline/fetch_realtime_price.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
COINGECKO_ID = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin", "XRP": "ripple"}
CRYPTOCOMPARE_SYMBOL = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "BNB": "BNB", "XRP": "XRP"}

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "price"
HTTP_TIMEOUT = 20.0


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_coingecko(client: httpx.Client, coin: str) -> dict | None:
    cgid = COINGECKO_ID[coin]
    resp = client.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={
            "ids": cgid,
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_24hr_vol": "true",
        },
    )
    resp.raise_for_status()
    data = resp.json()[cgid]
    return {
        "source": "CoinGecko /simple/price",
        "price_usd": data.get("usd"),
        "change_24h_pct": data.get("usd_24h_change"),
        "volume_24h_usd": data.get("usd_24h_vol"),
        "fetched_at": now_iso(),
    }


def fetch_cryptocompare(client: httpx.Client, coin: str) -> dict | None:
    symbol = CRYPTOCOMPARE_SYMBOL[coin]
    resp = client.get(
        "https://min-api.cryptocompare.com/data/pricemultifull",
        params={"fsyms": symbol, "tsyms": "USD"},
    )
    resp.raise_for_status()
    raw = resp.json()["RAW"][symbol]["USD"]
    return {
        "source": "CryptoCompare /pricemultifull（CoinGecko 備援）",
        "price_usd": raw.get("PRICE"),
        "change_24h_pct": raw.get("CHANGEPCT24HOUR"),
        "volume_24h_usd": raw.get("VOLUME24HOURTO"),
        "fetched_at": now_iso(),
    }


def fetch_realtime_price(client: httpx.Client, coin: str) -> dict:
    try:
        result = fetch_coingecko(client, coin)
        print(f"[{coin}] CoinGecko 成功")
        return result
    except Exception as exc:  # noqa: BLE001
        print(f"[{coin}] CoinGecko 失敗（{exc}），退 CryptoCompare")
        return fetch_cryptocompare(client, coin)


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "realtime_price.json"
    out_path.write_text(json.dumps({"coin": coin, **result}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        for coin in COINS:
            try:
                result = fetch_realtime_price(client, coin)
            except Exception as exc:  # noqa: BLE001
                print(f"[{coin}] 兩個來源都失敗：{exc}")
                continue
            out_path = write_output(coin, result)
            print(
                f"  現價 {result['price_usd']} USD，24h 漲跌 {result['change_24h_pct']:.2f}%"
                f"，24h 量 {result['volume_24h_usd']:.0f} USD → 已寫入 {out_path}"
            )
            print()


if __name__ == "__main__":
    main()

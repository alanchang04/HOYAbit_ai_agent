"""Coinbase 溢價（Coinbase Premium）：Coinbase 現貨價 vs Binance 現貨價的價差，
常被當作美系機構/散戶買壓的代理指標（Coinbase 使用者結構偏美系機構＋散戶，
Binance 偏全球＋衍生品交易者，正溢價＝美系買盤較急）。

分類記錄（2026-07-24，Ken 拍板）：這格原本在 07/08 流程圖文件裡被寫成
`price.py` 的既有項目，但實際查證後 `price.py` 完全沒有這段程式碼，連
prototype 都沒有——純粹是文件寫超前，不是漏併。Ken 判斷這格性質上更接近
「跨場地價格/流動性比較」，跟 `cex-dex-funding-diff`（CEX vs DEX 費率差，已在
derivatives.py）、`orderbook-depth-spread`（跨場地深度比較，還沒併）是同一類，
歸進「衍生品類＋流動性」缺口，不歸 price.py。這支腳本跟
`fetch_cex_dex_funding_diff.py` 同一個寫法（跨場地取值→算價差→門檻判讀）。

用法：
    python pipeline/fetch_coinbase_premium.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
BINANCE_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT", "XRP": "XRPUSDT"}

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "derivatives"
COINBASE_URL = "https://api.exchange.coinbase.com/products/{coin}-USD/ticker"
BINANCE_URL = "https://api.binance.com/api/v3/ticker/price"
HTTP_TIMEOUT = 20.0
USER_AGENT = "hoyabit-crypto-agent/1.0"

# 門檻取值方式跟 fetch_cex_dex_funding_diff.py 的 5% 一樣，是刻意取捨的起始值不是
# 理論值：2026-07-23 五幣實測基準線落在 -0.09%~-0.12%（見下方實測結果），拉開一點
# 空間避免正常雜訊被誤判，賽前如果覺得太鬆/太緊可以再跟 Ken 討論調整。
DIVERGENCE_THRESHOLD_PCT = 0.15


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_coinbase_price(client: httpx.Client, coin: str) -> float:
    resp = client.get(COINBASE_URL.format(coin=coin), headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return float(resp.json()["price"])


def fetch_binance_price(client: httpx.Client, coin: str) -> float:
    resp = client.get(BINANCE_URL, params={"symbol": BINANCE_SYMBOL[coin]})
    resp.raise_for_status()
    return float(resp.json()["price"])


def premium_label(premium_pct: float) -> str:
    if premium_pct >= DIVERGENCE_THRESHOLD_PCT:
        return "Coinbase 溢價明顯偏高（美系買壓較急）"
    if premium_pct <= -DIVERGENCE_THRESHOLD_PCT:
        return "Coinbase 溢價明顯偏低（美系賣壓較急／或該幣非 Coinbase 主力交易場）"
    return "價差在正常雜訊範圍內，無明顯溢價訊號"


def build_result(coinbase_price: float, binance_price: float) -> dict:
    premium_pct = (coinbase_price - binance_price) / binance_price * 100 if binance_price else 0.0
    return {
        "source": "Coinbase Exchange /products/{coin}-USD/ticker vs Binance Spot /api/v3/ticker/price",
        "coinbase_price_usd": coinbase_price,
        "binance_price_usdt": binance_price,
        "premium_pct": premium_pct,
        "premium_label": premium_label(premium_pct),
        "fetched_at": now_iso(),
        "note": "USDT 視為約當 USD（跟本專案其他 Binance USDT 報價的既有假設一致，"
        "未額外校正 USDT/USD 匯率；正式版 Coinbase Premium Index 會校正這項，"
        "此處為簡化版）",
    }


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "coinbase_premium_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"coin": coin, **result}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    # Windows 主控台預設 cp950，印不出全形符號會 UnicodeEncodeError（跟
    # fetch_news.py／fetch_event_calendar.py 踩過的同一個坑，修法一致）。
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        for coin in COINS:
            try:
                coinbase_price = fetch_coinbase_price(client, coin)
            except Exception as exc:  # noqa: BLE001
                print(f"[{coin}] Coinbase 抓取失敗（可能未上架）：{exc}")
                continue
            try:
                binance_price = fetch_binance_price(client, coin)
            except Exception as exc:  # noqa: BLE001
                print(f"[{coin}] Binance 抓取失敗：{exc}")
                continue

            result = build_result(coinbase_price, binance_price)
            out_path = write_output(coin, result)
            print(
                f"[{coin}] Coinbase {coinbase_price} vs Binance {binance_price}，"
                f"溢價 {result['premium_pct']:+.4f}%（{result['premium_label']}）"
                f" → 已寫入 {out_path}"
            )


if __name__ == "__main__":
    main()

"""清算流方向（對照 02改_資料網格.html 的 `liquidation-flow-hl` spec）。

查證過程見 pipeline/流程紀錄.md：Hyperliquid 公開 info/WebSocket 沒有市場級的
清算標記欄位（`trades` 頻道沒有、`userFills` 只能訂閱單一使用者），這條路不可行。
改用 Binance USDⓈ-M 合約公開 WebSocket `!forceOrder@arr`（All Market Liquidation
Order Streams）：免 key、market-wide、官方文件仍在維護（舊版 REST
`/fapi/v1/allForceOrders` 已停用，但這個即時推送頻道沒被砍）。

⚠️ 本質限制：這是「即時推送流」，不是「查歷史」。15 分鐘單次執行的架構下，
做法是開 WebSocket 連線聽固定一段時間窗口（`LISTEN_SECONDS`），把窗口內剛好
發生的清算單收下來當樣本——不是「過去 N 小時的清算統計」。窗口內沒收到
不代表沒有清算，只代表「這段觀察窗沒觀測到」，報告措辭要照這個誠實，不能
講得像穩定監控到的訊號，拿不到就退回 OI+價格四象限做間接推論。

用法：
    python pipeline/fetch_liquidation_flow.py [--seconds 45]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import websockets

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
PERP_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT", "XRP": "XRPUSDT"}
SYMBOL_TO_COIN = {v: k for k, v in PERP_SYMBOL.items()}

WS_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "derivatives"
DEFAULT_LISTEN_SECONDS = 45


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_force_order(raw: dict) -> dict | None:
    """把 forceOrder 事件轉成我們要的欄位；不是我們追的 5 幣種就回 None。"""
    order = raw.get("o", {})
    symbol = order.get("s")
    coin = SYMBOL_TO_COIN.get(symbol)
    if coin is None:
        return None
    qty = float(order["q"])
    avg_px = float(order["ap"]) if float(order.get("ap", 0)) > 0 else float(order["p"])
    return {
        "coin": coin,
        "side": order.get("S"),  # BUY＝空頭被強平（買回平倉）／SELL＝多頭被強平（賣出平倉）
        "qty": qty,
        "avg_price": avg_px,
        "notional_usd": round(qty * avg_px, 2),
        "order_time": datetime.fromtimestamp(order["T"] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


async def listen(seconds: int) -> list[dict]:
    events: list[dict] = []
    async with websockets.connect(WS_URL) as ws:
        try:
            async with asyncio.timeout(seconds):
                async for message in ws:
                    raw = json.loads(message)
                    parsed = parse_force_order(raw)
                    if parsed is not None:
                        events.append(parsed)
                        print(
                            f"  [{parsed['coin']}] {parsed['side']} 強平 {parsed['qty']} "
                            f"@ {parsed['avg_price']}（約 {parsed['notional_usd']:,.0f} USD）"
                        )
        except TimeoutError:
            pass
    return events


def write_output(coin: str, window_start: str, window_end: str, seconds: int, coin_events: list[dict]) -> Path:
    out_path = RAW_DATA_DIR / coin / "liquidation_flow_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "coin": coin,
        "source": "Binance USDⓈ-M 合約公開 WebSocket !forceOrder@arr（免 key，market-wide）",
        "note": (
            "這是固定時間窗口內的即時監聽樣本，不是歷史統計；observed_count=0 代表"
            "這段窗口沒觀測到清算，不代表市場沒有清算發生，報告只能講「推論」不能講"
            "「觀測到」以外的窗口。"
        ),
        "window_start": window_start,
        "window_end": window_end,
        "window_seconds": seconds,
        "observed_count": len(coin_events),
        "events": coin_events,
        "fetched_at": now_iso(),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


async def main_async(seconds: int) -> None:
    window_start = now_iso()
    print(f"連線 {WS_URL}，監聽 {seconds} 秒（{window_start}）...")
    events = await listen(seconds)
    window_end = now_iso()

    by_coin: dict[str, list[dict]] = {coin: [] for coin in COINS}
    for event in events:
        by_coin[event["coin"]].append(event)

    print()
    for coin in COINS:
        coin_events = by_coin[coin]
        out_path = write_output(coin, window_start, window_end, seconds, coin_events)
        if coin_events:
            print(f"[{coin}] 觀測到 {len(coin_events)} 筆清算 → 已寫入 {out_path}")
        else:
            print(f"[{coin}] 這段窗口沒觀測到清算（不代表沒發生）→ 已寫入 {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=DEFAULT_LISTEN_SECONDS, help="監聽秒數（預設 45）")
    args = parser.parse_args()
    asyncio.run(main_async(args.seconds))


if __name__ == "__main__":
    main()

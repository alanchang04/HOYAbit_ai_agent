"""期貨到期結構曲線 contango/backwardation（對照 02改_資料網格.html 的
`futures-term-structure` spec）。跟正式 `agent/collectors/` 還沒有對應模組，這裡
先是 Ken 自己驗證用的 prototype。

02 筆記原本寫「季度合約集中在 USDⓈ-M（BTC/ETH 為主），COIN-M 覆蓋種類較多」，
只把 BTC/ETH 當主力、SOL/XRP 標「視上市」、BNB 甚至沒開這個 spec 的 chip
（假設 BNB 沒有季度合約，跟 CME COT 章節「BNB 沒有 CME 期貨」的認知混在一起）。
這次實測 `dapi.binance.com`（COIN-M）exchangeInfo 才發現：BNB/BTC/ETH/SOL/XRP
五幣在 COIN-M 上**全部都有**季度合約（CURRENT_QUARTER + NEXT_QUARTER，皆
TRADING）；USDⓈ-M（`fapi.binance.com`）則確實只有 BTC/ETH 掛季度合約，
SOL/XRP/BNB 都沒有。所以這裡改用 COIN-M 當統一資料源，五幣不用分兩套邏輯，
也不用把 BNB 排除——「BNB 沒有 CME COT」跟「BNB 沒有 Binance 季度期貨」是
兩件不同的事，不能互相取代。

算法：
- 對每幣抓 `{COIN}USD_PERP`（永續）、當季（CURRENT_QUARTER）、次季
  （NEXT_QUARTER）三個合約的 `premiumIndex`（markPrice / indexPrice）
- 永續：basis_pct = (mark - index) / index * 100（跟 `price.py` 的
  `compute_perp_basis()` 同一套算法，不年化——永續沒有固定到期日）
- 當季／次季：annualized_basis_pct = (mark - index) / index * (365 /
  天數到期) * 100，換算成可跨到期日比較的年化基差
- 曲線形狀：比較 mark_price（永續 → 當季 → 次季）是否單調遞增（contango，
  遠月價 > 近月價 > 現貨/永續）還是單調遞減（backwardation，近月反而比遠月
  貴，短期拋壓訊號）；不是單調就標「mixed」

用法：
    python pipeline/fetch_futures_term_structure.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
DAPI_BASE = "https://dapi.binance.com"
HTTP_TIMEOUT = 20.0
RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "derivatives"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_quarterly_symbols(client: httpx.Client, pair: str) -> dict[str, dict]:
    """回傳 {'CURRENT_QUARTER': {...}, 'NEXT_QUARTER': {...}}，值含 symbol/deliveryDate。"""
    resp = client.get(f"{DAPI_BASE}/dapi/v1/exchangeInfo")
    resp.raise_for_status()
    symbols = resp.json()["symbols"]
    found = {}
    for s in symbols:
        if (
            s.get("pair") == pair
            and s.get("contractType") in ("CURRENT_QUARTER", "NEXT_QUARTER")
            and s.get("contractStatus") == "TRADING"
        ):
            found[s["contractType"]] = {"symbol": s["symbol"], "delivery_date_ms": s["deliveryDate"]}
    return found


def fetch_premium_index(client: httpx.Client, symbol: str) -> dict:
    resp = client.get(f"{DAPI_BASE}/dapi/v1/premiumIndex", params={"symbol": symbol})
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise RuntimeError(f"premiumIndex 查無資料：symbol={symbol}")
    return rows[0]


def build_curve(client: httpx.Client, coin: str, quarterly: dict[str, dict]) -> dict:
    pair = f"{coin}USD"
    now_ms = datetime.now(timezone.utc).timestamp() * 1000

    perp = fetch_premium_index(client, f"{pair}_PERP")
    index_price = float(perp["indexPrice"])
    perp_mark = float(perp["markPrice"])

    points = [
        {
            "label": "perp",
            "symbol": f"{pair}_PERP",
            "days_to_expiry": None,
            "mark_price": perp_mark,
            "basis_pct": (perp_mark - index_price) / index_price * 100,
        }
    ]
    for label in ("CURRENT_QUARTER", "NEXT_QUARTER"):
        info = quarterly[label]
        data = fetch_premium_index(client, info["symbol"])
        mark = float(data["markPrice"])
        days_to_expiry = (info["delivery_date_ms"] - now_ms) / 1000 / 86400
        annualized_basis_pct = (mark - index_price) / index_price * (365 / days_to_expiry) * 100
        points.append(
            {
                "label": "current_quarter" if label == "CURRENT_QUARTER" else "next_quarter",
                "symbol": info["symbol"],
                "days_to_expiry": round(days_to_expiry, 1),
                "mark_price": mark,
                "annualized_basis_pct": annualized_basis_pct,
            }
        )

    marks = [p["mark_price"] for p in points]
    if marks[0] < marks[1] < marks[2]:
        shape = "contango"
    elif marks[0] > marks[1] > marks[2]:
        shape = "backwardation"
    else:
        shape = "mixed"

    return {
        "source": "Binance COIN-M dapi.binance.com /dapi/v1/premiumIndex（免 key）",
        "pair": pair,
        "index_price": index_price,
        "curve": points,
        "shape": shape,
        "fetched_at": now_iso(),
    }


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "futures_term_structure_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"coin": coin, **result}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        for coin in COINS:
            pair = f"{coin}USD"
            try:
                quarterly = find_quarterly_symbols(client, pair)
                if "CURRENT_QUARTER" not in quarterly or "NEXT_QUARTER" not in quarterly:
                    print(f"[{coin}] COIN-M 查無完整當季/次季合約，跳過（缺席本身是敘事）")
                    continue
                result = build_curve(client, coin, quarterly)
            except Exception as exc:  # noqa: BLE001
                print(f"[{coin}] 抓取失敗：{exc}")
                continue
            out_path = write_output(coin, result)
            perp, cur, nxt = result["curve"]
            print(f"[{coin}] 已寫入 {out_path}")
            print(f"  形狀：{result['shape']}")
            print(
                f"  perp mark={perp['mark_price']:.4f}（基差{perp['basis_pct']:+.4f}%） → "
                f"當季 mark={cur['mark_price']:.4f}（年化基差{cur['annualized_basis_pct']:+.2f}%，"
                f"{cur['days_to_expiry']:.0f}天後到期） → "
                f"次季 mark={nxt['mark_price']:.4f}（年化基差{nxt['annualized_basis_pct']:+.2f}%，"
                f"{nxt['days_to_expiry']:.0f}天後到期）"
            )
            print()


if __name__ == "__main__":
    main()

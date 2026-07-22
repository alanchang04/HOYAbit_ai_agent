"""CME COT 機構淨倉位方向（對照 02改_資料網格.html 的 `cme-cot` spec）。

跟正式 collector 還沒有對應模組（`agent/collectors/` 目前沒有 cme_cot.py），這裡
先是 Ken 自己驗證用的 prototype，賽前核對欄位無誤後再決定併進哪個正式 collector。

資料來源：CFTC 公開 Socrata Open Data API（免 key），dataset 是「Traders in
Financial Futures - Futures Only」（TFF Futures Only，resource id gpe5-46if）：
    https://publicreporting.cftc.gov/resource/gpe5-46if.json
每週五公布、數據落後到當週二，是層2 敘事的背景佐證，不是即時訊號。

用 `market_and_exchange_names` 精確比對（不是模糊 like），避免混進同幣種下的
MICRO／NANO 等其他規格合約；四個名稱已對照 API 實測結果核對過，不是憑印象猜的。

「機構淨倉位」用 Asset Manager 分類（資產管理公司/機構投資人）的
long - short 當淨倉位，Leveraged Funds（避險基金/槓桿基金）淨倉位當對照組
一起存，畢竟兩者風格不同（前者偏配置型，後者偏方向型/動能型）。

⚠️ BNB 沒有 CME 期貨，CFTC 週報查不到，直接跳過——缺席本身是層2 風險特徵
（見 02改_資料網格.html 的 BNB override：「CME 沒有 BNB 期貨」）。

用法：
    python pipeline/fetch_cme_cot.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "derivatives"
COT_API_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
HTTP_TIMEOUT = 20.0
TREND_WEEKS = 12

# 精確市場名稱（已用 API 實測核對，不是模糊比對）。BNB 沒有 CME 期貨，不在此列。
COIN_MARKET_NAMES = {
    "BTC": "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
    "ETH": "ETHER CASH SETTLED - CHICAGO MERCANTILE EXCHANGE",
    "SOL": "SOL - CHICAGO MERCANTILE EXCHANGE",
    "XRP": "XRP - CHICAGO MERCANTILE EXCHANGE",
}

SELECT_FIELDS = [
    "report_date_as_yyyy_mm_dd",
    "open_interest_all",
    "asset_mgr_positions_long",
    "asset_mgr_positions_short",
    "lev_money_positions_long",
    "lev_money_positions_short",
    "change_in_asset_mgr_long",
    "change_in_asset_mgr_short",
    "contract_units",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_coin(client: httpx.Client, market_name: str) -> dict:
    params = {
        "$where": f"market_and_exchange_names = '{market_name}'",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(TREND_WEEKS),
        "$select": ",".join(SELECT_FIELDS),
    }
    resp = client.get(COT_API_URL, params=params)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise RuntimeError(f"查無資料：market_and_exchange_names = '{market_name}'")

    # rows 是 DESC（最新在前），trend 轉成時間正序比較好讀
    trend = [
        {
            "report_date": row["report_date_as_yyyy_mm_dd"][:10],
            "open_interest_all": int(row["open_interest_all"]),
            "asset_mgr_net": int(row["asset_mgr_positions_long"]) - int(row["asset_mgr_positions_short"]),
            "lev_money_net": int(row["lev_money_positions_long"]) - int(row["lev_money_positions_short"]),
        }
        for row in reversed(rows)
    ]

    latest = rows[0]
    return {
        "source": f"CFTC TFF Futures Only（{market_name}）",
        "contract_units": latest.get("contract_units"),
        "latest_report_date": latest["report_date_as_yyyy_mm_dd"][:10],
        "asset_mgr_net_latest": trend[-1]["asset_mgr_net"],
        "asset_mgr_net_change_latest": int(latest["change_in_asset_mgr_long"]) - int(latest["change_in_asset_mgr_short"]),
        "lev_money_net_latest": trend[-1]["lev_money_net"],
        f"trend_last_{TREND_WEEKS}_weeks": trend,
        "fetched_at": now_iso(),
    }


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "cme_cot_snapshot.json"
    out_path.write_text(json.dumps({"coin": coin, **result}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        for coin, market_name in COIN_MARKET_NAMES.items():
            try:
                result = fetch_coin(client, market_name)
            except Exception as exc:  # noqa: BLE001
                print(f"[{coin}] 抓取失敗：{exc}")
                continue
            out_path = write_output(coin, result)
            print(f"[{coin}] 已寫入 {out_path}")
            print(f"  最新報告日：{result['latest_report_date']}（{result['contract_units']}）")
            print(
                f"  Asset Manager 淨倉位：{result['asset_mgr_net_latest']:+,}"
                f"（本週變化 {result['asset_mgr_net_change_latest']:+,}）"
            )
            print(f"  Leveraged Funds 淨倉位：{result['lev_money_net_latest']:+,}")
            print()
        print("[BNB] CME 沒有 BNB 期貨，CFTC 週報查不到，跳過（缺席本身是層2 風險特徵）")


if __name__ == "__main__":
    main()

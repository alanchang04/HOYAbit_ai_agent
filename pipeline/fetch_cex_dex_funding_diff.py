"""CEX vs DEX 費率差（對照 02改_資料網格.html 的 `cex-dex-funding-diff` spec）。跟
正式 `agent/collectors/` 還沒有對應模組，這裡先是 prototype，屬於「衍生品類」
缺口的一部分（跟 CME COT／訂單簿深度／多空帳戶比／期貨到期結構／費率擁擠度／
選擇權 IV／OI×價格四象限同一批，都還沒併回正式 collector）。

CEX：複用 Binance USDⓈ-M `premiumIndex` 的 `lastFundingRate`（跟 `perp-basis`／
`funding-rate-percentile` 同一個端點）。
DEX：Hyperliquid `POST https://api.hyperliquid.xyz/info`，body
`{"type":"metaAndAssetCtxs"}`，回傳 `[meta, assetCtxs]` 兩個陣列，用
`meta.universe` 逐項比對 `name` 找到該幣在陣列中的 index，取 `assetCtxs` 同
index 的 `funding` 欄位。實測 2026-07-21：五幣皆在 `universe` 中找得到
（BTC idx 0／ETH idx 1／SOL idx 5／BNB idx 7／XRP idx 25），02 筆記原本沒提到
的疑慮「HL 是否五幣都有掛牌」這次確認不成立。

⚠️ 02 筆記「how」原文寫「跟 Binance lastFundingRate 相減」，但這次實測發現兩邊
結算週期不同，直接相減會誤導：
- Binance `lastFundingRate` 是每 8 小時結算一次的當期費率
- Hyperliquid `funding` 是每小時結算一次的當期費率
同樣是「一期費率」，但一期代表的時間長度差 8 倍，不能直接比大小（8h 期的
0.01% 跟 1h 期的 0.01% 換算成年化後差 8 倍）。這裡额外算年化版本
（Binance ×3×365、Hyperliquid ×24×365）當主要比較欄位，原始未年化的兩個數字
也保留供對照，不隱藏任何一版。

用法：
    python pipeline/fetch_cex_dex_funding_diff.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
PERP_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT", "XRP": "XRPUSDT"}

CEX_FUNDING_INTERVAL_HOURS = 8
DEX_FUNDING_INTERVAL_HOURS = 1
HOURS_PER_YEAR = 24 * 365

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "derivatives"
BINANCE_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
HYPERLIQUID_URL = "https://api.hyperliquid.xyz/info"
HTTP_TIMEOUT = 20.0

# 背離門檻：年化差距超過這個絕對值才算「場地擁擠度不一致」，避免雜訊被誤讀成訊號
DIVERGENCE_THRESHOLD_PCT = 5.0


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_binance_funding(client: httpx.Client, coin: str) -> float:
    symbol = PERP_SYMBOL[coin]
    resp = client.get(BINANCE_URL, params={"symbol": symbol})
    resp.raise_for_status()
    return float(resp.json()["lastFundingRate"])


def fetch_hyperliquid_funding_map(client: httpx.Client) -> dict[str, float]:
    resp = client.post(HYPERLIQUID_URL, json={"type": "metaAndAssetCtxs"})
    resp.raise_for_status()
    meta, asset_ctxs = resp.json()
    universe = meta["universe"]
    funding_map = {}
    for coin in COINS:
        idx = next((i for i, u in enumerate(universe) if u["name"] == coin), None)
        if idx is None:
            continue
        funding_map[coin] = float(asset_ctxs[idx]["funding"])
    return funding_map


def divergence_label(annualized_diff_pct: float) -> str:
    if annualized_diff_pct >= DIVERGENCE_THRESHOLD_PCT:
        return "CEX 費率明顯較高（槓桿集中 CEX）"
    if annualized_diff_pct <= -DIVERGENCE_THRESHOLD_PCT:
        return "DEX 費率明顯較高（槓桿集中 DEX）"
    return "兩邊費率接近，無明顯場地背離"


def build_result(coin: str, cex_rate: float, dex_rate: float) -> dict:
    cex_annualized_pct = cex_rate * (HOURS_PER_YEAR / CEX_FUNDING_INTERVAL_HOURS) * 100
    dex_annualized_pct = dex_rate * (HOURS_PER_YEAR / DEX_FUNDING_INTERVAL_HOURS) * 100
    annualized_diff_pct = cex_annualized_pct - dex_annualized_pct
    return {
        "source": "Binance /fapi/v1/premiumIndex (CEX) vs Hyperliquid metaAndAssetCtxs (DEX)",
        "cex_last_funding_rate_pct": cex_rate * 100,
        "cex_funding_interval_hours": CEX_FUNDING_INTERVAL_HOURS,
        "cex_annualized_pct": cex_annualized_pct,
        "dex_last_funding_rate_pct": dex_rate * 100,
        "dex_funding_interval_hours": DEX_FUNDING_INTERVAL_HOURS,
        "dex_annualized_pct": dex_annualized_pct,
        "annualized_diff_pct": annualized_diff_pct,
        "divergence_label": divergence_label(annualized_diff_pct),
        "fetched_at": now_iso(),
    }


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "cex_dex_funding_diff_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"coin": coin, **result}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        try:
            dex_funding_map = fetch_hyperliquid_funding_map(client)
        except Exception as exc:  # noqa: BLE001
            print(f"Hyperliquid metaAndAssetCtxs 抓取失敗：{exc}")
            return

        for coin in COINS:
            if coin not in dex_funding_map:
                print(f"[{coin}] Hyperliquid universe 找不到，跳過")
                continue
            try:
                cex_rate = fetch_binance_funding(client, coin)
            except Exception as exc:  # noqa: BLE001
                print(f"[{coin}] Binance 抓取失敗：{exc}")
                continue

            result = build_result(coin, cex_rate, dex_funding_map[coin])
            out_path = write_output(coin, result)
            print(
                f"[{coin}] CEX 年化 {result['cex_annualized_pct']:+.2f}% vs "
                f"DEX 年化 {result['dex_annualized_pct']:+.2f}%，"
                f"差 {result['annualized_diff_pct']:+.2f}%（{result['divergence_label']}）"
                f" → 已寫入 {out_path}"
            )


if __name__ == "__main__":
    main()

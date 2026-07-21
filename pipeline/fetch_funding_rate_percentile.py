"""費率擁擠度：BTC/ETH/SOL/BNB/XRP funding 近 30 天百分位（對照 02改_資料網格.html
的 `funding-rate-percentile` spec）。跟正式 `agent/collectors/price.py` 還沒有
對應邏輯，這裡先是 Ken 自己驗證用的 prototype。

Binance USDⓈ-M 合約公開端點，免 key：
    GET /fapi/v1/fundingRate?symbol={PERP}&limit=90
每 8 小時一筆，limit=90 剛好覆蓋近 30 天（已實測五幣都回傳剛好 90 筆）。

百分位算法跟 `pipeline/compute_relative_strength.py` 的 `percentile_rank()`
同一套定義：window 內 `<= 最新值` 的比例。

讀法（02 筆記原話）：持續高正費率百分位（例如 >90%）＝多頭極度擁擠，下方容易
堆滿多頭清算燃料，利於空頭往下砸；注意正費率本身是常態（多頭付空頭是常態
結構），只有「極端百分位」才是訊號，不能看到正的就當成擁擠。

用法：
    python pipeline/fetch_funding_rate_percentile.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
PERP_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT", "XRP": "XRPUSDT"}
LIMIT = 90

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "derivatives"
BASE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
HTTP_TIMEOUT = 20.0


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def percentile_rank(latest: float, series: list[float]) -> float:
    return sum(1 for v in series if v <= latest) / len(series) * 100


def crowd_label(pct: float) -> str:
    if pct >= 90:
        return "極度擁擠"
    if pct <= 10:
        return "極度寬鬆"
    return "中性區間"


def fetch_coin(client: httpx.Client, coin: str) -> dict:
    symbol = PERP_SYMBOL[coin]
    resp = client.get(BASE_URL, params={"symbol": symbol, "limit": LIMIT})
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise RuntimeError("fundingRate 回傳空序列")

    rates = [float(r["fundingRate"]) for r in rows]
    latest_rate = rates[-1]
    latest_time = rows[-1]["fundingTime"]
    percentile = percentile_rank(latest_rate, rates)

    return {
        "perp": symbol,
        "source": "Binance Futures /fapi/v1/fundingRate",
        "sample_size": len(rates),
        "latest_funding_rate_pct": latest_rate * 100,
        "latest_funding_time": latest_time,
        "percentile_30d": percentile,
        "crowd_label": crowd_label(percentile),
        "fetched_at": now_iso(),
    }


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "funding_rate_percentile_snapshot.json"
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
                f"  最新費率 {result['latest_funding_rate_pct']:+.5f}%，"
                f"近 {result['sample_size']} 筆（約 30 天）百分位 {result['percentile_30d']:.1f}"
                f"（{result['crowd_label']}）"
            )
            print()


if __name__ == "__main__":
    main()

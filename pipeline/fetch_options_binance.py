"""選擇權 IV／Put-Call／25Δ Skew（對照 02改_資料網格.html 的 `options-deribit`
spec，id 沿用歷史命名沒改）。跟正式 `agent/collectors/` 還沒有對應模組，這裡
先是 Ken 自己驗證用的 prototype，屬於「衍生品類」缺口的一部分（跟 CME COT／
訂單簿深度／多空帳戶比／期貨到期結構／費率擁擠度同一批，都還沒併回正式
collector）。

## 資料來源：統一用 Binance Options（五幣同一套邏輯）

02 筆記原本設計是 Deribit 為主（機構主流選擇權平台），這裡繞了一圈：第一版
先做 Deribit，發現 SOL/BNB/XRP 沒有掛牌，一度誤判成「這三幣選擇權市場不存
在」，查證後發現 Binance Options（`eapi.binance.com`，免 key）其實五幣都有
掛牌，改成 Deribit 為主／Binance 為 SOL/BNB/XRP 的 fallback。Ken 看過兩套
資料源混用的版本後決定**直接統一用 Binance**：五幣同一個端點、同一套算法，
不用再解釋「BTC/ETH 這條線跟 SOL/BNB/XRP 那條線口徑不一樣」，賽前報告寫起
來更乾淨，代價是放棄 Deribit 那邊機構玩家為主的樣本（Binance Options 相對
零售導向），這裡是刻意的取捨，不是沒注意到差異。

- `GET https://eapi.binance.com/eapi/v1/mark`：全市場一次回傳所有掛牌選擇權
  合約，本地按 `{COIN}-` 前綴過濾。這個端點直接附 `markIV`／`delta`（含
  greeks），不用像原本 Deribit 版那樣本地反推 Black-Scholes
- `GET https://eapi.binance.com/eapi/v1/index?underlying={COIN}USDT`：現貨
  指數價
- `GET https://eapi.binance.com/eapi/v1/openInterest?underlyingAsset={COIN}
  &expiration={YYMMDD}`：該到期日逐檔未平倉量（`expiration` 參數必填，所以
  put/call OI 比要對該幣每個到期日各打一次）
- symbol 格式 `{COIN}-{YYMMDD}-{STRIKE}-{C|P}`（例：`SOL-260731-76-C`），
  到期時間固定 08:00 UTC

## 到期月份覆蓋範圍不是五幣一致

實測 BTC/ETH 在 Binance Options 上掛到 2027-06-25（跟 Deribit 覆蓋範圍接近），
但 SOL/BNB/XRP 目前只到約 10 天後（2026-07-21 實測最遠只到 7/31）——這不是
換資料源就能解決的問題，是這幾個幣本身在 Binance 上的選擇權市場還不夠成熟，
掛牌到期月份天生比 BTC/ETH 短很多。`days_to_expiry` 欄位誠實反映實際天數，
讀報告時 SOL/BNB/XRP 的 skew 天期口徑不能跟 BTC/ETH 混為一談。

## ⚠️ 流動性過濾：遠 OTM strike 常沒有真實雙邊報價

實測發現（尤其 SOL）遠 OTM 的 strike 常常沒人掛單，`markIV` 是 Binance 內部
模型在沒有真實成交/掛單時的預設定價，數字會亂跳、不成一條平滑的 vol smile
（例如緊鄰兩個 strike 的 IV 差超過一倍）。第一次沒過濾直接插值，25Δ skew
算出 -30% 這種方向完全反過來的離譜數字。用 `bidIV`／`askIV` 過濾：兩邊都要
有正值報價、價差不能超過 `markIV` 本身（`MAX_IV_SPREAD_RATIO`），只用「市場
真的在報價」的 strike 建 vol smile。BTC/ETH 掛牌數多、流動性厚，這個過濾器
影響不大；SOL/BNB/XRP 掛牌數少，過濾後有效點數可能逼近插值需要的下限
（`MIN_POINTS_FOR_CURVE=4`），賽前如果再跑，這幾幣有機率因為過濾太嚴格直接
跳過，是已知取捨，不是 bug。

## 通用計算邏輯

到期月份選擇：篩掉 3 天內到期的（避免 gamma 效應太極端），剩下的挑「距離
30 天最近」一檔當代表——沿用 `fetch_funding_rate_percentile.py` 的 30 天
近月代表性視窗慣例。SOL/BNB/XRP 目前掛牌天期都不到 30 天，會直接 clamp 到
「目前最遠一檔」。

把每個 call 的 `(delta, markIV)` 排序成一條 delta-vs-IV 曲線，線性插值找
`delta=0.25`（call 25Δ）跟 `delta=0.75`（＝put_delta=-0.25，put 25Δ）兩點的
IV；`ATM IV` 用 `delta=0.50` 插值取得。`25Δ skew = put_25d_iv - call_25d_iv`，
正值＝put IV 較高＝市場為下跌避險付更高保費，偏空訊號，跟 02 筆記「read」欄
一致。

Put/Call 比是另一個獨立指標（跟 25Δ skew 看的角度不同：skew 看「同 delta下
IV 差多少」，這個看「市場整體未平倉量誰多」），該幣**所有已知到期日**加總
`sumOpenInterest`，算 `put_oi / call_oi`。

用法：
    python pipeline/fetch_options_binance.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

import httpx

BINANCE_OPTIONS_BASE = "https://eapi.binance.com/eapi/v1"
HTTP_TIMEOUT = 20.0
RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "derivatives"

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
MIN_CONTRACTS = 10  # 掛牌合約數量門檻，低於這個數字 IV/skew 參考價值太低
MIN_POINTS_FOR_CURVE = 4  # 流動性過濾後至少要有幾個 strike 才插值
TARGET_TENOR_DAYS = 30.0
MIN_DAYS_TO_EXPIRY = 3.0
MAX_IV_SPREAD_RATIO = 1.0  # (askIV-bidIV)/markIV 超過這個比例視為報價太寬，剔除
OPTIONS_EXPIRY_HOUR_UTC = 8  # Binance Options 固定 08:00 UTC 到期結算


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_mark_all(client: httpx.Client) -> list[dict]:
    resp = client.get(f"{BINANCE_OPTIONS_BASE}/mark")
    resp.raise_for_status()
    return resp.json()


def parse_instrument(symbol: str) -> tuple[str, float, str]:
    """'SOL-260731-76-C' -> ('260731', 76.0, 'C')"""
    _, expiry, strike, opt_type = symbol.split("-")
    return expiry, float(strike), opt_type


def expiry_to_datetime(expiry: str) -> datetime:
    return datetime.strptime(expiry, "%y%m%d").replace(hour=OPTIONS_EXPIRY_HOUR_UTC, tzinfo=timezone.utc)


def pick_target_expiry(expiry_to_days: dict[str, float]) -> tuple[str, float]:
    candidates = {e: d for e, d in expiry_to_days.items() if d >= MIN_DAYS_TO_EXPIRY}
    if not candidates:
        raise RuntimeError("查無可用到期日（皆 < MIN_DAYS_TO_EXPIRY 或無掛牌）")
    best_expiry = min(candidates, key=lambda e: abs(candidates[e] - TARGET_TENOR_DAYS))
    return best_expiry, candidates[best_expiry]


def interpolate_iv_at_delta(curve: list[tuple[float, float, float]], target_delta: float) -> float:
    """曲線是 delta 升冪排列，線性插值找 target_delta 對應的 IV（單位：%）。
    target_delta 落在範圍外就 clamp 到端點。"""
    deltas = [p[0] for p in curve]
    if target_delta <= deltas[0]:
        return curve[0][1]
    if target_delta >= deltas[-1]:
        return curve[-1][1]
    for i in range(len(curve) - 1):
        d0, iv0, _ = curve[i]
        d1, iv1, _ = curve[i + 1]
        if d0 <= target_delta <= d1:
            if d1 == d0:
                return iv0
            weight = (target_delta - d0) / (d1 - d0)
            return iv0 + weight * (iv1 - iv0)
    raise RuntimeError("插值失敗，理論上不會發生")


def fetch_open_interest(client: httpx.Client, coin: str, expiry: str) -> list[dict]:
    resp = client.get(
        f"{BINANCE_OPTIONS_BASE}/openInterest",
        params={"underlyingAsset": coin, "expiration": expiry},
    )
    resp.raise_for_status()
    return resp.json()


def build_result(client: httpx.Client, coin: str, coin_rows: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    expiry_to_days = {}
    for row in coin_rows:
        expiry, _, _ = parse_instrument(row["symbol"])
        if expiry not in expiry_to_days:
            expiry_to_days[expiry] = (expiry_to_datetime(expiry) - now).total_seconds() / 86400

    target_expiry, days_to_expiry = pick_target_expiry(expiry_to_days)

    curve = []
    skipped_wide_spread = 0
    for row in coin_rows:
        expiry, strike, opt_type = parse_instrument(row["symbol"])
        if expiry != target_expiry or opt_type != "C":
            continue
        delta = float(row["delta"])
        mark_iv = float(row["markIV"])
        if mark_iv <= 0:
            continue
        bid_iv, ask_iv = float(row["bidIV"]), float(row["askIV"])
        if bid_iv <= 0 or ask_iv <= 0 or (ask_iv - bid_iv) > MAX_IV_SPREAD_RATIO * mark_iv:
            skipped_wide_spread += 1
            continue
        curve.append((delta, mark_iv * 100, strike))
    curve.sort(key=lambda p: p[0])
    if skipped_wide_spread:
        print(f"  [{coin}] 過濾掉 {skipped_wide_spread} 檔報價過寬/無雙邊報價的 strike，剩 {len(curve)} 檔建 vol smile")
    if len(curve) < MIN_POINTS_FOR_CURVE:
        raise RuntimeError(f"流動性過濾後只剩 {len(curve)} 檔（門檻 {MIN_POINTS_FOR_CURVE}），插值不可靠")

    atm_iv = interpolate_iv_at_delta(curve, 0.50)
    call_25d_iv = interpolate_iv_at_delta(curve, 0.25)
    put_25d_iv = interpolate_iv_at_delta(curve, 0.75)  # delta=0.75 等於 put_delta=-0.25

    index_resp = client.get(f"{BINANCE_OPTIONS_BASE}/index", params={"underlying": f"{coin}USDT"})
    index_resp.raise_for_status()
    underlying_price = float(index_resp.json()["indexPrice"])

    put_oi_total = 0.0
    call_oi_total = 0.0
    for expiry in expiry_to_days:
        for oi_row in fetch_open_interest(client, coin, expiry):
            amount = float(oi_row["sumOpenInterest"])
            if oi_row["symbol"].endswith("-P"):
                put_oi_total += amount
            else:
                call_oi_total += amount

    return {
        "source": "Binance Options /eapi/v1/mark（免 key，五幣統一來源）；25Δ skew 用 API 直接回傳的 delta/markIV，非本地反推",
        "underlying_price": underlying_price,
        "contract_count_total": len(coin_rows),
        "target_expiry": target_expiry,
        "days_to_expiry": round(days_to_expiry, 1),
        "atm_iv_pct": round(atm_iv, 2),
        "call_25d_iv_pct": round(call_25d_iv, 2),
        "put_25d_iv_pct": round(put_25d_iv, 2),
        "skew_25d_pct": round(put_25d_iv - call_25d_iv, 2),
        "put_open_interest_total": round(put_oi_total, 2),
        "call_open_interest_total": round(call_oi_total, 2),
        "put_call_oi_ratio": round(put_oi_total / call_oi_total, 4) if call_oi_total else None,
        "fetched_at": now_iso(),
    }


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "options_binance_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"coin": coin, **result}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def print_result(coin: str, out_path: Path, result: dict) -> None:
    print(f"[{coin}] 已寫入 {out_path}")
    print(f"  目標到期日 {result['target_expiry']}（{result['days_to_expiry']}天後），現貨/指數價 {result['underlying_price']}")
    print(
        f"  ATM IV={result['atm_iv_pct']}%　"
        f"Call 25Δ IV={result['call_25d_iv_pct']}%　"
        f"Put 25Δ IV={result['put_25d_iv_pct']}%　"
        f"Skew={result['skew_25d_pct']:+.2f}%"
    )
    print(f"  Put/Call OI 比={result['put_call_oi_ratio']}（put_oi={result['put_open_interest_total']}／call_oi={result['call_open_interest_total']}）")
    print()


def main() -> None:
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        mark_all = fetch_mark_all(client)
        for coin in COINS:
            coin_rows = [r for r in mark_all if r["symbol"].startswith(f"{coin}-")]
            if len(coin_rows) < MIN_CONTRACTS:
                print(f"[{coin}] Binance Options 僅 {len(coin_rows)} 檔掛牌（門檻 {MIN_CONTRACTS}），跳過")
                continue
            try:
                result = build_result(client, coin, coin_rows)
            except Exception as exc:  # noqa: BLE001
                print(f"[{coin}] 計算失敗：{exc}")
                continue
            out_path = write_output(coin, result)
            print_result(coin, out_path, result)


if __name__ == "__main__":
    main()

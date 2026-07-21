"""選擇權 IV／Put-Call／25Δ Skew（對照 02改_資料網格.html 的 `options-deribit`
spec）。跟正式 `agent/collectors/` 還沒有對應模組，這裡先是 Ken 自己驗證用的
prototype，屬於「衍生品類」缺口的一部分（跟 CME COT／訂單簿深度／多空帳戶比／
期貨到期結構／費率擁擠度同一批，都還沒併回正式 collector）。

## 資料來源：Deribit 為主，掛牌不足時 fallback Binance Options

主來源 Deribit 公開 API（免 key）：
    GET https://www.deribit.com/api/v2/public/get_book_summary_by_currency
        ?currency={COIN}&kind=option
一次拿到該幣所有掛牌選擇權合約的 mark_iv / open_interest / volume。

⚠️ 這個端點沒有 delta 欄位，02 筆記寫的「25-delta skew 需額外挑出約
25-delta 的 put/call」是衍生計算，不是單一欄位直接給。原本考慮另外呼叫
`/public/ticker?instrument_name=...`（單一合約才有 `greeks.delta`），但單一
到期月份掛牌動輒 30-50 檔，逐檔敲 API 不符合「單次執行」精神，改用本地
Black-Scholes 反推：同一 strike 的 call/put `mark_iv` 相同（put-call
parity），直接拿這個 IV 代入標準 BS 公式算 `d1`，`call_delta = N(d1)`、
`put_delta = call_delta - 1`（無風險利率設 0，業界算 skew 常見簡化）。

⚠️ **第一版這裡犯過一個錯，記錄下來避免重犯**：實測發現 Deribit 對 SOL/BNB/
XRP 的 `get_book_summary_by_currency` 回傳空陣列，第一版直接下結論寫成「SOL
選擇權已下市」，但 Ken 提醒他自己在 Binance 就能交易 SOL 選擇權——查證後發現
Binance Options（`eapi.binance.com`）其實五幣都有掛牌（BTC 548／ETH 560／
SOL 132／BNB 120／XRP 56 檔，2026-07-21 實測），只是 Deribit 這個特定交易所
沒有 SOL/BNB/XRP。**「Deribit 沒有」跟「這個幣沒有選擇權市場」是兩件不同的
事**，不能把單一資料源查無結果直接推廣成「整個市場沒有」，跟 02 網格其他章節
（CME COT／期貨到期結構）已經踩過的「不要把單一資料源的缺席當成整個市場的
缺席」是同一類錯誤，這次是我自己犯的，不是抄舊筆記的錯。

所以現在的邏輯：Deribit 掛牌數 < `MIN_CONTRACTS` 就 fallback 到 Binance
Options：
    GET https://eapi.binance.com/eapi/v1/mark（全市場一次回傳，本地按
        `{COIN}-` 前綴過濾）：每檔直接附 `markIV`／`delta`，不用像 Deribit
        那樣本地反推——Binance 這個端點本身就把 greeks 算好了
    GET https://eapi.binance.com/eapi/v1/index?underlying={COIN}USDT：現貨
        指數價
    GET https://eapi.binance.com/eapi/v1/openInterest?underlyingAsset={COIN}
        &expiration={YYMMDD}：該到期日逐檔未平倉量（這個端點的 expiration
        參數是必填，所以 put/call OI 比要對目標幣種每個到期日各打一次，
        不像 Deribit book_summary 一次拿全部）
- Binance symbol 格式 `{COIN}-{YYMMDD}-{STRIKE}-{C|P}`（例：`SOL-260731-76-C`），
  到期時間同樣是 08:00 UTC，跟 Deribit 巧合一致
- ⚠️ Binance Options 對 SOL/BNB/XRP 目前只有到約 10 天後的到期月份（截至
  2026-07-21 實測，最遠只到 7/31），遠不到 Deribit BTC/ETH 那種到 2027 年的
  覆蓋範圍，30 天目標到期日在這三幣身上會直接 clamp 到「目前最遠一檔」，
  `days_to_expiry` 欄位會誠實反映實際天數，讀報告時不能預設這三幣的 skew
  跟 BTC/ETH 是同一個天期口徑
- Binance 是零售導向交易所，跟 Deribit 這種機構主流選擇權平台的參與者結構
  不同，02 網格「機構衍生品管道缺席＝風險特徵」這句話如果沿用在 SOL/BNB/XRP
  上，措辭需要改成「Deribit（機構平台）缺席，但 Binance（零售為主）仍有
  掛牌」，不能再講「完全沒有選擇權市場」

## 通用計算邏輯（兩個來源共用同一套 25Δ skew／ATM IV 算法）

到期月份選擇：篩掉 3 天內到期的（避免 gamma 效應太極端），剩下的挑「距離
30 天最近」一檔當代表——沿用 `fetch_funding_rate_percentile.py` 的 30 天
近月代表性視窗慣例。

把每個 strike 的 `(call_delta, mark_iv)` 排序成一條 delta-vs-IV 曲線，線性
插值找 `call_delta=0.25`（call 25Δ）跟 `call_delta=0.75`（＝put_delta=
-0.25，put 25Δ）兩點的 IV；`ATM IV` 用 `call_delta=0.50` 插值取得。
`25Δ skew = put_25d_iv - call_25d_iv`，正值＝put IV 較高＝市場為下跌避險
付更高保費，偏空訊號，跟 02 筆記「read」欄一致。

Put/Call 比是另一個獨立指標（跟 25Δ skew 看的角度不同：skew 看「同 delta
下 IV 差多少」，這個看「市場整體未平倉量誰多」），Deribit 版是全部到期月份
加總，Binance 版受限於 openInterest 端點要求 expiration 參數，是「該幣所有
已知到期日」逐一加總後的結果，語意上一致。

用法：
    python pipeline/fetch_options_deribit.py
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
import json

import httpx

DERIBIT_BASE = "https://www.deribit.com/api/v2/public"
BINANCE_OPTIONS_BASE = "https://eapi.binance.com/eapi/v1"
HTTP_TIMEOUT = 20.0
RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "derivatives"

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
MIN_CONTRACTS = 10  # 掛牌合約數量門檻，低於這個數字 IV/skew 參考價值太低
TARGET_TENOR_DAYS = 30.0
MIN_DAYS_TO_EXPIRY = 3.0
OPTIONS_EXPIRY_HOUR_UTC = 8  # Deribit／Binance Options 皆固定 08:00 UTC 到期結算


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def interpolate_iv_at_delta(curve: list[tuple[float, float, float]], target_delta: float) -> float:
    """曲線是 call_delta 升冪排列，線性插值找 target_delta 對應的 IV（單位：%）。
    target_delta 落在範圍外就 clamp 到端點（掛牌覆蓋不到那麼極端的 delta）。"""
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


def summarize_curve(curve: list[tuple[float, float, float]]) -> dict:
    if len(curve) < 4:
        raise RuntimeError(f"目標到期日掛牌 strike 數量太少（{len(curve)}），插值不可靠")
    atm_iv = interpolate_iv_at_delta(curve, 0.50)
    call_25d_iv = interpolate_iv_at_delta(curve, 0.25)
    put_25d_iv = interpolate_iv_at_delta(curve, 0.75)  # call_delta=0.75 等於 put_delta=-0.25
    return {
        "atm_iv_pct": round(atm_iv, 2),
        "call_25d_iv_pct": round(call_25d_iv, 2),
        "put_25d_iv_pct": round(put_25d_iv, 2),
        "skew_25d_pct": round(put_25d_iv - call_25d_iv, 2),
    }


# ---------------------------------------------------------------------------
# Deribit（主來源：BTC/ETH，機構主流選擇權平台）
# ---------------------------------------------------------------------------

def fetch_deribit_book_summary(client: httpx.Client, currency: str) -> list[dict]:
    resp = client.get(
        f"{DERIBIT_BASE}/get_book_summary_by_currency",
        params={"currency": currency, "kind": "option"},
    )
    resp.raise_for_status()
    return resp.json()["result"]


def parse_deribit_instrument(name: str) -> tuple[str, float, str]:
    """'BTC-28AUG26-65000-C' -> ('28AUG26', 65000.0, 'C')"""
    _, expiry, strike, opt_type = name.split("-")
    return expiry, float(strike), opt_type


def deribit_expiry_to_datetime(expiry: str) -> datetime:
    return datetime.strptime(expiry, "%d%b%y").replace(hour=OPTIONS_EXPIRY_HOUR_UTC, tzinfo=timezone.utc)


def pick_target_expiry(expiry_to_days: dict[str, float]) -> tuple[str, float]:
    candidates = {e: d for e, d in expiry_to_days.items() if d >= MIN_DAYS_TO_EXPIRY}
    if not candidates:
        raise RuntimeError("查無可用到期日（皆 < MIN_DAYS_TO_EXPIRY 或無掛牌）")
    best_expiry = min(candidates, key=lambda e: abs(candidates[e] - TARGET_TENOR_DAYS))
    return best_expiry, candidates[best_expiry]


def build_result_deribit(coin: str, rows: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    expiry_to_days = {}
    for row in rows:
        expiry, _, _ = parse_deribit_instrument(row["instrument_name"])
        if expiry not in expiry_to_days:
            expiry_to_days[expiry] = (deribit_expiry_to_datetime(expiry) - now).total_seconds() / 86400

    target_expiry, days_to_expiry = pick_target_expiry(expiry_to_days)
    T = days_to_expiry / 365.0

    curve = []
    seen_strikes = set()
    for row in rows:
        expiry, strike, opt_type = parse_deribit_instrument(row["instrument_name"])
        if expiry != target_expiry or opt_type != "C" or strike in seen_strikes:
            continue
        sigma = row["mark_iv"] / 100.0
        if sigma <= 0:
            continue
        S = row["underlying_price"]
        d1 = (math.log(S / strike) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        curve.append((normal_cdf(d1), row["mark_iv"], strike))
        seen_strikes.add(strike)
    curve.sort(key=lambda p: p[0])

    underlying_price = next(r["underlying_price"] for r in rows if r["instrument_name"].startswith(f"{coin}-{target_expiry}-"))
    put_oi = sum(r["open_interest"] for r in rows if r["instrument_name"].endswith("-P"))
    call_oi = sum(r["open_interest"] for r in rows if r["instrument_name"].endswith("-C"))

    return {
        "source": "Deribit /public/get_book_summary_by_currency（免 key），25Δ skew 為本地 Black-Scholes 反推，非 API 直接欄位",
        "underlying_price": underlying_price,
        "contract_count_total": len(rows),
        "target_expiry": target_expiry,
        "days_to_expiry": round(days_to_expiry, 1),
        **summarize_curve(curve),
        "put_open_interest_total": round(put_oi, 2),
        "call_open_interest_total": round(call_oi, 2),
        "put_call_oi_ratio": round(put_oi / call_oi, 4) if call_oi else None,
        "fetched_at": now_iso(),
    }


# ---------------------------------------------------------------------------
# Binance Options（fallback：Deribit 掛牌不足時使用，目前用於 SOL/BNB/XRP）
# ---------------------------------------------------------------------------

def fetch_binance_mark_all(client: httpx.Client) -> list[dict]:
    resp = client.get(f"{BINANCE_OPTIONS_BASE}/mark")
    resp.raise_for_status()
    return resp.json()


def parse_binance_instrument(symbol: str) -> tuple[str, float, str]:
    """'SOL-260731-76-C' -> ('260731', 76.0, 'C')"""
    _, expiry, strike, opt_type = symbol.split("-")
    return expiry, float(strike), opt_type


def binance_expiry_to_datetime(expiry: str) -> datetime:
    return datetime.strptime(expiry, "%y%m%d").replace(hour=OPTIONS_EXPIRY_HOUR_UTC, tzinfo=timezone.utc)


def fetch_binance_open_interest(client: httpx.Client, coin: str, expiry: str) -> list[dict]:
    resp = client.get(
        f"{BINANCE_OPTIONS_BASE}/openInterest",
        params={"underlyingAsset": coin, "expiration": expiry},
    )
    resp.raise_for_status()
    return resp.json()


MAX_IV_SPREAD_RATIO = 1.0  # (askIV-bidIV)/markIV 超過這個比例視為報價太寬，市場沒人要，剔除


def build_result_binance(client: httpx.Client, coin: str, coin_rows: list[dict]) -> dict:
    """⚠️ SOL/BNB/XRP 這幾幣的 Binance Options 掛牌雖然存在，但實測發現遠 OTM
    strike（delta 接近 0 或 1）常常沒有真實雙邊報價，`markIV` 是 Binance 內部
    模型在沒有真實成交/掛單時的預設定價，數字會亂跳、不成一條平滑的 vol
    smile（例如 SOL 曾出現緊鄰兩個 strike 的 IV 差一倍以上），直接拿來插值
    25Δ 點會算出方向錯亂的離譜 skew（實測踩過一次：算出 -30% 這種不合理數字）。
    用 `bidIV`/`askIV` 兩個欄位過濾：兩邊都要有正值報價、價差不能超過
    markIV 本身（`MAX_IV_SPREAD_RATIO`），確保只用「市場真的在報價」的
    strike 建 vol smile，不是每一檔掛牌都拿來用。"""
    now = datetime.now(timezone.utc)
    expiry_to_days = {}
    for row in coin_rows:
        expiry, _, _ = parse_binance_instrument(row["symbol"])
        if expiry not in expiry_to_days:
            expiry_to_days[expiry] = (binance_expiry_to_datetime(expiry) - now).total_seconds() / 86400

    target_expiry, days_to_expiry = pick_target_expiry(expiry_to_days)

    curve = []
    skipped_wide_spread = 0
    for row in coin_rows:
        expiry, strike, opt_type = parse_binance_instrument(row["symbol"])
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

    index_resp = client.get(f"{BINANCE_OPTIONS_BASE}/index", params={"underlying": f"{coin}USDT"})
    index_resp.raise_for_status()
    underlying_price = float(index_resp.json()["indexPrice"])

    put_oi_total = 0.0
    call_oi_total = 0.0
    for expiry in expiry_to_days:
        for oi_row in fetch_binance_open_interest(client, coin, expiry):
            amount = float(oi_row["sumOpenInterest"])
            if oi_row["symbol"].endswith("-P"):
                put_oi_total += amount
            else:
                call_oi_total += amount

    return {
        "source": "Binance Options /eapi/v1/mark（免 key，fallback——Deribit 沒有這幣掛牌）；25Δ skew 用 API 直接回傳的 delta/markIV，非本地反推",
        "underlying_price": underlying_price,
        "contract_count_total": len(coin_rows),
        "target_expiry": target_expiry,
        "days_to_expiry": round(days_to_expiry, 1),
        **summarize_curve(curve),
        "put_open_interest_total": round(put_oi_total, 2),
        "call_open_interest_total": round(call_oi_total, 2),
        "put_call_oi_ratio": round(put_oi_total / call_oi_total, 4) if call_oi_total else None,
        "fetched_at": now_iso(),
    }


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "options_deribit_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"coin": coin, **result}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def print_result(coin: str, out_path: Path, result: dict) -> None:
    print(f"[{coin}] 已寫入 {out_path}")
    print(f"  來源：{result['source']}")
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
    binance_mark_cache: list[dict] | None = None

    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        for coin in COINS:
            try:
                deribit_rows = fetch_deribit_book_summary(client, coin)
            except Exception as exc:  # noqa: BLE001
                print(f"[{coin}] Deribit 抓取失敗：{exc}")
                deribit_rows = []

            try:
                if len(deribit_rows) >= MIN_CONTRACTS:
                    result = build_result_deribit(coin, deribit_rows)
                else:
                    print(f"[{coin}] Deribit 僅 {len(deribit_rows)} 檔掛牌（門檻 {MIN_CONTRACTS}），fallback Binance Options")
                    if binance_mark_cache is None:
                        binance_mark_cache = fetch_binance_mark_all(client)
                    coin_rows = [r for r in binance_mark_cache if r["symbol"].startswith(f"{coin}-")]
                    if len(coin_rows) < MIN_CONTRACTS:
                        print(f"[{coin}] Binance Options 也僅 {len(coin_rows)} 檔，跳過——這個幣目前兩個來源都沒有夠用的選擇權市場")
                        continue
                    result = build_result_binance(client, coin, coin_rows)
            except Exception as exc:  # noqa: BLE001
                print(f"[{coin}] 計算失敗：{exc}")
                continue

            out_path = write_output(coin, result)
            print_result(coin, out_path, result)


if __name__ == "__main__":
    main()

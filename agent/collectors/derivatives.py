"""衍生品資料 collector：費率擁擠度／OI×價格四象限／多空帳戶比背離／期貨到期
結構／CME COT 機構倉位／選擇權 IV-Skew／CEX-DEX 費率差，七項邏輯皆搬自
`pipeline/fetch_*.py` prototype（已個別驗證過，見 `pipeline/流程紀錄.md`），這裡
是第一次併成正式 collector。

跨幣費率差（`compute_cross_coin_funding_diff.py`）暫不在此檔——它是雙幣比較題
專用，跟 `relative.py` 一樣需要兩個幣種同時比較，不適合塞進單幣種
`fetch(coin)` 介面。清算流（`fetch_liquidation_flow.py`）也暫不在此檔——它是
單次 45 秒 WebSocket 監聽全市場事件後依幣種分流，跟其他七項「打一次 API 拿
一個幣種的資料」模型不同，若照現有介面每個幣種各自監聽 45 秒會浪費 5 倍
時間。兩者併入方式待與 alanchang 討論，記在
`pipeline/待辦筆記/derivatives_collector化.md`。

單一子來源失敗（例如 CME COT 沒有 BNB 期貨、選擇權掛牌數不足）不拋例外，
只是該項不產生證據，並記一筆 log_subsource；不影響同一次 fetch() 裡其他子
來源的結果。
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from agent.collectors.base import BaseCollector
from agent.schemas import EvidenceDraft, LogStatus, now_iso

HTTP_TIMEOUT = 20.0

PERP_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT", "XRP": "XRPUSDT"}

FAPI_BASE = "https://fapi.binance.com/fapi/v1"
FUTURES_DATA_BASE = "https://fapi.binance.com/futures/data"
DAPI_BASE = "https://dapi.binance.com"
EAPI_BASE = "https://eapi.binance.com/eapi/v1"
HYPERLIQUID_URL = "https://api.hyperliquid.xyz/info"
COT_API_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"

# 費率擁擠度：每 8 小時一筆，limit=90 剛好覆蓋近 30 天
FUNDING_LIMIT = 90
# OI×價格四象限、多空帳戶比：近 30 小時趨勢
HOURLY_TREND_LIMIT = 30
HOUR_MS = 3_600_000

QUADRANT_LABEL = {
    ("up", "up"): "多頭增倉（順勢，新多頭進場）",
    ("up", "down"): "空頭增倉（順勢，新空頭進場）",
    ("down", "down"): "多頭停損離場（可能止跌）",
    ("down", "up"): "空頭回補（可能追高風險）",
    ("flat", "up"): "價漲 OI 持平（方向不明）",
    ("flat", "down"): "價跌 OI 持平（方向不明）",
    ("up", "flat"): "OI 增加價格持平（方向不明）",
    ("down", "flat"): "OI 減少價格持平（方向不明）",
    ("flat", "flat"): "OI 價格皆持平（無明顯訊號）",
}

CME_COT_TREND_WEEKS = 12
# 精確市場名稱（已用 API 實測核對，不是模糊比對）。BNB 沒有 CME 期貨，不在此列。
CME_COT_MARKET_NAMES = {
    "BTC": "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
    "ETH": "ETHER CASH SETTLED - CHICAGO MERCANTILE EXCHANGE",
    "SOL": "SOL - CHICAGO MERCANTILE EXCHANGE",
    "XRP": "XRP - CHICAGO MERCANTILE EXCHANGE",
}
CME_COT_SELECT_FIELDS = [
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

OPTIONS_MIN_CONTRACTS = 10
OPTIONS_MIN_POINTS_FOR_CURVE = 4
OPTIONS_TARGET_TENOR_DAYS = 30.0
OPTIONS_MIN_DAYS_TO_EXPIRY = 3.0
OPTIONS_MAX_IV_SPREAD_RATIO = 1.0
OPTIONS_EXPIRY_HOUR_UTC = 8

CEX_FUNDING_INTERVAL_HOURS = 8
DEX_FUNDING_INTERVAL_HOURS = 1
HOURS_PER_YEAR = 24 * 365
CEX_DEX_DIVERGENCE_THRESHOLD_PCT = 5.0


def percentile_rank(latest: float, series: list[float]) -> float:
    """window 內 <= 最新值 的比例，跟 pipeline/compute_relative_strength.py 同一套定義。"""
    return sum(1 for v in series if v <= latest) / len(series) * 100


def crowd_label(pct: float) -> str:
    if pct >= 90:
        return "極度擁擠"
    if pct <= 10:
        return "極度寬鬆"
    return "中性區間"


def hour_bucket(ts_ms: int) -> int:
    return ts_ms // HOUR_MS


def move_direction(latest: float, prev: float) -> str:
    if latest > prev:
        return "up"
    if latest < prev:
        return "down"
    return "flat"


def ratio_direction(ratio: float) -> str:
    return "偏多" if ratio > 1 else "偏空"


def parse_option_instrument(symbol: str) -> tuple[str, float, str]:
    """'SOL-260731-76-C' -> ('260731', 76.0, 'C')"""
    _, expiry, strike, opt_type = symbol.split("-")
    return expiry, float(strike), opt_type


def option_expiry_to_datetime(expiry: str) -> datetime:
    return datetime.strptime(expiry, "%y%m%d").replace(hour=OPTIONS_EXPIRY_HOUR_UTC, tzinfo=timezone.utc)


def interpolate_iv_at_delta(curve: list[tuple[float, float, float]], target_delta: float) -> float:
    """curve 是 delta 升冪排列的 (delta, iv_pct, strike)，線性插值找 target_delta 對應的 IV。
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


class DerivativesCollector(BaseCollector):
    name = "derivatives_collector"
    source_type = "derivatives"

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        coin = coin.upper()
        symbol = PERP_SYMBOL.get(coin)
        if symbol is None:
            return []

        evidences: list[EvidenceDraft] = []
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            for fetch_fn, sub_name in (
                (self._fetch_funding_rate_percentile, "funding_rate_percentile"),
                (self._fetch_oi_price_quadrant, "oi_price_quadrant"),
                (self._fetch_long_short_ratio, "long_short_ratio"),
                (self._fetch_futures_term_structure, "futures_term_structure"),
                (self._fetch_cme_cot, "cme_cot"),
                (self._fetch_options_iv_skew, "options_iv_skew"),
                (self._fetch_cex_dex_funding_diff, "cex_dex_funding_diff"),
            ):
                try:
                    ev = await fetch_fn(client, coin, symbol)
                    if ev is not None:
                        evidences.append(ev)
                except Exception as exc:  # noqa: BLE001 - 單一子來源失敗不影響其他子來源
                    self.log_subsource(sub_name, coin, LogStatus.ERROR, f"error={exc}")

        return evidences

    # --- 1. 費率擁擠度：近 30 天 funding rate 百分位 ---
    async def _fetch_funding_rate_percentile(
        self, client: httpx.AsyncClient, coin: str, symbol: str
    ) -> EvidenceDraft | None:
        resp = await client.get(f"{FAPI_BASE}/fundingRate", params={"symbol": symbol, "limit": FUNDING_LIMIT})
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            raise RuntimeError("fundingRate 回傳空序列")

        rates = [float(r["fundingRate"]) for r in rows]
        latest_rate = rates[-1]
        percentile = percentile_rank(latest_rate, rates)
        label = crowd_label(percentile)

        return EvidenceDraft(
            coin=coin,
            source="Binance Futures /fapi/v1/fundingRate",
            source_url=f"{FAPI_BASE}/fundingRate",
            fetched_at=now_iso(),
            content_reference=(
                f"query: symbol={symbol}&limit={FUNDING_LIMIT} | "
                f"最新資金費率 {latest_rate * 100:+.5f}%，近 {len(rates)} 筆（約 30 天）"
                f"百分位 {percentile:.1f}（{label}）。正費率本身是常態（多頭付空頭），"
                f"只有極端百分位（>90 或 <10）才是擁擠度訊號"
            ),
            related_claim=f"{coin} 永續合約資金費率擁擠度（30 天相對位置）",
            source_type="derivatives",
        )

    # --- 2. OI × 價格四象限：近 30 小時 OI 與價格同向/背離 ---
    async def _fetch_oi_price_quadrant(
        self, client: httpx.AsyncClient, coin: str, symbol: str
    ) -> EvidenceDraft | None:
        current_resp = await client.get(f"{FAPI_BASE}/openInterest", params={"symbol": symbol})
        current_resp.raise_for_status()

        oi_resp = await client.get(
            f"{FUTURES_DATA_BASE}/openInterestHist",
            params={"symbol": symbol, "period": "1h", "limit": HOURLY_TREND_LIMIT},
        )
        oi_resp.raise_for_status()
        oi_rows = oi_resp.json()
        if not oi_rows:
            raise RuntimeError("openInterestHist 回傳空序列")

        kline_resp = await client.get(
            f"{FAPI_BASE}/klines", params={"symbol": symbol, "interval": "1h", "limit": HOURLY_TREND_LIMIT}
        )
        kline_resp.raise_for_status()
        kline_rows = kline_resp.json()
        if not kline_rows:
            raise RuntimeError("klines 回傳空序列")

        oi_by_bucket = {hour_bucket(int(r["timestamp"])): float(r["sumOpenInterest"]) for r in oi_rows}
        price_by_bucket = {hour_bucket(int(r[0])): float(r[4]) for r in kline_rows}
        shared_buckets = sorted(set(oi_by_bucket) & set(price_by_bucket))
        if len(shared_buckets) < 2:
            raise RuntimeError("對齊後樣本數不足以判斷方向（少於 2 個共同時間桶）")

        latest_bucket, prev_bucket = shared_buckets[-1], shared_buckets[-2]
        oi_dir = move_direction(oi_by_bucket[latest_bucket], oi_by_bucket[prev_bucket])
        price_dir = move_direction(price_by_bucket[latest_bucket], price_by_bucket[prev_bucket])
        quadrant = QUADRANT_LABEL[(oi_dir, price_dir)]

        return EvidenceDraft(
            coin=coin,
            source="Binance Futures /fapi/v1/openInterest + /futures/data/openInterestHist + /fapi/v1/klines",
            source_url=f"{FUTURES_DATA_BASE}/openInterestHist",
            fetched_at=now_iso(),
            content_reference=(
                f"query: symbol={symbol}&period=1h&limit={HOURLY_TREND_LIMIT} | "
                f"最新 OI {oi_by_bucket[latest_bucket]:.2f}（{oi_dir}）、"
                f"價格 {price_by_bucket[latest_bucket]:.4f}（{price_dir}）→ {quadrant}"
                f"（對齊 {len(shared_buckets)} 個共同時間桶）"
            ),
            related_claim=f"{coin} 未平倉量與價格的四象限市場結構解讀",
            source_type="derivatives",
        )

    # --- 3. 多空帳戶比：散戶 vs 大戶持倉是否背離 ---
    async def _fetch_long_short_ratio(
        self, client: httpx.AsyncClient, coin: str, symbol: str
    ) -> EvidenceDraft | None:
        retail_resp = await client.get(
            f"{FUTURES_DATA_BASE}/globalLongShortAccountRatio",
            params={"symbol": symbol, "period": "1h", "limit": HOURLY_TREND_LIMIT},
        )
        retail_resp.raise_for_status()
        retail_rows = retail_resp.json()
        if not retail_rows:
            raise RuntimeError("globalLongShortAccountRatio 回傳空序列")

        smart_resp = await client.get(
            f"{FUTURES_DATA_BASE}/topLongShortPositionRatio",
            params={"symbol": symbol, "period": "1h", "limit": HOURLY_TREND_LIMIT},
        )
        smart_resp.raise_for_status()
        smart_rows = smart_resp.json()
        if not smart_rows:
            raise RuntimeError("topLongShortPositionRatio 回傳空序列")

        retail_latest = float(retail_rows[-1]["longShortRatio"])
        smart_latest = float(smart_rows[-1]["longShortRatio"])
        retail_dir = ratio_direction(retail_latest)
        smart_dir = ratio_direction(smart_latest)
        diverged = retail_dir != smart_dir

        return EvidenceDraft(
            coin=coin,
            source="Binance Futures /futures/data/globalLongShortAccountRatio + topLongShortPositionRatio",
            source_url=f"{FUTURES_DATA_BASE}/globalLongShortAccountRatio",
            fetched_at=now_iso(),
            content_reference=(
                f"query: symbol={symbol}&period=1h&limit={HOURLY_TREND_LIMIT} | "
                f"散戶比值 {retail_latest:.4f}（{retail_dir}） vs 大戶比值 {smart_latest:.4f}"
                f"（{smart_dir}） → {'背離（經典反指標訊號）' if diverged else '同向'}"
            ),
            related_claim=f"{coin} 散戶與大戶（smart money）持倉方向是否背離",
            source_type="derivatives",
        )

    # --- 4. 期貨到期結構：永續/當季/次季 contango/backwardation ---
    async def _fetch_futures_term_structure(
        self, client: httpx.AsyncClient, coin: str, symbol: str
    ) -> EvidenceDraft | None:
        pair = f"{coin}USD"
        exchange_resp = await client.get(f"{DAPI_BASE}/dapi/v1/exchangeInfo")
        exchange_resp.raise_for_status()
        quarterly: dict[str, dict] = {}
        for s in exchange_resp.json()["symbols"]:
            if (
                s.get("pair") == pair
                and s.get("contractType") in ("CURRENT_QUARTER", "NEXT_QUARTER")
                and s.get("contractStatus") == "TRADING"
            ):
                quarterly[s["contractType"]] = {"symbol": s["symbol"], "delivery_date_ms": s["deliveryDate"]}
        if "CURRENT_QUARTER" not in quarterly or "NEXT_QUARTER" not in quarterly:
            self.log_subsource(
                "futures_term_structure", coin, LogStatus.SKIPPED, "COIN-M 查無完整當季/次季合約"
            )
            return None

        async def premium_index(sym: str) -> dict:
            r = await client.get(f"{DAPI_BASE}/dapi/v1/premiumIndex", params={"symbol": sym})
            r.raise_for_status()
            rows = r.json()
            if not rows:
                raise RuntimeError(f"premiumIndex 查無資料：symbol={sym}")
            return rows[0]

        now_ms = datetime.now(timezone.utc).timestamp() * 1000
        perp = await premium_index(f"{pair}_PERP")
        index_price = float(perp["indexPrice"])
        perp_mark = float(perp["markPrice"])

        marks = [perp_mark]
        detail_parts = [f"perp mark={perp_mark:.4f}（基差{(perp_mark - index_price) / index_price * 100:+.4f}%）"]
        for label, key in (("當季", "CURRENT_QUARTER"), ("次季", "NEXT_QUARTER")):
            info = quarterly[key]
            data = await premium_index(info["symbol"])
            mark = float(data["markPrice"])
            days_to_expiry = (info["delivery_date_ms"] - now_ms) / 1000 / 86400
            annualized = (mark - index_price) / index_price * (365 / days_to_expiry) * 100
            marks.append(mark)
            detail_parts.append(
                f"{label} mark={mark:.4f}（年化基差{annualized:+.2f}%，{days_to_expiry:.0f}天後到期）"
            )

        if marks[0] < marks[1] < marks[2]:
            shape = "contango"
        elif marks[0] > marks[1] > marks[2]:
            shape = "backwardation"
        else:
            shape = "mixed"

        return EvidenceDraft(
            coin=coin,
            source="Binance COIN-M dapi.binance.com /dapi/v1/premiumIndex（免 key，五幣統一來源）",
            source_url=f"{DAPI_BASE}/dapi/v1/premiumIndex",
            fetched_at=now_iso(),
            content_reference=(
                f"query: pair={pair} | 曲線形狀：{shape} → " + " → ".join(detail_parts)
            ),
            related_claim=f"{coin} 期貨到期結構曲線形狀（contango/backwardation）",
            source_type="derivatives",
        )

    # --- 5. CME COT：機構（Asset Manager）淨倉位，BNB 無 CME 期貨直接跳過 ---
    async def _fetch_cme_cot(
        self, client: httpx.AsyncClient, coin: str, symbol: str
    ) -> EvidenceDraft | None:
        market_name = CME_COT_MARKET_NAMES.get(coin)
        if market_name is None:
            self.log_subsource("cme_cot", coin, LogStatus.SKIPPED, "BNB 沒有 CME 期貨，CFTC 週報查不到")
            return None

        resp = await client.get(
            COT_API_URL,
            params={
                "$where": f"market_and_exchange_names = '{market_name}'",
                "$order": "report_date_as_yyyy_mm_dd DESC",
                "$limit": str(CME_COT_TREND_WEEKS),
                "$select": ",".join(CME_COT_SELECT_FIELDS),
            },
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            raise RuntimeError(f"查無資料：market_and_exchange_names = '{market_name}'")

        latest = rows[0]
        asset_mgr_net = int(latest["asset_mgr_positions_long"]) - int(latest["asset_mgr_positions_short"])
        asset_mgr_change = int(latest["change_in_asset_mgr_long"]) - int(latest["change_in_asset_mgr_short"])
        lev_money_net = int(latest["lev_money_positions_long"]) - int(latest["lev_money_positions_short"])
        report_date = latest["report_date_as_yyyy_mm_dd"][:10]

        return EvidenceDraft(
            coin=coin,
            source=f"CFTC TFF Futures Only（{market_name}）",
            source_url=COT_API_URL,
            fetched_at=now_iso(),
            content_reference=(
                f"最新報告日 {report_date}（週頻，落後至當週二）：Asset Manager（機構配置型）"
                f"淨倉位 {asset_mgr_net:+,}（本週變化 {asset_mgr_change:+,}），"
                f"Leveraged Funds（避險/動能型）淨倉位 {lev_money_net:+,}"
            ),
            related_claim=f"{coin} CME 期貨機構淨倉位方向（層2 敘事背景佐證，非即時訊號）",
            source_type="derivatives",
        )

    # --- 6. 選擇權 IV/Skew：Binance Options 五幣統一來源 ---
    async def _fetch_options_iv_skew(
        self, client: httpx.AsyncClient, coin: str, symbol: str
    ) -> EvidenceDraft | None:
        mark_resp = await client.get(f"{EAPI_BASE}/mark")
        mark_resp.raise_for_status()
        coin_rows = [r for r in mark_resp.json() if r["symbol"].startswith(f"{coin}-")]
        if len(coin_rows) < OPTIONS_MIN_CONTRACTS:
            self.log_subsource(
                "options_iv_skew", coin, LogStatus.SKIPPED,
                f"Binance Options 僅 {len(coin_rows)} 檔掛牌（門檻 {OPTIONS_MIN_CONTRACTS}）",
            )
            return None

        now = datetime.now(timezone.utc)
        expiry_to_days: dict[str, float] = {}
        for row in coin_rows:
            expiry, _, _ = parse_option_instrument(row["symbol"])
            if expiry not in expiry_to_days:
                expiry_to_days[expiry] = (option_expiry_to_datetime(expiry) - now).total_seconds() / 86400

        candidates = {e: d for e, d in expiry_to_days.items() if d >= OPTIONS_MIN_DAYS_TO_EXPIRY}
        if not candidates:
            raise RuntimeError("查無可用到期日（皆 < MIN_DAYS_TO_EXPIRY 或無掛牌）")
        target_expiry = min(candidates, key=lambda e: abs(candidates[e] - OPTIONS_TARGET_TENOR_DAYS))
        days_to_expiry = candidates[target_expiry]

        curve: list[tuple[float, float, float]] = []
        for row in coin_rows:
            expiry, strike, opt_type = parse_option_instrument(row["symbol"])
            if expiry != target_expiry or opt_type != "C":
                continue
            mark_iv = float(row["markIV"])
            if mark_iv <= 0:
                continue
            bid_iv, ask_iv = float(row["bidIV"]), float(row["askIV"])
            if bid_iv <= 0 or ask_iv <= 0 or (ask_iv - bid_iv) > OPTIONS_MAX_IV_SPREAD_RATIO * mark_iv:
                continue
            curve.append((float(row["delta"]), mark_iv * 100, strike))
        curve.sort(key=lambda p: p[0])
        if len(curve) < OPTIONS_MIN_POINTS_FOR_CURVE:
            raise RuntimeError(
                f"流動性過濾後只剩 {len(curve)} 檔（門檻 {OPTIONS_MIN_POINTS_FOR_CURVE}），插值不可靠"
            )

        atm_iv = interpolate_iv_at_delta(curve, 0.50)
        call_25d_iv = interpolate_iv_at_delta(curve, 0.25)
        put_25d_iv = interpolate_iv_at_delta(curve, 0.75)  # delta=0.75 等於 put_delta=-0.25
        skew_25d = put_25d_iv - call_25d_iv

        put_oi_total = 0.0
        call_oi_total = 0.0
        for expiry in expiry_to_days:
            oi_resp = await client.get(
                f"{EAPI_BASE}/openInterest", params={"underlyingAsset": coin, "expiration": expiry}
            )
            oi_resp.raise_for_status()
            for oi_row in oi_resp.json():
                amount = float(oi_row["sumOpenInterest"])
                if oi_row["symbol"].endswith("-P"):
                    put_oi_total += amount
                else:
                    call_oi_total += amount
        put_call_ratio = put_oi_total / call_oi_total if call_oi_total else None
        put_call_part = (
            f"Put/Call OI比={put_call_ratio:.4f}"
            if put_call_ratio is not None
            else "Put/Call OI比=無法計算（call_oi=0）"
        )

        return EvidenceDraft(
            coin=coin,
            source="Binance Options /eapi/v1/mark（免 key，五幣統一來源；25Δ skew 用 API 直接回傳的 delta/markIV，非本地反推）",
            source_url=f"{EAPI_BASE}/mark",
            fetched_at=now_iso(),
            content_reference=(
                f"目標到期日 {target_expiry}（{days_to_expiry:.1f}天後）："
                f"ATM IV={atm_iv:.2f}%，Call 25Δ IV={call_25d_iv:.2f}%，Put 25Δ IV={put_25d_iv:.2f}%，"
                f"25Δ Skew={skew_25d:+.2f}%（正值＝put IV較高＝下跌避險溢價，偏空訊號）；{put_call_part}"
            ),
            related_claim=f"{coin} 選擇權隱含波動率結構（ATM IV／25Δ Skew／Put-Call OI 比）",
            source_type="derivatives",
        )

    # --- 7. CEX-DEX 費率差：Binance vs Hyperliquid 年化費率背離 ---
    async def _fetch_cex_dex_funding_diff(
        self, client: httpx.AsyncClient, coin: str, symbol: str
    ) -> EvidenceDraft | None:
        cex_resp = await client.get(f"{FAPI_BASE}/premiumIndex", params={"symbol": symbol})
        cex_resp.raise_for_status()
        cex_rate = float(cex_resp.json()["lastFundingRate"])

        hl_resp = await client.post(HYPERLIQUID_URL, json={"type": "metaAndAssetCtxs"})
        hl_resp.raise_for_status()
        meta, asset_ctxs = hl_resp.json()
        universe = meta["universe"]
        idx = next((i for i, u in enumerate(universe) if u["name"] == coin), None)
        if idx is None:
            self.log_subsource("cex_dex_funding_diff", coin, LogStatus.SKIPPED, "Hyperliquid universe 找不到該幣")
            return None
        dex_rate = float(asset_ctxs[idx]["funding"])

        cex_annualized = cex_rate * (HOURS_PER_YEAR / CEX_FUNDING_INTERVAL_HOURS) * 100
        dex_annualized = dex_rate * (HOURS_PER_YEAR / DEX_FUNDING_INTERVAL_HOURS) * 100
        diff = cex_annualized - dex_annualized
        if diff >= CEX_DEX_DIVERGENCE_THRESHOLD_PCT:
            label = "CEX 費率明顯較高（槓桿集中 CEX）"
        elif diff <= -CEX_DEX_DIVERGENCE_THRESHOLD_PCT:
            label = "DEX 費率明顯較高（槓桿集中 DEX）"
        else:
            label = "兩邊費率接近，無明顯場地背離"

        return EvidenceDraft(
            coin=coin,
            source="Binance /fapi/v1/premiumIndex（CEX）vs Hyperliquid metaAndAssetCtxs（DEX）",
            source_url=HYPERLIQUID_URL,
            fetched_at=now_iso(),
            content_reference=(
                f"CEX 年化費率 {cex_annualized:+.2f}%（8h期）vs DEX 年化費率 {dex_annualized:+.2f}%"
                f"（1h期，已依結算週期換算年化後比較）→ 差 {diff:+.2f}%（{label}）"
            ),
            related_claim=f"{coin} 中心化與去中心化交易場地的資金費率背離",
            source_type="derivatives",
        )

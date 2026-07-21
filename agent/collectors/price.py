"""價格資料 collector：主辦方 CSV（穩定基準）＋ CoinGecko 即時報價（備援 CryptoCompare）。

另外用純 Python（不靠外部 API、不靠 LLM）從官方 OHLCV CSV 計算技術指標
（SMA／RSI／波動率／量能趨勢），這類證據是決定性運算，不會因網路或
API 額度而失敗，是最穩定的一類 price evidence。
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

import httpx

from agent.collectors.base import BaseCollector
from agent.collectors.coin_map import get_coin_info
from agent.schemas import EvidenceDraft, LogStatus, now_iso

HTTP_TIMEOUT = 20.0
# MA120 需要至少 120 天收盤價才算得出來，抓 121 列留一天緩衝（見
# pipeline/流程紀錄.md 的落差記錄）。2026-07-21 由 Ken 直接指示先改，
# 尚未跟 alanchang 對過這個窗口常數，之後要補講一聲。
INDICATOR_WINDOW = 121
MA_WINDOWS = (20, 60, 120)


def load_ohlcv_tail(coin: str, data_dir: str, n: int = 14) -> list[dict]:
    path = Path(data_dir) / f"{coin}_daily_ohlcv.csv"
    if not path.exists():
        raise FileNotFoundError(f"找不到 OHLCV 資料檔: {path}")
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[-n:]


def summarize_ohlcv(rows: list[dict]) -> str:
    if not rows:
        return "無可用歷史資料"
    start, end = rows[0], rows[-1]
    start_close = float(start["close"])
    end_close = float(end["close"])
    pct_change = (end_close - start_close) / start_close * 100 if start_close else 0.0
    high = max(float(r["high"]) for r in rows)
    low = min(float(r["low"]) for r in rows)
    total_volume = sum(float(r["volume"]) for r in rows)
    return (
        f"期間 {start['date']} ~ {end['date']}（共 {len(rows)} 日）："
        f"收盤價 {start_close:.2f} → {end_close:.2f} USDT（{pct_change:+.2f}%），"
        f"期間最高 {high:.2f}／最低 {low:.2f}，總成交量約 {total_volume:.2f}"
    )


def compute_technical_indicators(rows: list[dict]) -> dict:
    """依最近 N 日 OHLCV 計算 SMA7/SMA14、RSI14、日報酬波動率、近 7 日量能趨勢。

    需要至少 15 筆資料才能算出一個 RSI14 數值；資料不足時回傳空 dict，
    呼叫端應視為「本次無法計算技術指標」而略過，不應拋例外。
    """
    closes = [float(r["close"]) for r in rows]
    volumes = [float(r["volume"]) for r in rows]
    if len(closes) < 15:
        return {}

    sma7 = sum(closes[-7:]) / 7
    sma14 = sum(closes[-14:]) / 14

    window = closes[-15:]
    diffs = [window[i + 1] - window[i] for i in range(14)]
    gains = [d for d in diffs if d > 0]
    losses = [-d for d in diffs if d < 0]
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    if avg_loss == 0:
        rsi14 = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi14 = 100 - (100 / (1 + rs))

    returns = [(window[i + 1] - window[i]) / window[i] for i in range(14) if window[i]]
    volatility_pct = statistics.pstdev(returns) * 100 if len(returns) >= 2 else 0.0

    if len(volumes) >= 14:
        recent_avg_vol = sum(volumes[-7:]) / 7
        prior_avg_vol = sum(volumes[-14:-7]) / 7
        volume_trend_pct = (
            (recent_avg_vol - prior_avg_vol) / prior_avg_vol * 100 if prior_avg_vol else 0.0
        )
    else:
        volume_trend_pct = 0.0

    result = {
        "sma7": sma7,
        "sma14": sma14,
        "rsi14": rsi14,
        "volatility_pct": volatility_pct,
        "volume_trend_pct": volume_trend_pct,
        "last_close": closes[-1],
    }

    # MA20/60/120 位置判讀：資料不足對應天數的窗口留 None（不是 0，避免誤讀）。
    for window_size in MA_WINDOWS:
        if len(closes) >= window_size:
            ma = sum(closes[-window_size:]) / window_size
            result[f"ma{window_size}"] = ma
            result[f"ma{window_size}_position"] = "站上" if closes[-1] >= ma else "跌破"
        else:
            result[f"ma{window_size}"] = None
            result[f"ma{window_size}_position"] = "資料不足"

    return result


def summarize_technical_indicators(indicators: dict) -> str:
    if not indicators:
        return "資料筆數不足，無法計算技術指標"
    trend = "站上" if indicators["last_close"] >= indicators["sma7"] else "跌破"
    rsi_zone = (
        "超買" if indicators["rsi14"] >= 70 else "超賣" if indicators["rsi14"] <= 30 else "中性"
    )
    ma_parts = []
    for window_size in MA_WINDOWS:
        val = indicators.get(f"ma{window_size}")
        pos = indicators.get(f"ma{window_size}_position", "資料不足")
        ma_parts.append(f"MA{window_size}={val:.2f}（{pos}）" if val is not None else f"MA{window_size}=資料不足")

    return (
        f"SMA7={indicators['sma7']:.2f}, SMA14={indicators['sma14']:.2f}"
        f"（現價{trend} SMA7）, RSI14={indicators['rsi14']:.1f}（{rsi_zone}區間）, "
        f"近14日日報酬波動率={indicators['volatility_pct']:.2f}%, "
        f"近7日量能較前7日變化={indicators['volume_trend_pct']:+.2f}%, "
        + "，".join(ma_parts)
    )


def compute_perp_basis(mark_price: float, index_price: float, funding_rate: float) -> dict:
    """依 Binance premiumIndex 回傳值算永續合約基差（mark 相對 index 的溢價比例）。"""
    basis_pct = (mark_price - index_price) / index_price * 100 if index_price else 0.0
    return {
        "mark_price": mark_price,
        "index_price": index_price,
        "basis_pct": basis_pct,
        "funding_rate_pct": funding_rate * 100,
    }


def summarize_perp_basis(basis: dict) -> str:
    direction = (
        "正基差 contango（多頭情緒佐證）"
        if basis["basis_pct"] >= 0
        else "負基差 backwardation（空頭情緒佐證）"
    )
    return (
        f"markPrice {basis['mark_price']:.4f} vs indexPrice {basis['index_price']:.4f}，"
        f"基差 {basis['basis_pct']:+.4f}%（{direction}），"
        f"最新資金費率 {basis['funding_rate_pct']:+.5f}%"
    )


class PriceCollector(BaseCollector):
    name = "price_collector"
    source_type = "price"

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        evidences: list[EvidenceDraft] = []
        info = get_coin_info(coin)
        data_dir = self.settings.data_dir if self.settings else "data"

        # --- 主要來源：主辦方提供之共同基準 OHLCV CSV（穩定，不受外部 API 影響）---
        try:
            indicator_rows = load_ohlcv_tail(coin, data_dir, n=INDICATOR_WINDOW)
            summary_rows = indicator_rows[-14:]
            evidences.append(
                EvidenceDraft(
                    coin=coin,
                    source=f"HOYA BIT 共同基準資料集 (data/{coin}_daily_ohlcv.csv)",
                    source_url=None,
                    fetched_at=now_iso(),
                    content_reference=summarize_ohlcv(summary_rows),
                    related_claim=f"{coin} 近兩週價格走勢與成交量變化",
                    source_type="price",
                )
            )

            # --- 技術指標：純 Python 決定性運算，不依賴任何外部 API，不會因網路/額度失敗 ---
            indicators = compute_technical_indicators(indicator_rows)
            if indicators:
                evidences.append(
                    EvidenceDraft(
                        coin=coin,
                        source=f"本地技術指標計算（依 data/{coin}_daily_ohlcv.csv 最近 {len(indicator_rows)} 日計算，非外部資料）",
                        source_url=None,
                        fetched_at=now_iso(),
                        content_reference=summarize_technical_indicators(indicators),
                        related_claim=f"{coin} 技術面動能指標（均線、RSI、波動率、量能趨勢）",
                        source_type="price",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            self.log_subsource("ohlcv_csv", coin, LogStatus.ERROR, f"error={exc}")

        # --- 即時報價：CoinGecko（免 key），失敗則退 CryptoCompare（免 key）---
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            try:
                resp = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={
                        "ids": info.coingecko_id,
                        "vs_currencies": "usd",
                        "include_24hr_change": "true",
                        "include_24hr_vol": "true",
                    },
                )
                resp.raise_for_status()
                data = resp.json()[info.coingecko_id]
                evidences.append(
                    EvidenceDraft(
                        coin=coin,
                        source="CoinGecko /simple/price",
                        source_url="https://api.coingecko.com/api/v3/simple/price",
                        fetched_at=now_iso(),
                        content_reference=(
                            f"query: ids={info.coingecko_id}&vs_currencies=usd | "
                            f"現價 {data.get('usd')} USD，24h 漲跌 {data.get('usd_24h_change', 0):.2f}%，"
                            f"24h 成交量 {data.get('usd_24h_vol', 0):.0f} USD"
                        ),
                        related_claim=f"{coin} 當前即時報價與 24 小時變化",
                        source_type="price",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.log_subsource("coingecko", coin, LogStatus.SKIPPED, f"error={exc}, fallback=cryptocompare")
                try:
                    resp = await client.get(
                        "https://min-api.cryptocompare.com/data/pricemultifull",
                        params={"fsyms": info.cryptocompare_symbol, "tsyms": "USD"},
                    )
                    resp.raise_for_status()
                    raw = resp.json()["RAW"][info.cryptocompare_symbol]["USD"]
                    evidences.append(
                        EvidenceDraft(
                            coin=coin,
                            source="CryptoCompare /data/pricemultifull（CoinGecko 備援）",
                            source_url="https://min-api.cryptocompare.com/data/pricemultifull",
                            fetched_at=now_iso(),
                            content_reference=(
                                f"query: fsyms={info.cryptocompare_symbol}&tsyms=USD | "
                                f"現價 {raw.get('PRICE')} USD，24h 漲跌 {raw.get('CHANGEPCT24HOUR', 0):.2f}%"
                            ),
                            related_claim=f"{coin} 當前即時報價與 24 小時變化",
                            source_type="price",
                        )
                    )
                except Exception as exc2:  # noqa: BLE001
                    self.log_subsource("cryptocompare", coin, LogStatus.ERROR, f"error={exc2}")

            # --- 永續基差：Binance Futures premiumIndex（免 key），mark/index 價差是多空情緒佐證 ---
            try:
                resp = await client.get(
                    "https://fapi.binance.com/fapi/v1/premiumIndex",
                    params={"symbol": f"{info.ticker}USDT"},
                )
                resp.raise_for_status()
                data = resp.json()
                basis = compute_perp_basis(
                    mark_price=float(data["markPrice"]),
                    index_price=float(data["indexPrice"]),
                    funding_rate=float(data["lastFundingRate"]),
                )
                evidences.append(
                    EvidenceDraft(
                        coin=coin,
                        source="Binance Futures /fapi/v1/premiumIndex",
                        source_url="https://fapi.binance.com/fapi/v1/premiumIndex",
                        fetched_at=now_iso(),
                        content_reference=(
                            f"query: symbol={info.ticker}USDT | " + summarize_perp_basis(basis)
                        ),
                        related_claim=f"{coin} 永續合約基差與資金費率（多空情緒佐證）",
                        source_type="price",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.log_subsource("perp_basis", coin, LogStatus.ERROR, f"error={exc}")

        return evidences

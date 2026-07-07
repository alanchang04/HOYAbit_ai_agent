"""價格資料 collector：主辦方 CSV（穩定基準）＋ CoinGecko 即時報價（備援 CryptoCompare）。"""

from __future__ import annotations

import csv
from pathlib import Path

import httpx

from agent.collectors.base import BaseCollector
from agent.collectors.coin_map import get_coin_info
from agent.schemas import EvidenceDraft, LogStatus, now_iso

HTTP_TIMEOUT = 20.0


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


class PriceCollector(BaseCollector):
    name = "price_collector"
    source_type = "price"

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        evidences: list[EvidenceDraft] = []
        info = get_coin_info(coin)
        data_dir = self.settings.data_dir if self.settings else "data"

        # --- 主要來源：主辦方提供之共同基準 OHLCV CSV（穩定，不受外部 API 影響）---
        try:
            rows = load_ohlcv_tail(coin, data_dir, n=14)
            evidences.append(
                EvidenceDraft(
                    source=f"HOYA BIT 共同基準資料集 (data/{coin}_daily_ohlcv.csv)",
                    source_url=None,
                    fetched_at=now_iso(),
                    content_reference=summarize_ohlcv(rows),
                    related_claim=f"{coin} 近兩週價格走勢與成交量變化",
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

        return evidences

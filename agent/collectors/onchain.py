"""鏈上資料 collector：依幣種所屬鏈路由至對應公開端點（皆為免 key 公開 RPC/API）。

若使用者提供 Etherscan / BscScan 免費 key，會額外疊加一筆補充證據；
沒有 key 時不影響主要（免 key）鏈上證據的取得。
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import httpx

from agent.collectors.base import BaseCollector
from agent.collectors.coin_map import get_coin_info
from agent.collectors.horizon import window_back
from agent.schemas import EvidenceDraft, HorizonClass, LogStatus, now_iso

HTTP_TIMEOUT = 20.0

# 併自 pipeline/fetch_onchain_history.py：只有 BTC/ETH 找到免 key 的免費歷史
# 來源，SOL/BNB/XRP 仍是開放缺口（見 pipeline/待辦筆記/onchain_歷史資料.md）。
HISTORY_TREND_DAYS = 30
BTC_HISTORY_CHARTS: dict[str, tuple[str, str]] = {
    "算力": ("hash-rate", "TH/s"),
    "24h交易筆數": ("n-transactions", "筆"),
    "Mempool待確認筆數": ("mempool-count", "筆"),
    "Mempool大小": ("mempool-size", "bytes"),
}


async def _evm_rpc_call(client: httpx.AsyncClient, rpc_url: str, method: str, params: list | None = None):
    resp = await client.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []},
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data["result"]


async def _fetch_blockchain_info_chart(client: httpx.AsyncClient, chart_name: str) -> list[tuple[str, float]]:
    """打 blockchain.info charts API（免 key），回傳依日期排序的 (date, value) 序列。"""
    resp = await client.get(
        f"https://api.blockchain.info/charts/{chart_name}",
        params={"timespan": "5years", "format": "json", "cors": "true"},
    )
    resp.raise_for_status()
    return sorted(
        (datetime.fromtimestamp(point["x"], tz=timezone.utc).strftime("%Y-%m-%d"), point["y"])
        for point in resp.json()["values"]
    )


def _history_trend(series: list[tuple[str, float]], days: int = HISTORY_TREND_DAYS) -> tuple[str, float, float] | None:
    """回傳 (最新日期, 最新值, 對比 days 天前的變化百分比)；資料不足 days+1 筆時回傳
    None，呼叫端應顯示「資料不足」而不是硬湊。"""
    if len(series) < days + 1:
        return None
    latest_date, latest_val = series[-1]
    _, past_val = series[-(days + 1)]
    pct = (latest_val - past_val) / past_val * 100 if past_val else 0.0
    return latest_date, latest_val, pct


class OnchainCollector(BaseCollector):
    name = "onchain_collector"
    source_type = "onchain"

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        info = get_coin_info(coin)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            if info.chain == "bitcoin":
                return await self._fetch_bitcoin(client, coin)
            if info.chain == "evm":
                evidences = await self._fetch_evm(
                    client,
                    coin,
                    ["https://ethereum-rpc.publicnode.com", "https://cloudflare-eth.com"],
                    etherscan_url="https://api.etherscan.io/api",
                    api_key=getattr(self.settings, "etherscan_api_key", None),
                )
                if coin == "ETH":
                    evidences.extend(await self._fetch_eth_gas_history(client, coin))
                return evidences
            if info.chain == "bnb_chain":
                return await self._fetch_evm(
                    client,
                    coin,
                    ["https://bsc-dataseed.binance.org", "https://bsc-rpc.publicnode.com"],
                    etherscan_url="https://api.bscscan.com/api",
                    api_key=getattr(self.settings, "bscscan_api_key", None),
                )
            if info.chain == "solana":
                return await self._fetch_solana(client, coin)
            if info.chain == "xrpl":
                return await self._fetch_xrpl(client, coin)
        return []

    async def _fetch_bitcoin(self, client: httpx.AsyncClient, coin: str) -> list[EvidenceDraft]:
        evidences: list[EvidenceDraft] = []
        try:
            resp = await client.get("https://api.blockchair.com/bitcoin/stats")
            resp.raise_for_status()
            data = resp.json()["data"]
            evidences.append(
                EvidenceDraft(
                    coin=coin,
                    source="Blockchair /bitcoin/stats",
                    source_url="https://api.blockchair.com/bitcoin/stats",
                    fetched_at=now_iso(),
                    content_reference=(
                        f"blocks={data.get('blocks')}, mempool_tx_count={data.get('mempool_transactions')}, "
                        f"24h_tx_count={data.get('transactions_24h')}, hashrate_24h={data.get('hashrate_24h')}"
                    ),
                    related_claim=f"{coin} 鏈上活躍度（交易量、mempool、算力）",
                    source_type="onchain",
                    horizon_class=HorizonClass.SPOT,
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.log_subsource("blockchair", coin, LogStatus.ERROR, f"error={exc}")

        # 併自 pipeline/fetch_onchain_history.py：快照只有「當下一個時間點」，這裡
        # 補一筆近 5 年歷史序列的近 30 天趨勢，回答「現在算力/交易量是在漲還是跌」。
        try:
            history_window_start, history_window_end = window_back(HISTORY_TREND_DAYS)
            history_parts = []
            for label, (chart_name, unit) in BTC_HISTORY_CHARTS.items():
                series = await _fetch_blockchain_info_chart(client, chart_name)
                trend = _history_trend(series)
                if trend:
                    _, latest_val, pct = trend
                    history_parts.append(f"{label}={latest_val:.2f}{unit}（近{HISTORY_TREND_DAYS}天{pct:+.2f}%）")
                else:
                    history_parts.append(f"{label}=資料不足")
            evidences.append(
                EvidenceDraft(
                    coin=coin,
                    source="blockchain.info Charts API（近5年歷史序列，取近30天趨勢）",
                    source_url="https://api.blockchain.info/charts/hash-rate",
                    fetched_at=now_iso(),
                    content_reference="；".join(history_parts),
                    related_claim=f"{coin} 鏈上活躍度近期趨勢（算力／交易量／mempool 積壓，非單點快照）",
                    source_type="onchain",
                    # 原始序列雖有 5 年，但實際判讀只取 HISTORY_TREND_DAYS=30 天的趨勢，
                    # 標註依「實際使用的窗口」而非「拉回來的資料長度」。
                    window_start=history_window_start,
                    window_end=history_window_end,
                    horizon_class=HorizonClass.MEDIUM,
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.log_subsource("blockchain_info_history", coin, LogStatus.ERROR, f"error={exc}")

        return evidences

    async def _fetch_evm(
        self, client: httpx.AsyncClient, coin: str, rpc_urls: list[str], etherscan_url: str, api_key: str | None
    ) -> list[EvidenceDraft]:
        evidences: list[EvidenceDraft] = []
        last_exc: Exception | None = None
        for rpc_url in rpc_urls:
            try:
                block_hex = await _evm_rpc_call(client, rpc_url, "eth_blockNumber")
                gas_hex = await _evm_rpc_call(client, rpc_url, "eth_gasPrice")
                block_number = int(block_hex, 16)
                gas_price_gwei = int(gas_hex, 16) / 1e9
                evidences.append(
                    EvidenceDraft(
                        coin=coin,
                        source=f"公開 EVM RPC ({rpc_url})",
                        source_url=rpc_url,
                        fetched_at=now_iso(),
                        content_reference=f"method=eth_blockNumber,eth_gasPrice | 最新區塊 {block_number}，Gas Price {gas_price_gwei:.2f} Gwei",
                        related_claim=f"{coin} 鏈上網路即時活動（區塊高度、Gas 費用）",
                        source_type="onchain",
                        horizon_class=HorizonClass.SPOT,
                    )
                )
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue
        if last_exc is not None:
            self.log_subsource("evm_rpc", coin, LogStatus.ERROR, f"error={last_exc}, tried={rpc_urls}")

        if api_key:
            try:
                resp = await client.get(
                    etherscan_url,
                    params={"module": "stats", "action": "ethsupply" if "etherscan" in etherscan_url else "bnbsupply", "apikey": api_key},
                )
                resp.raise_for_status()
                data = resp.json()
                evidences.append(
                    EvidenceDraft(
                        coin=coin,
                        source=f"{'Etherscan' if 'etherscan' in etherscan_url else 'BscScan'} /api?module=stats",
                        source_url=etherscan_url,
                        fetched_at=now_iso(),
                        content_reference=f"result={data.get('result')}",
                        related_claim=f"{coin} 鏈上總供給量（補充資料）",
                        source_type="onchain",
                        horizon_class=HorizonClass.SPOT,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.log_subsource("scan_api", coin, LogStatus.SKIPPED, f"error={exc}")

        return evidences

    async def _fetch_eth_gas_history(self, client: httpx.AsyncClient, coin: str) -> list[EvidenceDraft]:
        """併自 pipeline/fetch_onchain_history.py：ETH 唯一免 key 的免費歷史來源
        是 etherscan.io 的 gas price CSV 匯出端點（回溯到 2015 年），只對 ETH 抓，
        BNB 走同一個 `_fetch_evm()` 但沒有等價的免費歷史來源，不觸發這段。"""
        try:
            resp = await client.get(
                "https://etherscan.io/chart/gasprice",
                params={"output": "csv"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            series: list[tuple[str, float]] = sorted(
                (
                    datetime.strptime(row["Date(UTC)"], "%m/%d/%Y").strftime("%Y-%m-%d"),
                    float(row["Value (Wei)"]) / 1e9,
                )
                for row in csv.DictReader(io.StringIO(resp.text))
            )
            trend = _history_trend(series)
            if trend is None:
                self.log_subsource("etherscan_gas_history", coin, LogStatus.SKIPPED, f"insufficient_history={len(series)}")
                return []
            _, latest_val, pct = trend
            return [
                EvidenceDraft(
                    coin=coin,
                    source="Etherscan Gas Price 歷史 CSV（etherscan.io/chart/gasprice）",
                    source_url="https://etherscan.io/chart/gasprice",
                    fetched_at=now_iso(),
                    content_reference=(
                        f"Gas Price={latest_val:.2f} Gwei（近{HISTORY_TREND_DAYS}天{pct:+.2f}%，"
                        f"樣本回溯至{series[0][0]}）"
                    ),
                    related_claim=f"{coin} 鏈上網路壅塞程度近期趨勢（Gas 費用歷史走勢，非單點快照）",
                    source_type="onchain",
                    # 同 blockchain.info 歷史趨勢：CSV 回溯很長但實際判讀窗是
                    # HISTORY_TREND_DAYS=30 天，依實際使用的窗口標註。
                    window_start=window_back(HISTORY_TREND_DAYS)[0],
                    window_end=window_back(HISTORY_TREND_DAYS)[1],
                    horizon_class=HorizonClass.MEDIUM,
                )
            ]
        except Exception as exc:  # noqa: BLE001
            self.log_subsource("etherscan_gas_history", coin, LogStatus.ERROR, f"error={exc}")
            return []

    async def _fetch_solana(self, client: httpx.AsyncClient, coin: str) -> list[EvidenceDraft]:
        try:
            resp = await client.post(
                "https://api.mainnet-beta.solana.com",
                json={"jsonrpc": "2.0", "id": 1, "method": "getRecentPerformanceSamples", "params": [5]},
            )
            resp.raise_for_status()
            samples = resp.json()["result"]
            avg_tps = sum(s["numTransactions"] / s["samplePeriodSecs"] for s in samples) / len(samples) if samples else 0
            return [
                EvidenceDraft(
                    coin=coin,
                    source="Solana 公開 RPC getRecentPerformanceSamples",
                    source_url="https://api.mainnet-beta.solana.com",
                    fetched_at=now_iso(),
                    content_reference=f"method=getRecentPerformanceSamples,limit=5 | 近期平均 TPS 約 {avg_tps:.1f}",
                    related_claim=f"{coin} 鏈上網路即時活躍度（TPS）",
                    source_type="onchain",
                    horizon_class=HorizonClass.SPOT,
                )
            ]
        except Exception as exc:  # noqa: BLE001
            self.log_subsource("solana_rpc", coin, LogStatus.ERROR, f"error={exc}")
            return []

    async def _fetch_xrpl(self, client: httpx.AsyncClient, coin: str) -> list[EvidenceDraft]:
        rpc_urls = ["https://xrplcluster.com", "https://s1.ripple.com:51234"]
        last_exc: Exception | None = None
        for rpc_url in rpc_urls:
            try:
                resp = await client.post(rpc_url, json={"method": "server_info", "params": [{}]})
                resp.raise_for_status()
                info = resp.json()["result"]["info"]
                validated = info.get("validated_ledger", {})
                return [
                    EvidenceDraft(
                        coin=coin,
                        source=f"XRPL 公開 JSON-RPC ({rpc_url})",
                        source_url=rpc_url,
                        fetched_at=now_iso(),
                        content_reference=(
                            f"method=server_info | validated_ledger_seq={validated.get('seq')}, "
                            f"load_factor={info.get('load_factor')}, base_fee_xrp={validated.get('base_fee_xrp')}"
                        ),
                        related_claim=f"{coin} XRPL 網路狀態（帳本高度、費率負載）",
                        source_type="onchain",
                        horizon_class=HorizonClass.SPOT,
                    )
                ]
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue
        self.log_subsource("xrpl_rpc", coin, LogStatus.ERROR, f"error={last_exc}, tried={rpc_urls}")
        return []

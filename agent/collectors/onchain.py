"""鏈上資料 collector：依幣種所屬鏈路由至對應公開端點（皆為免 key 公開 RPC/API）。

若使用者提供 Etherscan / BscScan 免費 key，會額外疊加一筆補充證據；
沒有 key 時不影響主要（免 key）鏈上證據的取得。
"""

from __future__ import annotations

import httpx

from agent.collectors.base import BaseCollector
from agent.collectors.coin_map import get_coin_info
from agent.schemas import EvidenceDraft, LogStatus, now_iso

HTTP_TIMEOUT = 20.0


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


class OnchainCollector(BaseCollector):
    name = "onchain_collector"
    source_type = "onchain"

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        info = get_coin_info(coin)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            if info.chain == "bitcoin":
                return await self._fetch_bitcoin(client, coin)
            if info.chain == "evm":
                return await self._fetch_evm(
                    client,
                    coin,
                    ["https://ethereum-rpc.publicnode.com", "https://cloudflare-eth.com"],
                    etherscan_url="https://api.etherscan.io/api",
                    api_key=getattr(self.settings, "etherscan_api_key", None),
                )
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
        try:
            resp = await client.get("https://api.blockchair.com/bitcoin/stats")
            resp.raise_for_status()
            data = resp.json()["data"]
            return [
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
                )
            ]
        except Exception as exc:  # noqa: BLE001
            self.log_subsource("blockchair", coin, LogStatus.ERROR, f"error={exc}")
            return []

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
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.log_subsource("scan_api", coin, LogStatus.SKIPPED, f"error={exc}")

        return evidences

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
                    )
                ]
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue
        self.log_subsource("xrpl_rpc", coin, LogStatus.ERROR, f"error={last_exc}, tried={rpc_urls}")
        return []

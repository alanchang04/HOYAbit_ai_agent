"""Onchain 方向：五幣各自的鏈上快照（對照 02改_資料網格.html 的「Onchain 鏈上」色塊）。

跟 `agent/collectors/onchain.py` 的正式實作邏輯大致一致（免 key 公開 RPC/API
為主，Etherscan 為有 key 才疊加的補充來源），這裡是 Ken 自己驗證用的
prototype，抓完直接落地存進 raw_data/onchain/{COIN}/onchain_snapshot.json。

⚠️ 跟正式 collector 有落差：BscScan 訂閱已併入 Etherscan API V2（單一
ETHERSCAN_API_KEY 用 chainid 參數切鏈，1=Ethereum、56=BSC），這裡已改用統一
V2 端點；正式 `onchain.py` 的 `_fetch_evm()` 還是打舊版 `api.bscscan.com`、
分開吃 ETHERSCAN_API_KEY / BSCSCAN_API_KEY，併回正式程式碼前要跟 alanchang
講一聲一起改掉。另外免費方案的 Etherscan key 目前只涵蓋 Ethereum 一條鏈，
BSC（chainid=56）會回 "Free API access is not supported for this chain"，
所以 BNB 的供給量補充證據即使有 key 一樣是 skipped，除非升級付費方案。

跟即時報價一樣，onchain 這幾個欄位本質是「當下一個時間點」的快照，沒有歷史
序列版本，每次跑都會覆蓋掉上一次的結果。

用法：
    python pipeline/fetch_onchain.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "onchain"
HTTP_TIMEOUT = 20.0


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _evm_rpc_call(client: httpx.Client, rpc_url: str, method: str, params: list | None = None):
    resp = client.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []})
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data["result"]


def fetch_btc(client: httpx.Client) -> dict:
    resp = client.get("https://api.blockchair.com/bitcoin/stats")
    resp.raise_for_status()
    data = resp.json()["data"]
    return {
        "source": "Blockchair /bitcoin/stats",
        "blocks": data.get("blocks"),
        "mempool_tx_count": data.get("mempool_transactions"),
        "tx_count_24h": data.get("transactions_24h"),
        "hashrate_24h": data.get("hashrate_24h"),
        "fetched_at": now_iso(),
    }


ETHERSCAN_V2_URL = "https://api.etherscan.io/v2/api"


def fetch_evm(client: httpx.Client, rpc_urls: list[str], chainid: int, scan_action: str, api_key: str | None) -> dict:
    last_exc: Exception | None = None
    result: dict = {}
    for rpc_url in rpc_urls:
        try:
            block_hex = _evm_rpc_call(client, rpc_url, "eth_blockNumber")
            gas_hex = _evm_rpc_call(client, rpc_url, "eth_gasPrice")
            result = {
                "source": f"公開 EVM RPC ({rpc_url})",
                "block_number": int(block_hex, 16),
                "gas_price_gwei": int(gas_hex, 16) / 1e9,
                "fetched_at": now_iso(),
            }
            last_exc = None
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc

    # Etherscan API V2（統一端點，BscScan 訂閱已併入，同一把 ETHERSCAN_API_KEY
    # 用 chainid 切鏈：1=Ethereum、56=BSC。免費方案目前只涵蓋 Ethereum，其他鏈
    # 會回 200 但 status="0"，不算例外，視為 skipped。）
    if api_key:
        try:
            resp = client.get(
                ETHERSCAN_V2_URL,
                params={"chainid": chainid, "module": "stats", "action": scan_action, "apikey": api_key},
            )
            resp.raise_for_status()
            scan_data = resp.json()
            if scan_data.get("status") == "1":
                result["supply_supplement"] = {"source": f"{ETHERSCAN_V2_URL}?chainid={chainid}", "result": scan_data.get("result")}
            else:
                result["supply_supplement"] = {
                    "source": f"{ETHERSCAN_V2_URL}?chainid={chainid}",
                    "skipped": f"API 回應：{scan_data.get('result')}",
                }
        except Exception as exc:  # noqa: BLE001
            result["supply_supplement"] = {"skipped": f"error={exc}"}
    else:
        result["supply_supplement"] = {"skipped": "沒有設定 ETHERSCAN_API_KEY，略過（不影響主要免 key 資料）"}

    return result


def fetch_sol(client: httpx.Client) -> dict:
    resp = client.post(
        "https://api.mainnet-beta.solana.com",
        json={"jsonrpc": "2.0", "id": 1, "method": "getRecentPerformanceSamples", "params": [5]},
    )
    resp.raise_for_status()
    samples = resp.json()["result"]
    avg_tps = sum(s["numTransactions"] / s["samplePeriodSecs"] for s in samples) / len(samples) if samples else 0
    return {
        "source": "Solana 公開 RPC getRecentPerformanceSamples",
        "avg_tps": avg_tps,
        "sample_count": len(samples),
        "fetched_at": now_iso(),
    }


def fetch_xrp(client: httpx.Client) -> dict:
    rpc_urls = ["https://xrplcluster.com", "https://s1.ripple.com:51234"]
    last_exc: Exception | None = None
    for rpc_url in rpc_urls:
        try:
            resp = client.post(rpc_url, json={"method": "server_info", "params": [{}]})
            resp.raise_for_status()
            info = resp.json()["result"]["info"]
            validated = info.get("validated_ledger", {})
            return {
                "source": f"XRPL 公開 JSON-RPC ({rpc_url})",
                "ledger_seq": validated.get("seq"),
                "load_factor": info.get("load_factor"),
                "base_fee_xrp": validated.get("base_fee_xrp"),
                "fetched_at": now_iso(),
            }
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue
    raise last_exc  # type: ignore[misc]


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "onchain_snapshot.json"
    out_path.write_text(json.dumps({"coin": coin, **result}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        etherscan_key = os.getenv("ETHERSCAN_API_KEY") or None
        fetchers = {
            "BTC": lambda: fetch_btc(client),
            "ETH": lambda: fetch_evm(
                client,
                ["https://ethereum-rpc.publicnode.com", "https://cloudflare-eth.com"],
                1,
                "ethsupply",
                etherscan_key,
            ),
            "SOL": lambda: fetch_sol(client),
            "BNB": lambda: fetch_evm(
                client,
                ["https://bsc-dataseed.binance.org", "https://bsc-rpc.publicnode.com"],
                56,
                "bnbsupply",
                etherscan_key,
            ),
            "XRP": lambda: fetch_xrp(client),
        }
        for coin, fetcher in fetchers.items():
            try:
                result = fetcher()
            except Exception as exc:  # noqa: BLE001
                print(f"[{coin}] 抓取失敗：{exc}")
                continue
            out_path = write_output(coin, result)
            print(f"[{coin}] 已寫入 {out_path}")
            for key, value in result.items():
                if key not in ("source", "fetched_at"):
                    print(f"  {key}: {value}")
            print()


if __name__ == "__main__":
    main()

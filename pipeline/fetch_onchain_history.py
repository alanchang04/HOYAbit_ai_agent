"""Onchain 歷史序列 collector prototype：目前只有 BTC/ETH 找到免 key 的免費歷史
來源（見 `pipeline/待辦筆記/onchain_歷史資料.md`），SOL/BNB/XRP 仍卡住——沒有
免費歷史序列來源，等之後找到才補。

跟 `fetch_onchain.py` 的差別：那支抓的是「當下一個時間點」快照，這支抓的是
完整每日歷史序列，寫成 CSV（每天一列，比照 `raw_data/price/{COIN}/` 底下
序列檔案的作法，跟單點快照 json 不同）。

BTC：blockchain.info 免費 charts API，四條免 key 圖表——hash-rate／
n-transactions（24h 交易筆數）近 5 年；mempool-count／mempool-size 只有近 4 年
（來源本身資料起點較晚，不是抓取邏輯的問題）。
ETH：etherscan.io/chart/gasprice 免 key 公開 CSV 匯出端點，回溯到 2015 年。

用法：
    python pipeline/fetch_onchain_history.py
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path

import httpx

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "onchain"
HTTP_TIMEOUT = 30.0

BTC_CHARTS = {
    "hash_rate_ths": "hash-rate",
    "tx_count_24h": "n-transactions",
    "mempool_count": "mempool-count",
    "mempool_size_bytes": "mempool-size",
}


def fetch_btc_history(client: httpx.Client) -> dict[str, dict[str, float]]:
    """逐圖表打 blockchain.info charts API，依日期合併成 {date: {field: value}}。"""
    merged: dict[str, dict[str, float]] = {}
    for field, chart_name in BTC_CHARTS.items():
        resp = client.get(
            f"https://api.blockchain.info/charts/{chart_name}",
            params={"timespan": "5years", "format": "json", "cors": "true"},
        )
        resp.raise_for_status()
        for point in resp.json()["values"]:
            date_str = datetime.fromtimestamp(point["x"], tz=timezone.utc).strftime("%Y-%m-%d")
            merged.setdefault(date_str, {})[field] = point["y"]
    return merged


def write_btc_csv(merged: dict[str, dict[str, float]]) -> Path:
    out_path = RAW_DATA_DIR / "BTC" / "onchain_history_daily.csv"
    fields = list(BTC_CHARTS.keys())
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", *fields])
        for date_str in sorted(merged):
            row = merged[date_str]
            writer.writerow([date_str, *[row.get(field, "") for field in fields]])
    return out_path


def fetch_eth_history(client: httpx.Client) -> list[tuple[str, float]]:
    """打 etherscan gasprice csv 匯出端點，回傳 [(date, gas_price_gwei), ...]。"""
    resp = client.get(
        "https://etherscan.io/chart/gasprice",
        params={"output": "csv"},
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    rows = []
    for row in reader:
        date_obj = datetime.strptime(row["Date(UTC)"], "%m/%d/%Y")
        gas_price_gwei = float(row["Value (Wei)"]) / 1e9
        rows.append((date_obj.strftime("%Y-%m-%d"), gas_price_gwei))
    return rows


def write_eth_csv(rows: list[tuple[str, float]]) -> Path:
    out_path = RAW_DATA_DIR / "ETH" / "onchain_history_daily.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "gas_price_gwei"])
        writer.writerows(rows)
    return out_path


def main() -> None:
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        print("[BTC] 抓取歷史序列（hash-rate／n-transactions／mempool-count／mempool-size）...")
        btc_merged = fetch_btc_history(client)
        btc_path = write_btc_csv(btc_merged)
        print(f"[BTC] 已寫入 {btc_path}（{len(btc_merged)} 天）")

        print("[ETH] 抓取歷史序列（gas price）...")
        eth_rows = fetch_eth_history(client)
        eth_path = write_eth_csv(eth_rows)
        print(f"[ETH] 已寫入 {eth_path}（{len(eth_rows)} 天）")


if __name__ == "__main__":
    main()

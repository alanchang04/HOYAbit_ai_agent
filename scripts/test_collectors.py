"""Stage 2 驗證腳本：直接執行五類真實 collector（不經過推理/報告），
用於實測真實 API 連線效果、備援是否正常啟動，以及各 collector 耗時。

使用方式：
    python scripts/test_collectors.py --coin BTC
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.collectors.macro import MacroCollector
from agent.collectors.news import NewsCollector
from agent.collectors.onchain import OnchainCollector
from agent.collectors.price import PriceCollector
from agent.collectors.social import SocialCollector
from agent.config import get_settings
from agent.logging_utils import ExecutionLogger

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


async def run(coin: str) -> None:
    settings = get_settings()
    logger = ExecutionLogger("output/test_collectors_execution_log.jsonl")
    collectors = [
        PriceCollector(logger, timeout_seconds=settings.collector_timeout_seconds, settings=settings),
        OnchainCollector(logger, timeout_seconds=settings.collector_timeout_seconds, settings=settings),
        NewsCollector(logger, timeout_seconds=settings.collector_timeout_seconds, settings=settings),
        SocialCollector(logger, timeout_seconds=settings.collector_timeout_seconds, settings=settings),
        MacroCollector(logger, timeout_seconds=settings.collector_timeout_seconds, settings=settings),
    ]

    start = time.monotonic()
    results = await asyncio.gather(*[c.run(coin) for c in collectors])
    elapsed = time.monotonic() - start

    for collector, evidences in zip(collectors, results):
        print(f"\n== {collector.name} ({len(evidences)} 筆證據) ==")
        for ev in evidences:
            print(f"  - [{ev.source_type.value}] {ev.source} | {ev.content_reference[:150]}")

    print(f"\n總耗時：{elapsed:.2f} 秒")
    print("詳細成功/失敗紀錄請見 output/test_collectors_execution_log.jsonl")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--coin", default="BTC")
    args = parser.parse_args()
    asyncio.run(run(args.coin.upper()))

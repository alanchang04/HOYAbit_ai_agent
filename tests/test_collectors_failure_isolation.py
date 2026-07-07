import asyncio

import pytest

from agent.collectors.base import BaseCollector
from agent.collectors.dry_run import DryRunCollector
from agent.logging_utils import ExecutionLogger
from agent.schemas import EvidenceDraft, LogStatus, now_iso


class RaisingCollector(BaseCollector):
    name = "raising_collector"
    source_type = "news"

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        raise ValueError("simulated upstream failure")


class HangingCollector(BaseCollector):
    name = "hanging_collector"
    source_type = "social"

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        await asyncio.sleep(10)
        return []


def test_raising_collector_is_isolated(tmp_path):
    logger = ExecutionLogger(tmp_path / "execution_log.jsonl")
    collector = RaisingCollector(logger)

    result = asyncio.run(collector.run("BTC"))

    assert result == []
    entries = logger.read_all()
    assert any(e.status == LogStatus.ERROR and e.action == "raising_collector" for e in entries)


def test_hanging_collector_times_out(tmp_path):
    logger = ExecutionLogger(tmp_path / "execution_log.jsonl")
    collector = HangingCollector(logger, timeout_seconds=1)

    result = asyncio.run(collector.run("BTC"))

    assert result == []
    entries = logger.read_all()
    assert any(e.status == LogStatus.SKIPPED and e.action == "hanging_collector" for e in entries)


def test_single_failure_does_not_block_other_collectors(tmp_path):
    """單一 collector 失敗/超時不應影響其他 collector 的平行執行結果。"""
    logger = ExecutionLogger(tmp_path / "execution_log.jsonl")
    good_collector = DryRunCollector("price", logger)
    bad_collector = RaisingCollector(logger)
    hanging_collector = HangingCollector(logger, timeout_seconds=1)

    async def run_all():
        return await asyncio.gather(
            good_collector.run("BTC"),
            bad_collector.run("BTC"),
            hanging_collector.run("BTC"),
        )

    good_result, bad_result, hanging_result = asyncio.run(run_all())

    assert len(good_result) > 0
    assert bad_result == []
    assert hanging_result == []

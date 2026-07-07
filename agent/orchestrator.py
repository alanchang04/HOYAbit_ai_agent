"""Orchestrator：Phase 1（蒐集）→ Phase 2（證據化）→ Phase 3（推理）→ Phase 4（報告生成）。

負責 15 分鐘硬性 deadline 與 degraded mode（超過
`degraded_mode_trigger_seconds` 後跳過剩餘蒐集、直接進入推理）。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

from agent.collectors.base import BaseCollector
from agent.collectors.dry_run import DryRunCollector
from agent.collectors.macro import MacroCollector
from agent.collectors.news import NewsCollector
from agent.collectors.onchain import OnchainCollector
from agent.collectors.price import PriceCollector
from agent.collectors.social import SocialCollector
from agent.config import Settings, check_optional_keys, get_settings
from agent.logging_utils import ExecutionLogger
from agent.reasoning.bedrock_client import BedrockClient
from agent.reasoning.pipeline import ReasoningResult, run_reasoning
from agent.report.builder import build_report_markdown
from agent.schemas import Evidence, EvidenceDraft, LogPhase, LogStatus

SOURCE_TYPES = ["price", "onchain", "news", "social", "macro"]


@dataclass
class RunResult:
    report_markdown: str
    evidences: list[Evidence]
    reasoning: ReasoningResult
    degraded_mode: bool
    elapsed_seconds: float


def build_collectors(logger: ExecutionLogger, settings: Settings, dry_run: bool) -> list[BaseCollector]:
    if dry_run:
        return [
            DryRunCollector(source_type, logger, timeout_seconds=settings.collector_timeout_seconds)
            for source_type in SOURCE_TYPES
        ]
    return [
        PriceCollector(logger, timeout_seconds=settings.collector_timeout_seconds, settings=settings),
        OnchainCollector(logger, timeout_seconds=settings.collector_timeout_seconds, settings=settings),
        NewsCollector(logger, timeout_seconds=settings.collector_timeout_seconds, settings=settings),
        SocialCollector(logger, timeout_seconds=settings.collector_timeout_seconds, settings=settings),
        MacroCollector(logger, timeout_seconds=settings.collector_timeout_seconds, settings=settings),
    ]


async def collect_all(
    collectors: list[BaseCollector], coin: str, remaining_seconds: float
) -> list[EvidenceDraft]:
    if remaining_seconds <= 0:
        return []
    tasks = [c.run(coin) for c in collectors]
    results = await asyncio.gather(*tasks)
    drafts: list[EvidenceDraft] = []
    for r in results:
        drafts.extend(r)
    return drafts


def assign_evidence_ids(drafts: list[EvidenceDraft]) -> list[Evidence]:
    evidences = []
    for i, draft in enumerate(drafts, start=1):
        evidences.append(Evidence(id=f"ev-{i:03d}", **draft.model_dump()))
    return evidences


def run_pipeline(
    coin: str,
    question: str,
    dry_run: bool = True,
    output_dir: str | None = None,
) -> RunResult:
    settings = get_settings()
    start_time = time.monotonic()

    out_dir = Path(output_dir or settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger = ExecutionLogger(out_dir / "execution_log.jsonl")

    for warning in check_optional_keys():
        logger.log(phase=LogPhase.COLLECT, action="config_check", detail=warning, status=LogStatus.SKIPPED)

    logger.log(
        phase=LogPhase.COLLECT,
        action="pipeline_start",
        detail=f"coin={coin}, question={question!r}, dry_run={dry_run}",
        status=LogStatus.OK,
    )

    collectors = build_collectors(logger, settings, dry_run)

    elapsed = time.monotonic() - start_time
    remaining_before_collect = settings.hard_deadline_seconds - elapsed
    degraded_mode = elapsed > settings.degraded_mode_trigger_seconds

    if degraded_mode:
        logger.log(
            phase=LogPhase.COLLECT,
            action="degraded_mode",
            detail="已超過 degraded_mode_trigger_seconds，跳過剩餘資料蒐集，直接進入推理",
            status=LogStatus.SKIPPED,
        )
        drafts: list[EvidenceDraft] = []
    else:
        drafts = asyncio.run(collect_all(collectors, coin, remaining_before_collect))

    evidences = assign_evidence_ids(drafts)

    evidence_path = out_dir / "evidence.json"
    evidence_path.write_text(
        json.dumps([e.model_dump() for e in evidences], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.log(
        phase=LogPhase.COLLECT,
        action="evidence_written",
        detail=f"count={len(evidences)}, path={evidence_path}",
        status=LogStatus.OK,
    )

    bedrock_client = None if dry_run else BedrockClient(settings)
    reasoning_result = run_reasoning(coin, question, evidences, dry_run=dry_run, bedrock_client=bedrock_client)
    logger.log(
        phase=LogPhase.REASON,
        action="reasoning_complete",
        detail=f"question_type={reasoning_result.question_type}",
        status=LogStatus.OK,
    )

    report_md = build_report_markdown(coin, question, reasoning_result, evidences)
    report_path = out_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")
    logger.log(phase=LogPhase.REPORT, action="report_written", detail=str(report_path), status=LogStatus.OK)

    total_elapsed = time.monotonic() - start_time
    logger.log(
        phase=LogPhase.REPORT,
        action="pipeline_end",
        detail=f"elapsed_seconds={total_elapsed:.2f}",
        status=LogStatus.OK,
    )

    return RunResult(
        report_markdown=report_md,
        evidences=evidences,
        reasoning=reasoning_result,
        degraded_mode=degraded_mode,
        elapsed_seconds=total_elapsed,
    )

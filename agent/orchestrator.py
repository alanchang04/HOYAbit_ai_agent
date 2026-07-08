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
from agent.collectors.coin_map import detect_coins_in_text
from agent.collectors.dry_run import DryRunCollector
from agent.collectors.macro import MacroCollector
from agent.collectors.news import NewsCollector
from agent.collectors.onchain import OnchainCollector
from agent.collectors.price import PriceCollector
from agent.collectors.social import SocialCollector
from agent.config import Settings, check_optional_keys, get_settings
from agent.logging_utils import ExecutionLogger
from agent.reasoning.llm_client import build_llm_client
from agent.reasoning.pipeline import ReasoningResult, ReasoningStepError, run_reasoning
from agent.reasoning.prompts import classify_question_type
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
    collectors: list[BaseCollector], coins: list[str], remaining_seconds: float
) -> list[EvidenceDraft]:
    """對每個 collector × 每個幣種平行執行（比較分析題型會有 2 個幣種）。"""
    if remaining_seconds <= 0:
        return []
    tasks = [c.run(coin) for c in collectors for coin in coins]
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
    coin2: str | None = None,
) -> RunResult:
    settings = get_settings()
    start_time = time.monotonic()

    out_dir = Path(output_dir or settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger = ExecutionLogger(out_dir / "execution_log.jsonl")

    for warning in check_optional_keys():
        logger.log(phase=LogPhase.COLLECT, action="config_check", detail=warning, status=LogStatus.SKIPPED)

    question_type = classify_question_type(question)

    # 「比較分析」題型需要第二個幣種的證據：優先用使用者明確指定的 --coin2，
    # 否則嘗試從題目文字自動偵測（題目模板通常會直接寫出「比較【幣種A】與
    # 【幣種B】」）。偵測不到就維持單幣種證據，report 會依既有 framing
    # 在限制中明確揭露比較對象資料不足，而非憑空比較。
    if question_type == "comparison":
        if coin2 is None:
            detected = [c for c in detect_coins_in_text(question) if c != coin.upper()]
            if detected:
                coin2 = detected[0]
        if coin2:
            coin2 = coin2.upper()
            logger.log(
                phase=LogPhase.COLLECT,
                action="comparison_coin2_resolved",
                detail=f"coin2={coin2}",
                status=LogStatus.OK,
            )
        else:
            logger.log(
                phase=LogPhase.COLLECT,
                action="comparison_coin2_not_found",
                detail="comparison 題型但未指定/偵測到第二個幣種，本次僅蒐集單一幣種證據",
                status=LogStatus.SKIPPED,
            )
    else:
        coin2 = None

    coins = [coin] + ([coin2] if coin2 else [])

    logger.log(
        phase=LogPhase.COLLECT,
        action="pipeline_start",
        detail=f"coins={coins}, question={question!r}, dry_run={dry_run}",
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
        drafts = asyncio.run(collect_all(collectors, coins, remaining_before_collect))

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

    def log_step(step: str, status: str, detail: str = "") -> None:
        logger.log(phase=LogPhase.REASON, action=step, detail=detail, status=LogStatus(status))

    if dry_run:
        reasoning_result = run_reasoning(coin, question, evidences, dry_run=True, coin2=coin2)
    else:
        llm_client = build_llm_client(settings)
        logger.log(
            phase=LogPhase.REASON,
            action="llm_backend",
            detail=f"backend={settings.llm_backend}",
            status=LogStatus.OK,
        )
        try:
            reasoning_result = run_reasoning(
                coin, question, evidences, dry_run=False, llm_client=llm_client, log_step=log_step, coin2=coin2
            )
        except ReasoningStepError as exc:
            # 推理鏈任一步驟失敗都不可讓整個 pipeline 中斷：退化為誠實揭露失敗原因的結論，
            # 讓 report.md / evidence.json / execution_log.jsonl 仍能完整產出。
            logger.log(phase=LogPhase.REASON, action="reasoning_failed", detail=str(exc), status=LogStatus.ERROR)
            reasoning_result = ReasoningResult(
                question_type=classify_question_type(question),
                facts=[],
                cross_validation={},
                inference=[],
                conclusion={
                    "market_judgment": "本次執行因推理鏈呼叫失敗，無法產出正式市場判斷，請參考 execution_log.jsonl 排查原因。",
                    "confidence": "低",
                    "limitations": [f"推理鏈執行失敗: {exc}"],
                    "invalidation_conditions": ["修復推理鏈問題後重新執行"],
                    "evidence_ids": [],
                },
            )

    logger.log(
        phase=LogPhase.REASON,
        action="reasoning_complete",
        detail=f"question_type={reasoning_result.question_type}",
        status=LogStatus.OK,
    )

    report_md = build_report_markdown(coin, question, reasoning_result, evidences, coin2=coin2)
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

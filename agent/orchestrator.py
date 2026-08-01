"""Orchestrator：Phase 1（蒐集）→ Phase 2（證據化）→ Phase 3（推理）→ Phase 4（報告生成）。

負責 15 分鐘硬性 deadline 與 degraded mode（超過
`degraded_mode_trigger_seconds` 後跳過剩餘蒐集、直接進入推理）。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from agent.collectors.base import BaseCollector
from agent.collectors.coin_map import detect_coins_in_text
from agent.collectors.derivatives import DerivativesCollector
from agent.collectors.dry_run import DryRunCollector
from agent.collectors.macro import MacroCollector
from agent.collectors.news import NewsCollector
from agent.collectors.onchain import OnchainCollector
from agent.collectors.price import PriceCollector
from agent.collectors.social import SocialCollector
from agent.config import Settings, check_optional_keys, get_settings
from agent.logging_utils import ExecutionLogger
from agent.reasoning.baseline import run_baseline, run_baseline_dry_run
from agent.reasoning.llm_client import build_llm_client
from agent.reasoning.pipeline import ReasoningResult, ReasoningStepError, run_reasoning
from agent.reasoning.prompts import classify_question_type
from agent.report.builder import build_report_markdown
from agent.report.view_builder import build_report_view
from agent.filters.content import apply_content_filters, scan_pr_terms
from agent.filters.dedup import apply_dedup
from agent.filters.injection import apply_injection_filter
from agent.filters.source_weights import apply_source_weights
from agent.schemas import Evidence, EvidenceDraft, FilterDecision, HorizonClass, LogPhase, LogStatus, PipelineLayer, RunMetrics

SOURCE_TYPES = ["price", "onchain", "news", "social", "macro", "derivatives"]

# 從硬性上限扣掉、留給「推理結束後的收尾」的時間：報告組裝、evidence.json 與
# report_view.json 寫檔、引用檢查。這些都是本機運算沒有網路，實測都在 1 秒內，
# 但 15 分鐘是硬性上限（命題文件執行限制第 1 條：超時主辦方可停止執行或不採計
# 產出），所以推理層拿到的 deadline 要比真正的截止早一點，不能剛好用滿。
REPORT_RESERVE_SECONDS = 20

# 一題最多蒐集幾個幣種的證據。比較題型「題目提到幾個就抓幾個」，這個上限純粹是
# 時間與 prompt 長度的保護：collector 之間是平行的（牆鐘不隨幣種數線性成長），
# 但證據筆數會——實測 2 幣種約 40-47 筆、Step D 的 prompt 已達 18k 字。
# 3 個幣種約 60-70 筆仍在 15 分鐘預算內。超出上限的幣種會照實揭露為未涵蓋。
MAX_COMPARISON_COINS = 3


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
        DerivativesCollector(logger, timeout_seconds=settings.collector_timeout_seconds, settings=settings),
    ]


async def collect_all(
    collectors: list[BaseCollector], coins: list[str], remaining_seconds: float
) -> list[EvidenceDraft]:
    """對每個 collector × 每個幣種平行執行（比較分析題型會有 2 個幣種）。

    特例：macro collector 產出的是幣種無關的全域資料（Fear & Greed Index、
    央行匯率等），無論有幾個幣種都只用主幣種跑一次，避免重複證據。
    """
    if remaining_seconds <= 0:
        return []
    tasks: list = []
    for c in collectors:
        if c.source_type == "macro":
            # macro 是幣種無關的全域資料，只用主幣種跑一次
            tasks.append(c.run(coins[0]))
        else:
            for coin in coins:
                tasks.append(c.run(coin))
    results = await asyncio.gather(*tasks)
    drafts: list[EvidenceDraft] = []
    for r in results:
        drafts.extend(r)
    return drafts


# spot 帶容許的最長觀察窗（天）。design.md §3.2 有幾筆合法的 spot 證據帶著跨日窗口
# （OI 四象限、多空帳戶比皆為 30 小時趨勢），那不是漏標；真正要抓的是把月／年尺度的
# 資料留在預設 spot 的情況（MA120、CME COT 這類假矛盾來源）。
SPOT_MAX_WINDOW_DAYS = 7


def _window_span_days(window_start: str | None, window_end: str | None) -> int | None:
    """觀察窗天數（含端點）。任一端缺漏或格式不可解時回 None，由呼叫端各自處理。"""
    if not window_start or not window_end:
        return None
    try:
        start = date.fromisoformat(window_start[:10])
        end = date.fromisoformat(window_end[:10])
    except ValueError:
        return None
    return (end - start).days + 1


def _horizon_annotation_issue(ev: Evidence) -> str | None:
    """回傳 horizon 標註的問題描述，無問題回 None（R2-3）。"""
    if (ev.window_start is None) != (ev.window_end is None):
        return (
            f"觀察窗只標了一端（window_start={ev.window_start}, window_end={ev.window_end}），"
            f"標註不完整"
        )
    if ev.horizon_class == HorizonClass.SPOT:
        span = _window_span_days(ev.window_start, ev.window_end)
        if span is not None and span > SPOT_MAX_WINDOW_DAYS:
            return (
                f"horizon_class 為預設 spot 但觀察窗長達 {span} 天"
                f"（{ev.window_start}~{ev.window_end}），疑似漏標非 spot 分帶"
            )
    return None


def assign_evidence_ids(drafts: list[EvidenceDraft], logger=None) -> list[Evidence]:
    evidences = []
    for i, draft in enumerate(drafts, start=1):
        ev = Evidence(id=f"ev-{i:03d}", **draft.model_dump())
        # horizon-aware R2-3：標註缺漏／矛盾只記警示 log，絕不拋錯或過濾掉證據（R6-1 降級優先）。
        issue = _horizon_annotation_issue(ev) if logger is not None else None
        if issue:
            logger.log(
                phase=LogPhase.COLLECT,
                action="horizon_annotation_warning",
                detail=f"{ev.id}（{ev.source_type.value}/{ev.source}）{issue}",
                status=LogStatus.SKIPPED,
                layer=PipelineLayer.SOURCE,
            )
        evidences.append(ev)
    return evidences


def run_pipeline(
    coin: str,
    question: str,
    dry_run: bool = True,
    output_dir: str | None = None,
    coin2: str | None = None,
    with_baseline: bool = False,
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
    # 題目提到、但超出上限而沒蒐集的幣種。報告要誠實揭露，
    # 不能讓模型去比較一個它根本沒有資料的幣。
    uncovered_coins: list[str] = []
    # 主幣以外、本次也會蒐集證據的幣種（比較題型才有）。
    extra_coins: list[str] = []
    if question_type == "comparison":
        detected = [c for c in detect_coins_in_text(question) if c != coin.upper()]
        if coin2:
            # 使用者用 --coin2 明確指定時，把它排到最前面（其餘偵測到的仍會蒐集）
            coin2 = coin2.upper()
            detected = [coin2] + [c for c in detected if c != coin2]
        # **題目提到幾個幣就蒐集幾個**，不是只取第一個。少蒐集一個幣的代價是
        # 題目根本回答不了，而且錯在蒐集階段、事後無法補救；多蒐集的代價只是
        # 多花一點時間與 prompt 長度。上限 MAX_COMPARISON_COINS 是時間預算的保護，
        # 不是設計取捨——超出的部分照實揭露，不假裝有分析到。
        extra_coins = detected[: MAX_COMPARISON_COINS - 1]
        uncovered_coins = detected[MAX_COMPARISON_COINS - 1 :]
        # `coin2` 是既有下游（framing／相對指標／報告標題）的相容欄位，
        # 維持「第一個非主幣」的語意。完整清單走 `coins`。
        coin2 = extra_coins[0] if extra_coins else None
        if uncovered_coins:
            logger.log(
                phase=LogPhase.COLLECT,
                action="comparison_coins_uncovered",
                detail=(
                    f"題目提到 {', '.join(uncovered_coins)} 但超出本次蒐集上限"
                    f"（{MAX_COMPARISON_COINS} 個幣種），報告需揭露此限制"
                ),
                status=LogStatus.SKIPPED,
            )
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

    coins = [coin] + extra_coins

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

    # 追蹤 degraded 原因，任一項非空時最終 integrity_status="DEGRADED"
    degraded_reasons: list[str] = []

    if degraded_mode:
        logger.log(
            phase=LogPhase.COLLECT,
            action="degraded_mode",
            detail="已超過 degraded_mode_trigger_seconds，跳過剩餘資料蒐集，直接進入推理",
            status=LogStatus.SKIPPED,
        )
        drafts: list[EvidenceDraft] = []
        degraded_reasons.append("collector timeout（已超過 degraded_mode_trigger_seconds）")
    else:
        drafts = asyncio.run(collect_all(collectors, coins, remaining_before_collect))

    evidences = assign_evidence_ids(drafts, logger=logger)

    # Phase 2（R12，Ken 設計）：去重先行 → 話術掃描 → 四因子權重 → L2 決策紀錄
    dedup_result = None
    try:
        dedup_result = apply_dedup(evidences, logger)
    except Exception as exc:
        # R12-5：去重失敗隔離，權重層自動視為無 dedup 資訊（覆蓋度/dedup 因子=1）
        logger.log(
            phase=LogPhase.COLLECT,
            action="l2_dedup_failed",
            detail=f"去重失敗，退回無 dedup 資訊計算（R12-5）: {exc}",
            status=LogStatus.ERROR,
            layer=PipelineLayer.CONTENT,
        )

    try:
        pr_hits = scan_pr_terms(evidences)
    except Exception as exc:
        pr_hits = {}
        logger.log(
            phase=LogPhase.COLLECT,
            action="l2_pr_scan_failed",
            detail=str(exc),
            status=LogStatus.ERROR,
            layer=PipelineLayer.CONTENT,
        )

    # L1 信源權重：四因子公式（信譽表載入失敗時內部自動退回舊制規則表，R12-5）
    breakdowns = apply_source_weights(
        evidences, logger, dedup_result=dedup_result, pr_demotions=pr_hits
    )

    # L2 內容層過濾（純本地，毫秒級）；DEDUP 決策一併納入供面板①③對帳
    filter_decisions: list[FilterDecision] = (
        list(dedup_result.decisions) if dedup_result else []
    )
    try:
        filter_decisions += apply_content_filters(
            evidences, logger, pr_hits=pr_hits, breakdowns=breakdowns
        )
    except Exception as exc:
        logger.log(
            phase=LogPhase.COLLECT,
            action="l2_content_failed",
            detail=str(exc),
            status=LogStatus.ERROR,
            layer=PipelineLayer.CONTENT,
        )
        degraded_reasons.append("L2 content filter skipped")

    # 比較題型：計算雙幣相對指標
    if question_type == "comparison" and coin2:
        try:
            from agent.collectors.relative import compute_relative_metrics
            relative_draft = compute_relative_metrics(coin.upper(), coin2)
            next_id = len(evidences) + 1
            relative_ev = Evidence(id=f"ev-{next_id:03d}", **relative_draft.model_dump())
            evidences.append(relative_ev)
            logger.log(
                phase=LogPhase.COLLECT,
                action="relative_metrics_computed",
                detail=f"{coin.upper()}/{coin2} 雙幣相對指標已加入",
                status=LogStatus.OK,
            )
        except Exception as exc:
            logger.log(
                phase=LogPhase.COLLECT,
                action="relative_metrics_failed",
                detail=str(exc),
                status=LogStatus.ERROR,
            )

    # L2 資安層：prompt injection 偵測。放在最後一個「會新增證據」的步驟之後、
    # 寫檔之前，確保比較題型補進來的相對指標證據也一起掃到。
    # high 命中者標記 injection_flag="high"，由 prompts 層排除出 LLM 清單；
    # 證據本身仍完整寫進 evidence.json（比照 dedup 的可回溯慣例）。
    try:
        filter_decisions += apply_injection_filter(evidences, logger)
    except Exception as exc:
        # 這層失效等於「本次沒有注入防護」，必須進 degraded 理由讓報告誠實揭露，
        # 不能像其他 L2 check 一樣默默跳過。
        logger.log(
            phase=LogPhase.COLLECT,
            action="l2_injection_failed",
            detail=f"注入偵測失敗，本次證據未經注入過濾: {exc}",
            status=LogStatus.ERROR,
            layer=PipelineLayer.CONTENT,
        )
        degraded_reasons.append("L2 prompt injection filter skipped（本次證據未經注入過濾）")

    # 題目提到但沒蒐集到的幣種，必須進 degraded 理由——報告的「已知限制」會照實揭露，
    # 讀者才知道這份比較沒有涵蓋題目要求的全部對象。命題文件的評分標準明列
    # 「對不確定性與限制的清楚說明」，揭露本身就是得分項，隱瞞才是失分。
    if uncovered_coins:
        degraded_reasons.append(
            f"題目提到 {', '.join(uncovered_coins)} 但本次未蒐集其證據，"
            f"比較範圍僅涵蓋 {coin.upper()}" + (f"／{coin2}" if coin2 else "")
        )

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
        reasoning_result = run_reasoning(coin, question, evidences, dry_run=True, coin2=coin2, logger=logger)
    else:
        llm_client = build_llm_client(settings)
        reasoning_deadline = start_time + settings.hard_deadline_seconds - REPORT_RESERVE_SECONDS
        logger.log(
            phase=LogPhase.REASON,
            action="llm_backend",
            detail=f"backend={settings.llm_backend}",
            status=LogStatus.OK,
        )
        # 把同一個硬性 deadline 也交給 LLM client：辯論輪之間的 gate 只擋得住第 2 輪，
        # Step A/B 在它之前、Step D 在它之後，都可能因為單次呼叫卡住而把整跑拖過 15 分鐘
        # （2026-08-01 實測 step_a_facts 卡了 1020s）。重試也要留下紀錄，否則下次一樣難查。
        if hasattr(llm_client, "deadline"):
            llm_client.deadline = reasoning_deadline
        if hasattr(llm_client, "on_retry"):
            llm_client.on_retry = lambda detail: logger.log(
                phase=LogPhase.REASON,
                action="llm_retry",
                detail=detail,
                status=LogStatus.SKIPPED,
            )
        try:
            reasoning_result = run_reasoning(
                coin, question, evidences, dry_run=False, llm_client=llm_client, log_step=log_step, coin2=coin2, logger=logger,
                deadline=reasoning_deadline,
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

        # 讀取 LLM usage 統計
        usage = getattr(llm_client, "usage", None)
        if usage:
            total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            logger.log(
                phase=LogPhase.REASON,
                action="llm_usage",
                detail=f"total_tokens={total_tokens}, calls={usage.get('calls', 0)}",
                status=LogStatus.OK,
                metrics=usage,
            )

    logger.log(
        phase=LogPhase.REASON,
        action="reasoning_complete",
        detail=f"question_type={reasoning_result.question_type}",
        status=LogStatus.OK,
    )

    # Baseline 對照組（可開關，預設關閉）
    baseline_result: dict | None = None
    if with_baseline:
        if dry_run:
            baseline_result = run_baseline_dry_run(question, coin=coin, coin2=coin2)
        else:
            baseline_result = run_baseline(
                question=question,
                evidences=evidences,
                llm_client=llm_client,
                coin=coin,
                coin2=coin2,
            )
        logger.log(
            phase=LogPhase.REASON,
            action="baseline_complete",
            detail=f"enabled=True, has_error={'error' in baseline_result}",
            status=LogStatus.OK if "error" not in baseline_result else LogStatus.ERROR,
        )

    report_md = build_report_markdown(
        coin, question, reasoning_result, evidences, coin2=coin2,
        uncovered_coins=uncovered_coins,
    )
    report_path = out_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")
    logger.log(phase=LogPhase.REPORT, action="report_written", detail=str(report_path), status=LogStatus.OK)

    # view_builder：組裝 report_view.json（失敗隔離，不影響三個命題交付檔）
    try:
        # 計算 RunMetrics
        contradictions_count = len(reasoning_result.cross_validation.get("contradictions", []))
        # 從 log 讀取 L3 noise_removal_rate
        l3_entries = [e for e in logger.read_all() if e.action == "l3_fact_extraction"]
        noise_rate = l3_entries[-1].metrics.get("removal_rate", 0.0) if l3_entries else 0.0

        # 讀取 LLM usage
        total_tokens = 0
        if not dry_run:
            usage = getattr(llm_client, "usage", None)
            if usage:
                total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        run_metrics = RunMetrics(
            confidence=reasoning_result.confidence_score,
            noise_removal_rate=noise_rate,
            total_tokens=total_tokens,
            integrity_status="DEGRADED" if degraded_reasons else "INTACT",
            raw_evidence_count=len(evidences),
            kept_fact_count=sum(
                len(f.get("evidence_ids", [])) for f in reasoning_result.facts
            ),
            degraded_reasons=degraded_reasons,
        )

        view = build_report_view(
            out_dir=out_dir,
            evidences=evidences,
            reasoning_result=reasoning_result,
            run_metrics=run_metrics,
            filter_decisions=filter_decisions,
            baseline_result=baseline_result,
            coin=coin,
            coin2=coin2,
            question=question,
        )
        if view:
            logger.log(
                phase=LogPhase.REPORT,
                action="view_written",
                detail=str(out_dir / "report_view.json"),
                status=LogStatus.OK,
            )
        else:
            logger.log(
                phase=LogPhase.REPORT,
                action="view_build_failed",
                detail="build_report_view returned None",
                status=LogStatus.ERROR,
            )
    except Exception as exc:
        logger.log(
            phase=LogPhase.REPORT,
            action="view_build_failed",
            detail=str(exc),
            status=LogStatus.ERROR,
        )

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

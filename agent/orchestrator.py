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
from agent.collectors.coin_map import detect_coins_in_text, get_coin_info
from agent.collectors.derivatives import DerivativesCollector
from agent.collectors.dry_run import DryRunCollector
from agent.collectors.horizon import resolve_primary_horizon
from agent.collectors.macro import MacroCollector
from agent.collectors.news import NewsCollector
from agent.collectors.onchain import OnchainCollector
from agent.collectors.price import PriceCollector
from agent.collectors.reference_pages import resolve_reference_url
from agent.collectors.social import SocialCollector
from agent.config import Settings, check_optional_keys, get_settings
from agent.logging_utils import ExecutionLogger
from agent.reasoning.baseline import run_baseline, run_baseline_dry_run
from agent.reasoning.llm_client import build_llm_client
from agent.reasoning.pipeline import ReasoningResult, ReasoningStepError, run_reasoning
from agent.reasoning.prompts import classify_question_type
from agent.report.builder import build_report_markdown
from agent.report.html_export import export_html_bundle
from agent.report.view_builder import build_report_view
from agent.filters.content import apply_content_filters, scan_pr_terms
from agent.filters.dedup import apply_dedup
from agent.filters.injection import apply_injection_filter
from agent.filters.source_weights import apply_source_weights
from agent.filters.validation import build_validation_results
from agent.integrity import assess_integrity
from agent.reasoning.consistency import enforce_reasoning_consistency
from agent.research.context import write_research_context
from agent.schemas import Evidence, EvidenceDraft, FilterDecision, HorizonClass, LogPhase, LogStatus, PipelineLayer, RunMetrics

SOURCE_TYPES = ["price", "onchain", "news", "social", "macro", "derivatives"]

# 從硬性上限扣掉、留給「推理結束後的收尾」的時間：報告組裝、evidence.json 與
# report_view.json 寫檔、引用檢查。這些都是本機運算沒有網路，實測都在 1 秒內，
# 但 15 分鐘是硬性上限（命題文件執行限制第 1 條：超時主辦方可停止執行或不採計
# 產出），所以推理層拿到的 deadline 要比真正的截止早一點，不能剛好用滿。
REPORT_RESERVE_SECONDS = 20


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
    collectors: list[BaseCollector],
    coins: list[str],
    remaining_seconds: float,
    primary_horizon: HorizonClass | None = None,
) -> list[EvidenceDraft]:
    """對每個 collector × 每個幣種平行執行（比較分析題型會有 2 個幣種）。

    特例：macro collector 產出的是幣種無關的全域資料（Fear & Greed Index、
    央行匯率等），無論有幾個幣種都只用主幣種跑一次，避免重複證據。

    `primary_horizon`（R8-5）：傳給每個 collector 的 `run()`／`fetch()`，各自
    盡力依此調整查詢窗；`BaseCollector.run()` 用 `**kwargs` 透傳，不支援調整的
    collector 會直接忽略這個參數、維持既有行為（R6-1 降級優先，不會因此失敗）。
    """
    if remaining_seconds <= 0:
        return []
    tasks: list = []
    for c in collectors:
        if c.source_type == "macro":
            # macro 是幣種無關的全域資料，只用主幣種跑一次
            tasks.append(c.run(coins[0], primary_horizon=primary_horizon))
        else:
            for coin in coins:
                tasks.append(c.run(coin, primary_horizon=primary_horizon))
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


def _resolve_chain(coin: str) -> str | None:
    """幣種 → 鏈別（供 onchain 的 RPC 端點對照瀏覽器）。未知幣種回 None。"""
    try:
        return get_coin_info(coin).chain
    except Exception:  # noqa: BLE001 - 未知幣種不該中斷流程（R6-1）
        return None


def assign_evidence_ids(
    drafts: list[EvidenceDraft], logger=None
) -> tuple[list[Evidence], list[dict]]:
    """把 collector 產出的草稿建構成正式 `Evidence`，並分配全域唯一 id。

    回傳 `(evidences, quarantined)`——`quarantined` 是建構失敗（缺欄位、型別
    錯誤）的草稿紀錄。**這是真正的「Invalid Evidence quarantine」，不是只有
    dedup 降權**：以前 `Evidence(id=..., **payload)` 沒有任何防護，單一一筆
    壞資料的 collector 輸出會讓 pydantic ValidationError 直接炸穿整條
    pipeline。一筆證據建構失敗不該賠上其餘所有正常證據（R6-1 降級優先）。
    """
    evidences: list[Evidence] = []
    quarantined: list[dict] = []
    for i, draft in enumerate(drafts, start=1):
        payload = draft.model_dump()
        # 補上「人看的頁面」。集中在這裡推導而非散在 7 個 collector 的 32 個
        # EvidenceDraft 呼叫點：對照表只有一份、可稽核、可單獨測，且新增來源時
        # 不改 collector 也能受惠。collector 若自己就知道更好的頁面（例如 news／
        # social 的原文網址），可直接填 reference_url，這裡不覆蓋。
        if not payload.get("reference_url"):
            payload["reference_url"] = resolve_reference_url(
                payload.get("source_url"), draft.coin, _resolve_chain(draft.coin)
            )
        try:
            ev = Evidence(id=f"ev-{i:03d}", **payload)
        except Exception as exc:  # noqa: BLE001 - 任何一筆壞資料都不該中斷整條 pipeline
            quarantined.append(
                {
                    "index": i,
                    "source": draft.source,
                    "coin": draft.coin,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
            if logger is not None:
                logger.log(
                    phase=LogPhase.COLLECT,
                    action="evidence_quarantined",
                    detail=f"draft#{i}（{draft.source}）建構失敗已隔離: {type(exc).__name__}: {exc}",
                    status=LogStatus.SKIPPED,
                    layer=PipelineLayer.SOURCE,
                )
            continue
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
    return evidences, quarantined


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

    # R8-5：主視野在蒐集階段就先解出來，讓有能力調整查詢窗的 collector（如
    # social／news）可以據此決定抓多長的窗；resolve_primary_horizon 是純函式，
    # 跟 pipeline.py 推理層各自獨立呼叫同一份、結果必然一致，不需要跨層傳遞狀態。
    primary_horizon, primary_horizon_basis = resolve_primary_horizon(question)
    logger.log(
        phase=LogPhase.COLLECT,
        action="primary_horizon_for_collection",
        detail=f"primary_horizon={primary_horizon.value}, basis={primary_horizon_basis or '（題目未明示，用預設）'}",
        status=LogStatus.OK,
    )

    elapsed = time.monotonic() - start_time
    remaining_before_collect = settings.hard_deadline_seconds - elapsed
    # 邊界值也代表預算已用完。使用 `>` 會在 Windows 的第一個 monotonic tick
    # 剛好仍為 0 時讓 trigger=0 的執行漏過 gate，形成平台相依的 flaky 行為。
    degraded_mode = elapsed >= settings.degraded_mode_trigger_seconds

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
        drafts = asyncio.run(
            collect_all(collectors, coins, remaining_before_collect, primary_horizon=primary_horizon)
        )

    evidences, quarantined_drafts = assign_evidence_ids(drafts, logger=logger)
    if quarantined_drafts:
        degraded_reasons.append(f"{len(quarantined_drafts)} 筆證據建構失敗已隔離（缺欄位或型別錯誤）")

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

    # 統一 Validation Result（v1.2 新增，ValidatedEvidence gate 的稽核輸出）：
    # 把 source_weight／injection_flag／dedup verdict 這些已經算好的既有檢查結果
    # 彙總成一筆 per-evidence 紀錄，寫成獨立檔案——刻意不塞進 evidence.json，
    # 那份檔案的頂層是 list（webapp／report 已經假設這個形狀），改成 dict 會
    # 動到既有讀取邏輯。
    validation_results = build_validation_results(evidences, breakdowns, filter_decisions)
    validation_path = out_dir / "validation_results.json"
    validation_path.write_text(
        json.dumps([vars(r) for r in validation_results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.log(
        phase=LogPhase.COLLECT,
        action="validation_results_written",
        detail=(
            f"count={len(validation_results)}, quarantined={len(quarantined_drafts)}, "
            f"path={validation_path}"
        ),
        status=LogStatus.OK,
        layer=PipelineLayer.SOURCE,
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
            degraded_reasons.append("推理鏈失敗，已輸出降級報告")
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

    # v1 報告一致性護欄：可由 Evidence 日期確定重算的事件時間，不再完全信任
    # LLM 在不同段落的自由換算。校正會同時套用 facts／辯論／結論，避免只修畫面
    # 而下載的 report.md 仍互相矛盾。
    try:
        consistency_corrections = enforce_reasoning_consistency(reasoning_result, evidences)
        if consistency_corrections:
            logger.log(
                phase=LogPhase.REASON,
                action="consistency_guard_corrected",
                detail=(
                    f"count={len(consistency_corrections)}, "
                    f"events={sorted({c.event for c in consistency_corrections})}"
                ),
                status=LogStatus.OK,
                layer=PipelineLayer.CONCLUSION,
                metrics={
                    "count": len(consistency_corrections),
                    "corrections": [c.__dict__ for c in consistency_corrections],
                },
            )
    except Exception as exc:  # noqa: BLE001 - 護欄失敗不可吃掉整份報告，但必須降級揭露
        degraded_reasons.append("跨段落一致性檢查失敗")
        logger.log(
            phase=LogPhase.REASON,
            action="consistency_guard_failed",
            detail=f"{type(exc).__name__}: {exc}",
            status=LogStatus.ERROR,
            layer=PipelineLayer.CONCLUSION,
        )

    # v2-reference sidecar：只把既有 Evidence／Reasoning 關係結構化，不回寫結論、
    # 不重算 confidence，也不進入 LLM。失敗隔離以維持 v1.2 正式交付；但若 graph
    # 發現 invalid/quarantined Evidence 仍被推理引用，代表 ValidatedEvidence gate
    # 真正漏水，必須降級揭露，不能只把異常藏在 sidecar。
    try:
        research_path, research_context = write_research_context(
            out_dir,
            evidences,
            reasoning_result,
            question=question,
            question_type=reasoning_result.question_type,
            validation_results=validation_results,
            quarantined_drafts=quarantined_drafts,
        )
        graph = research_context.evidence_graph
        violations = graph.stats.get("validation_violations", 0)
        logger.log(
            phase=LogPhase.REPORT,
            action="research_context_written",
            detail=f"path={research_path}, validation_violations={violations}",
            status=LogStatus.ERROR if violations else LogStatus.OK,
            metrics={
                "features": len(research_context.structured_features),
                "knowledge_cards": len(research_context.knowledge_cards),
                "graph_nodes": len(graph.nodes),
                "graph_edges": len(graph.edges),
                **graph.stats,
            },
        )
        if violations:
            degraded_reasons.append(
                f"ValidatedEvidence gate 發現 {violations} 條無效／隔離證據引用"
            )
    except Exception as exc:  # noqa: BLE001 - 額外 sidecar 不可阻止命題正式交付
        logger.log(
            phase=LogPhase.REPORT,
            action="research_context_failed",
            detail=f"{type(exc).__name__}: {exc}",
            status=LogStatus.ERROR,
        )

    integrity = assess_integrity(evidences, coins, degraded_reasons)
    if integrity.status != "INTACT":
        integrity_note = f"資料完整性 {integrity.status}：{'；'.join(integrity.reasons)}"
        limitations = reasoning_result.conclusion.setdefault("limitations", [])
        if integrity_note not in limitations:
            limitations.append(integrity_note)
        logger.log(
            phase=LogPhase.COLLECT,
            action="integrity_assessment",
            detail=integrity_note,
            status=LogStatus.ERROR if integrity.status == "DEGRADED" else LogStatus.SKIPPED,
            metrics={"integrity_status": integrity.status, "reasons": integrity.reasons},
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

    report_md = build_report_markdown(coin, question, reasoning_result, evidences, coin2=coin2)
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
            integrity_status=integrity.status,
            raw_evidence_count=len(evidences),
            kept_fact_count=sum(
                len(f.get("evidence_ids", [])) for f in reasoning_result.facts
            ),
            # 欄位名稱為了 report_view.json v1 相容仍保留 degraded_reasons；在
            # PARTIAL 時同樣承載具體缺失原因，前端會依 status 使用中性警示。
            degraded_reasons=integrity.reasons,
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

    # 三份命題原始交付檔仍是權威來源；HTML 僅是可離線開啟的評審閱讀副本。
    # 放在 pipeline_end 後才匯出，確保 execution_log.html 包含完整流程終點。
    # 匯出失敗採隔離處理，不得反過來阻止正式交付檔產出。
    try:
        export_html_bundle(
            out_dir=out_dir,
            report_markdown=report_md,
            evidences=evidences,
            log_entries=logger.read_all(),
            metadata={
                "coin": coin,
                "coin2": coin2,
                "question": question,
                "integrity_status": integrity.status,
            },
        )
    except Exception as exc:
        logger.log(
            phase=LogPhase.REPORT,
            action="html_export_failed",
            detail=str(exc),
            status=LogStatus.ERROR,
        )

    return RunResult(
        report_markdown=report_md,
        evidences=evidences,
        reasoning=reasoning_result,
        degraded_mode=degraded_mode,
        elapsed_seconds=total_elapsed,
    )

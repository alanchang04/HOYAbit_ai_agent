"""四步推理鏈組裝：事實層 → 交叉驗證層 → 推論層 → 結論層。

`dry_run=True` 時回傳依實際 evidence 組成的假推理結果（不呼叫任何 LLM），
用於驗證整體 pipeline 與 report-evidence 對應檢查。
`dry_run=False` 時依序呼叫 llm_client 完成四步推理，並在每一步後
過濾掉模型可能捏造、不存在於 evidence 清單中的 evidence id（防止幻覺
引用讓 Phase 4 的報告檢查失敗、拖垮整個流程）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.logging_utils import ExecutionLogger
from agent.reasoning.llm_client import LLMClient
from agent.reasoning.prompts import (
    SYSTEM_PROMPT,
    build_step_a_prompt,
    build_step_b_prompt,
    build_step_c_prompt,
    build_step_c1_bull_prompt,
    build_step_c2_bear_prompt,
    build_step_d_prompt,
    classify_question_type,
    extract_json,
)
from agent.reasoning.confidence import compute_confidence_score
from agent.schemas import Evidence, LogPhase, LogStatus, PipelineLayer, QuestionType


@dataclass
class ReasoningResult:
    question_type: QuestionType
    facts: list[dict] = field(default_factory=list)
    cross_validation: dict = field(default_factory=dict)
    inference: list[dict] = field(default_factory=list)
    conclusion: dict = field(default_factory=dict)
    follow_up_watchpoints: list[str] = field(default_factory=list)
    debate: dict = field(default_factory=dict)
    coin2: str | None = None
    confidence_score: int = 0


class ReasoningStepError(RuntimeError):
    """某一步驟呼叫 LLM 或解析回應失敗時拋出，由呼叫端決定如何降級處理。"""


def _dry_run_reasoning(
    coin: str,
    question: str,
    question_type: QuestionType,
    evidences: list[Evidence],
    coin2: str | None = None,
    logger: ExecutionLogger | None = None,
) -> ReasoningResult:
    by_type: dict[str, list[Evidence]] = {}
    for ev in evidences:
        by_type.setdefault(ev.source_type.value, []).append(ev)

    facts = [
        {
            "summary": f"（dry-run 假資料）{stype} 類來源共 {len(evs)} 筆證據可供參考。",
            "evidence_ids": [e.id for e in evs],
        }
        for stype, evs in by_type.items()
    ]

    # L3 metrics：事實提取層量化
    if logger:
        input_count = len(evidences)
        kept_ids: set[str] = set()
        for f in facts:
            kept_ids.update(f.get("evidence_ids", []))
        kept_count = len(kept_ids)
        removed_count = input_count - kept_count
        removal_rate = removed_count / input_count if input_count > 0 else 0.0
        logger.log(
            phase=LogPhase.REASON,
            action="l3_fact_extraction",
            detail=f"input={input_count}, kept={kept_count}, removed={removed_count}, rate={removal_rate:.3f}",
            status=LogStatus.OK,
            layer=PipelineLayer.FACT,
            metrics={"input": input_count, "kept": kept_count, "removed": removed_count, "removal_rate": round(removal_rate, 4)},
        )

    all_ids = [e.id for e in evidences]
    coin_label = f"{coin} 與 {coin2}" if coin2 else coin

    cross_validation = {
        "consistent_signals": ["（dry-run 假資料）各來源皆無法判斷實際一致性，僅為流程驗證"],
        "contradictions": [],
    }

    # L4 metrics：交叉驗證層量化
    if logger:
        consistent_count = len(cross_validation.get("consistent_signals", []))
        contradiction_count = len(cross_validation.get("contradictions", []))
        logger.log(
            phase=LogPhase.REASON,
            action="l4_cross_validation",
            detail=f"consistent={consistent_count}, contradictions={contradiction_count}",
            status=LogStatus.OK,
            layer=PipelineLayer.CROSS,
            metrics={"consistent": consistent_count, "contradictions": contradiction_count},
        )

    conclusion = {
        "market_judgment": f"（dry-run 假資料，非真實分析）針對「{question}」，{coin_label} 的市場判斷待正式資料與 Bedrock 推理補上。",
        "confidence": "低",
        "limitations": ["本次為 --dry-run 假資料流程，未使用真實市場資料與 LLM 推理"],
        "invalidation_conditions": ["正式執行並取得真實資料後，本假結論應被取代"],
        "evidence_ids": all_ids,
    }

    # L5：數值信心分數
    contradictions_count = len(cross_validation.get("contradictions", []))
    score, breakdown = compute_confidence_score(
        conclusion.get("confidence", "低"),
        evidences,
        contradictions_count,
    )
    if logger:
        logger.log(
            phase=LogPhase.REASON,
            action="l5_confidence_score",
            detail=(
                f"score={score}, base={breakdown['base']}, auth_bonus={breakdown['auth_bonus']}, "
                f"contradiction_penalty={breakdown['contradiction_penalty']}, gap_penalty={breakdown['gap_penalty']}"
            ),
            status=LogStatus.OK,
            layer=PipelineLayer.CONCLUSION,
            metrics=breakdown,
        )

    return ReasoningResult(
        question_type=question_type,
        facts=facts,
        cross_validation=cross_validation,
        inference=[
            {
                "hypothesis": f"（dry-run 假資料）{coin_label} 市場狀態假設",
                "supporting_evidence_ids": all_ids[:1],
                "opposing_evidence_ids": [],
            }
        ],
        conclusion=conclusion,
        follow_up_watchpoints=["（dry-run 假資料）此為流程驗證用，非真實觀察重點"],
        coin2=coin2,
        confidence_score=score,
    )


def _call_json_step(llm_client: LLMClient, user_prompt: str, step_name: str) -> dict:
    """呼叫 LLM 並解析 JSON，若第一次解析失敗，重試一次並明確要求修正格式。

    無論是 LLM 呼叫本身失敗（網路、配額、認證等）或回應無法解析為 JSON，
    一律轉成 ReasoningStepError，讓上層 orchestrator 可以統一捕捉、
    退化為誠實揭露失敗原因的報告，而不是讓整個 process 直接崩潰。
    """
    try:
        raw = llm_client.converse(SYSTEM_PROMPT, user_prompt)
    except Exception as exc:  # noqa: BLE001
        raise ReasoningStepError(f"{step_name} 呼叫 LLM 失敗: {exc}") from exc

    try:
        return extract_json(raw)
    except Exception:  # noqa: BLE001
        retry_prompt = (
            f"{user_prompt}\n\n"
            f"你上一次的回應無法被解析為合法 JSON（原始回應：{raw[:500]!r}）。"
            f"請只輸出合法 JSON，不要有任何其他文字或 code fence。"
        )
        try:
            raw_retry = llm_client.converse(SYSTEM_PROMPT, retry_prompt)
        except Exception as exc:  # noqa: BLE001
            raise ReasoningStepError(f"{step_name} 重試呼叫 LLM 失敗: {exc}") from exc
        try:
            return extract_json(raw_retry)
        except Exception as exc:  # noqa: BLE001
            raise ReasoningStepError(f"{step_name} 兩次皆無法解析為合法 JSON: {exc}") from exc


def _sanitize_ids(ids: list, known_ids: set[str]) -> list[str]:
    """過濾掉不存在於 evidence 清單中的 id，避免模型幻覺引用讓後續報告檢查崩潰。"""
    if not isinstance(ids, list):
        return []
    return [i for i in ids if isinstance(i, str) and i in known_ids]


def _sanitize_facts(facts: list, known_ids: set[str]) -> list[dict]:
    sanitized = []
    if not isinstance(facts, list):
        return sanitized
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        entry = {
            "source_type": fact.get("source_type", ""),
            "summary": fact.get("summary", ""),
            "evidence_ids": _sanitize_ids(fact.get("evidence_ids", []), known_ids),
        }
        if isinstance(fact.get("coin"), str):
            entry["coin"] = fact["coin"]
        sanitized.append(entry)
    return sanitized


def _sanitize_inference(inference: list, known_ids: set[str]) -> list[dict]:
    sanitized = []
    if not isinstance(inference, list):
        return sanitized
    for inf in inference:
        if not isinstance(inf, dict):
            continue
        sanitized.append(
            {
                "hypothesis": inf.get("hypothesis", ""),
                "supporting_evidence_ids": _sanitize_ids(inf.get("supporting_evidence_ids", []), known_ids),
                "opposing_evidence_ids": _sanitize_ids(inf.get("opposing_evidence_ids", []), known_ids),
            }
        )
    return sanitized


def _real_reasoning(
    coin: str,
    question: str,
    question_type: QuestionType,
    evidences: list[Evidence],
    llm_client: LLMClient,
    log_step=None,
    coin2: str | None = None,
    logger: ExecutionLogger | None = None,
) -> ReasoningResult:
    known_ids = {e.id for e in evidences}

    def _log(step: str, status: str, detail: str = "") -> None:
        if log_step:
            log_step(step, status, detail)

    # Step A：事實層
    step_a_raw = _call_json_step(
        llm_client, build_step_a_prompt(coin, question, evidences, coin2=coin2), "step_a_facts"
    )
    facts = _sanitize_facts(step_a_raw.get("facts", []), known_ids)
    _log("step_a_facts", "ok", f"facts_count={len(facts)}")

    # L3 metrics：事實提取層量化
    if logger:
        input_count = len(evidences)
        kept_ids: set[str] = set()
        for f in facts:
            kept_ids.update(f.get("evidence_ids", []))
        kept_count = len(kept_ids)
        removed_count = input_count - kept_count
        removal_rate = removed_count / input_count if input_count > 0 else 0.0
        logger.log(
            phase=LogPhase.REASON,
            action="l3_fact_extraction",
            detail=f"input={input_count}, kept={kept_count}, removed={removed_count}, rate={removal_rate:.3f}",
            status=LogStatus.OK,
            layer=PipelineLayer.FACT,
            metrics={"input": input_count, "kept": kept_count, "removed": removed_count, "removal_rate": round(removal_rate, 4)},
        )

    # Step B：交叉驗證層
    step_b_raw = _call_json_step(
        llm_client, build_step_b_prompt(coin, question, evidences, facts, coin2=coin2), "step_b_cross_validation"
    )
    cross_validation = {
        "consistent_signals": step_b_raw.get("consistent_signals", []) if isinstance(step_b_raw.get("consistent_signals"), list) else [],
        "contradictions": step_b_raw.get("contradictions", []) if isinstance(step_b_raw.get("contradictions"), list) else [],
    }
    _log(
        "step_b_cross_validation",
        "ok",
        f"consistent={len(cross_validation['consistent_signals'])}, contradictions={len(cross_validation['contradictions'])}",
    )

    # L4 metrics：交叉驗證層量化
    if logger:
        consistent_count = len(cross_validation.get("consistent_signals", []))
        contradiction_count = len(cross_validation.get("contradictions", []))
        logger.log(
            phase=LogPhase.REASON,
            action="l4_cross_validation",
            detail=f"consistent={consistent_count}, contradictions={contradiction_count}",
            status=LogStatus.OK,
            layer=PipelineLayer.CROSS,
            metrics={"consistent": consistent_count, "contradictions": contradiction_count},
        )

    # Step C：推論層，改為正方 vs 反方辯論（提升對抗性，避免單一模型自問自答式的假辯論）。
    # 辯論任一步（C1 正方 / C2 反方）失敗，都會退回單模型一次產出多假設的舊版 Step C，
    # 確保推論層本身的失敗不會直接讓整條推理鏈中斷。
    debate: dict = {}
    try:
        step_c1_raw = _call_json_step(
            llm_client,
            build_step_c1_bull_prompt(coin, question, question_type, facts, cross_validation, coin2=coin2),
            "step_c1_bull",
        )
        bull_argument = step_c1_raw.get("argument", "")
        bull_evidence_ids = _sanitize_ids(step_c1_raw.get("evidence_ids", []), known_ids)
        _log("step_c1_bull", "ok", f"evidence_count={len(bull_evidence_ids)}")

        step_c2_raw = _call_json_step(
            llm_client,
            build_step_c2_bear_prompt(
                coin, question, question_type, facts, cross_validation, bull_argument, coin2=coin2
            ),
            "step_c2_bear",
        )
        bear_argument = step_c2_raw.get("argument", "")
        bear_critique = step_c2_raw.get("critique", "")
        bear_evidence_ids = _sanitize_ids(step_c2_raw.get("evidence_ids", []), known_ids)
        _log("step_c2_bear", "ok", f"evidence_count={len(bear_evidence_ids)}")

        debate = {
            "bull_argument": bull_argument,
            "bull_evidence_ids": bull_evidence_ids,
            "bear_critique": bear_critique,
            "bear_argument": bear_argument,
            "bear_evidence_ids": bear_evidence_ids,
        }
        inference = [
            {
                "hypothesis": f"[正方] {bull_argument}",
                "supporting_evidence_ids": bull_evidence_ids,
                "opposing_evidence_ids": bear_evidence_ids,
            },
            {
                "hypothesis": f"[反方] {bear_argument}",
                "supporting_evidence_ids": bear_evidence_ids,
                "opposing_evidence_ids": bull_evidence_ids,
            },
        ]
    except ReasoningStepError as exc:
        _log("step_c_debate", "error", f"正反方辯論失敗，退回單模型推論: {exc}")
        step_c_raw = _call_json_step(
            llm_client,
            build_step_c_prompt(coin, question, question_type, facts, cross_validation, coin2=coin2),
            "step_c_inference_fallback",
        )
        inference = _sanitize_inference(step_c_raw.get("inference", []), known_ids)
        _log("step_c_inference_fallback", "ok", f"hypotheses_count={len(inference)}")

    # Step D：結論層
    step_d_raw = _call_json_step(
        llm_client,
        build_step_d_prompt(coin, question, question_type, facts, cross_validation, inference, coin2=coin2),
        "step_d_conclusion",
    )
    conclusion = {
        "market_judgment": step_d_raw.get("market_judgment", ""),
        "confidence": step_d_raw.get("confidence", "低"),
        "limitations": step_d_raw.get("limitations", []) if isinstance(step_d_raw.get("limitations"), list) else [],
        "invalidation_conditions": step_d_raw.get("invalidation_conditions", [])
        if isinstance(step_d_raw.get("invalidation_conditions"), list)
        else [],
        "evidence_ids": _sanitize_ids(step_d_raw.get("evidence_ids", []), known_ids),
    }
    follow_up_watchpoints = (
        [w for w in step_d_raw.get("follow_up_watchpoints", []) if isinstance(w, str)]
        if isinstance(step_d_raw.get("follow_up_watchpoints"), list)
        else []
    )
    _log("step_d_conclusion", "ok", f"confidence={conclusion['confidence']}")

    # L5：數值信心分數
    contradictions_count = len(cross_validation.get("contradictions", []))
    score, breakdown = compute_confidence_score(
        conclusion.get("confidence", "低"),
        evidences,
        contradictions_count,
    )
    if logger:
        logger.log(
            phase=LogPhase.REASON,
            action="l5_confidence_score",
            detail=(
                f"score={score}, base={breakdown['base']}, auth_bonus={breakdown['auth_bonus']}, "
                f"contradiction_penalty={breakdown['contradiction_penalty']}, gap_penalty={breakdown['gap_penalty']}"
            ),
            status=LogStatus.OK,
            layer=PipelineLayer.CONCLUSION,
            metrics=breakdown,
        )

    return ReasoningResult(
        question_type=question_type,
        facts=facts,
        cross_validation=cross_validation,
        inference=inference,
        conclusion=conclusion,
        follow_up_watchpoints=follow_up_watchpoints,
        debate=debate,
        coin2=coin2,
        confidence_score=score,
    )


def run_reasoning(
    coin: str,
    question: str,
    evidences: list[Evidence],
    dry_run: bool = True,
    llm_client: LLMClient | None = None,
    log_step=None,
    coin2: str | None = None,
    logger: ExecutionLogger | None = None,
) -> ReasoningResult:
    question_type = classify_question_type(question)

    if dry_run:
        return _dry_run_reasoning(coin, question, question_type, evidences, coin2=coin2, logger=logger)

    if llm_client is None:
        raise RuntimeError("非 dry-run 模式需要傳入 llm_client。")

    return _real_reasoning(
        coin, question, question_type, evidences, llm_client, log_step=log_step, coin2=coin2, logger=logger
    )

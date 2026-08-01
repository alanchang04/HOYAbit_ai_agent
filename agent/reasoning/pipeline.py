"""四步推理鏈組裝：事實層 → 交叉驗證層 → 推論層 → 結論層。

`dry_run=True` 時回傳依實際 evidence 組成的假推理結果（不呼叫任何 LLM），
用於驗證整體 pipeline 與 report-evidence 對應檢查。
`dry_run=False` 時依序呼叫 llm_client 完成四步推理，並在每一步後
過濾掉模型可能捏造、不存在於 evidence 清單中的 evidence id（防止幻覺
引用讓 Phase 4 的報告檢查失敗、拖垮整個流程）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from agent.collectors.horizon import resolve_primary_horizon
from agent.filters.injection import is_quarantined
from agent.logging_utils import ExecutionLogger
from agent.reasoning.confidence import compute_confidence, coerce_verdict
from agent.reasoning.grounding import check_fact_grounding
from agent.reasoning.llm_client import LLMClient
from agent.reasoning.prompts import (
    SYSTEM_PROMPT,
    build_step_a_prompt,
    build_step_b_prompt,
    build_step_c_prompt,
    build_step_c1_bull_prompt,
    build_step_c1_bull_rebuttal_prompt,
    build_step_c2_bear_prompt,
    build_step_d_prompt,
    classify_question_type,
    extract_json,
)
from agent.schemas import Evidence, LogPhase, LogStatus, PipelineLayer, QuestionType

# 辯論輪數上限。多智能體辯論的增益在第 2 輪後大致飽和，再往上主要是燒 token 與延遲，
# 因此預設 2 輪（= 7 次 LLM 呼叫）。反方自報無新論點時會更早收斂。
MAX_DEBATE_ROUNDS = 2

# 開下一輪辯論所需的時間餘裕，以「上一輪實測秒數」為單位。這個係數必須同時涵蓋
# 「下一輪（正方＋反方 2 次呼叫）」與「裁判（1 次呼叫）」——gate 放行後就沒有第二個
# 檢查點，Step D 之前不再檢查 deadline，剩下的路一定會走完。
#
# 2.2 來自 2026-08-01 三題真實 Bedrock 實測：(第2輪+裁判)÷第1輪 = 1.68 / 1.91 / 2.09。
# 原本的 1.5 三題全部低估——主因是裁判的 prompt 是全場最長的（要吃完整逐字稿，
# 比較分析題達 18k 字），耗時與辯論一輪相當，但 1.5 只留了 0.5 輪的餘裕。
# 低估的後果不是「辯論被砍掉」而是「整跑超過 15 分鐘」，依命題文件執行限制第 1 條，
# 超時主辦方可停止執行或不採計產出。
DEBATE_ROUND_TIME_FACTOR = 2.2

# 發一次新 LLM 呼叫的最低時間門檻。低於此值就不再開新呼叫，直接降級——
# 15 分鐘是硬性上限（命題文件執行限制第 1 條：超時主辦方可停止執行或不採計產出），
# 「有產出但超時」比「誠實降級但準時」還糟。實測最快的辯論呼叫約 21s，取 20s。
MIN_LLM_STEP_SECONDS = 20.0

# 進辯論前要為裁判（Step D）保留的時間。沒有結論的辯論沒有價值，寧可不辯論也要有結論。
# 實測 step_d_conclusion 最慢 56.5s（6 次樣本），取約 2 倍餘裕。
STEP_D_RESERVE_SECONDS = 120.0


def _remaining(deadline: float | None) -> float | None:
    """距離硬性截止還剩幾秒；沒有設 deadline 時回 None（不限時）。"""
    return None if deadline is None else deadline - time.monotonic()


def _log_l3_metrics(
    logger: ExecutionLogger | None, evidences: list[Evidence], facts: list[dict]
) -> None:
    """記錄 L3 事實提取層的量化指標（input／kept／removed／removal_rate）。

    **被注入隔離的證據不計入 input**：它們根本沒送進 Step A，模型沒有機會引用，
    把它們算成「事實層剔除」會同時做錯兩件事——把 L2 資安層的處置記到 L3 頭上，
    並灌高 `noise_removal_rate` 這個對外的品質指標。隔離筆數改記在同一則 log 的
    `quarantined` 欄位，對帳時看得到差額從哪來。
    """
    if not logger:
        return
    scored_ids = {e.id for e in evidences if not is_quarantined(e)}
    quarantined = len(evidences) - len(scored_ids)
    input_count = len(scored_ids)
    kept_ids: set[str] = set()
    for f in facts:
        kept_ids.update(f.get("evidence_ids", []))
    # 只認在分母裡的 id：隔離筆數已排除在 input 之外，若讓它出現在分子，
    # removal_rate 會算出負數。
    kept_count = len(kept_ids & scored_ids)
    removed_count = input_count - kept_count
    removal_rate = removed_count / input_count if input_count > 0 else 0.0
    logger.log(
        phase=LogPhase.REASON,
        action="l3_fact_extraction",
        detail=(
            f"input={input_count}, kept={kept_count}, removed={removed_count}, "
            f"rate={removal_rate:.3f}"
            + (f"（另有 {quarantined} 筆因注入隔離未送入，不計入）" if quarantined else "")
        ),
        status=LogStatus.OK,
        layer=PipelineLayer.FACT,
        metrics={
            "input": input_count,
            "kept": kept_count,
            "removed": removed_count,
            "removal_rate": round(removal_rate, 4),
            "quarantined": quarantined,
        },
    )


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
    # 三維信心的完整分項（R3-12/R3-13）。report.md 與四面板都要呈現「88 分是怎麼
    # 算出來的」，不能只給最終數字——分項留在 log metrics 裡的話報告層拿不到。
    confidence_breakdown: dict = field(default_factory=dict)
    # 本次的主判斷尺度與其判定依據（R7-2/R7-7）。報告要揭露「為什麼判成這個尺度」，
    # 讀者才能檢查系統有沒有誤解題目的時間範圍。
    primary_horizon: str = "medium"
    primary_horizon_basis: str = ""


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
    primary_horizon, primary_horizon_basis = resolve_primary_horizon(question)
    by_type: dict[str, list[Evidence]] = {}
    for ev in evidences:
        # dry-run fixture 會刻意注入一筆重複轉載，讓評審在零成本模式也能看到
        # 「原始證據 → 去重後事實」的實際差異。Evidence 仍完整保留供回溯，
        # 但已標 duplicate_of 的項目不再進入事實層。
        #
        # 與正式路徑一致：被隔離的證據不進事實層，dry-run 也不例外，
        # 否則 dry-run 的產出會長得跟正式跑不一樣，測不出真實行為。
        if ev.duplicate_of is not None or is_quarantined(ev):
            continue
        by_type.setdefault(ev.source_type.value, []).append(ev)

    facts = [
        {
            "summary": f"（dry-run 假資料）{stype} 類來源共 {len(evs)} 筆證據可供參考。",
            "evidence_ids": [e.id for e in evs],
        }
        for stype, evs in by_type.items()
    ]

    # L3 metrics：事實提取層量化
    _log_l3_metrics(logger, evidences, facts)

    all_ids = [e.id for e in evidences if e.duplicate_of is None]
    coin_label = f"{coin} 與 {coin2}" if coin2 else coin

    cross_validation = {
        "consistent_signals": ["（dry-run 假資料）各來源皆無法判斷實際一致性，僅為流程驗證"],
        "contradictions": [],
        "structural_context": [],
        "direction_matrix": [],
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
        # dry-run 沒有真實辯論可摘要，維持空陣列——report.md 會走「本次未觸發
        # 正反辯論」的既有 fallback 文案，不虛構攻防內容。
        "debate_summary": [],
    }

    # L5：三維可解釋信心分數（R3）
    score, breakdown = compute_confidence(
        evidences,
        cross_validation,
        debate_adjustment=conclusion.get("debate_adjustment_raw"),
        debate_adjustment_reason=conclusion.get("debate_adjustment_reason", ""),
        primary_horizon=primary_horizon,
        debate_summary=conclusion.get("debate_summary"),
    )
    if logger:
        logger.log(
            phase=LogPhase.REASON,
            action="l5_confidence_score",
            detail=(
                f"score={score}, base={breakdown['base']}, "
                f"data={breakdown['data_confidence']}, consensus={breakdown['signal_consensus']}, "
                f"strength={breakdown['evidence_strength']}, "
                f"debate_adjustment={breakdown['debate_adjustment']}"
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
        confidence_breakdown=breakdown,
        primary_horizon=primary_horizon.value,
        primary_horizon_basis=primary_horizon_basis,
    )


def _call_json_step(
    llm_client: LLMClient, user_prompt: str, step_name: str, deadline: float | None = None
) -> dict:
    """呼叫 LLM 並解析 JSON，若第一次解析失敗，重試一次並明確要求修正格式。

    無論是 LLM 呼叫本身失敗（網路、配額、認證等）或回應無法解析為 JSON，
    一律轉成 ReasoningStepError，讓上層 orchestrator 可以統一捕捉、
    退化為誠實揭露失敗原因的報告，而不是讓整個 process 直接崩潰。

    `deadline` 是整跑的硬性截止（`time.monotonic()` 絕對值）。剩餘時間不足以
    完成一次呼叫時**直接放棄這一步**，不發新的請求——這是 15 分鐘上限的
    「不啟動」那一半保證；「不超時」那一半由 `BedrockClient` 依剩餘預算收緊
    單次 socket timeout 負責。兩邊都要有，缺一不可：只擋啟動的話，
    在截止前 1 秒發出的請求照樣能跑滿整個 read timeout。
    """
    remaining = _remaining(deadline)
    if remaining is not None and remaining < MIN_LLM_STEP_SECONDS:
        raise ReasoningStepError(
            f"{step_name} 時間預算不足（剩餘 {remaining:.1f}s < {MIN_LLM_STEP_SECONDS:.0f}s），"
            f"不再發出新的 LLM 呼叫以確保整跑不超過硬性上限"
        )
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
        remaining = _remaining(deadline)
        if remaining is not None and remaining < MIN_LLM_STEP_SECONDS:
            raise ReasoningStepError(
                f"{step_name} 回應無法解析為 JSON，且剩餘時間 {remaining:.1f}s 不足以重試"
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


_VALID_DIRECTIONS = {-1, 0, 1}


def _sanitize_direction_matrix(matrix, known_ids: set[str]) -> list[dict]:
    """清洗 Step B 的 direction_matrix：過濾非法 direction 值與不存在的 evidence id（R3-3）。

    每筆須為 {source_type: str, direction: -1|0|1, basis: [evidence_ids]}。
    direction 容忍字串整數（"1"／"-1"），但**小數一律丟棄不做四捨五入**：模型回 0.7
    （「偏多」）若截斷成 0 會變成「中性」這個明確錯誤的表態，直接排除該樣本反而
    對共識計算的傷害小。同一個 source_type 重複表態時只取第一筆，避免它在共識
    標準差裡被重複計票。
    """
    sanitized: list[dict] = []
    if not isinstance(matrix, list):
        return sanitized
    seen_types: set[str] = set()
    for row in matrix:
        if not isinstance(row, dict):
            continue
        stype = row.get("source_type")
        if not isinstance(stype, str) or not stype or stype in seen_types:
            continue
        direction = _coerce_direction(row.get("direction"))
        if direction is None:
            continue
        seen_types.add(stype)
        sanitized.append(
            {
                "source_type": stype,
                "direction": direction,
                "basis": _sanitize_ids(row.get("basis", []), known_ids),
            }
        )
    return sanitized


def _coerce_direction(raw) -> int | None:
    """把 direction 收斂成 -1/0/1；非整數值（含 bool、小數、無法解析的字串）回 None。"""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, float):
        if not raw.is_integer():
            return None
        value = int(raw)
    elif isinstance(raw, str):
        try:
            value = int(raw.strip())
        except ValueError:
            return None
    else:
        return None
    return value if value in _VALID_DIRECTIONS else None


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


def _validate_facts_grounding(
    facts: list[dict], evidences_by_id: dict[str, Evidence]
) -> tuple[list[dict], list[tuple[dict, list[str]]]]:
    """把 `_sanitize_facts()` 的產出分成通過 grounding 稽核／違規兩組。

    `_sanitize_facts()` 只驗證結構（evidence_ids 是否存在、型別是否正確），
    不驗證內容——模型只要引用一個真實存在的 evidence id，寫什麼都會被放行。
    這裡補上內容稽核（見 `agent/reasoning/grounding.py`），回傳
    (通過的 facts, [(違規的 fact, 違規原因列表), ...])。
    """
    clean: list[dict] = []
    violations: list[tuple[dict, list[str]]] = []
    for fact in facts:
        reasons = check_fact_grounding(fact, evidences_by_id)
        if reasons:
            violations.append((fact, reasons))
        else:
            clean.append(fact)
    return clean, violations


def _sanitize_debate_summary(raw, known_ids: set[str]) -> list[dict]:
    """裁判整理的辯論重點摘要（{point, evidence_ids, verdict}）。格式錯誤的條目整條丟棄
    而非整段作廢——單一條目壞掉不該讓其他 3-4 點也一起消失（R6-1 降級優先）。

    `verdict` 是逐點勝負判定，會被 `confidence.tally_debate_verdicts()` 加總成
    辯論調整值。判讀不出來的 verdict 落回 `"draw"`（0 分，不影響分數），
    而不是丟掉整點——同樣是降級優先。
    """
    sanitized: list[dict] = []
    if not isinstance(raw, list):
        return sanitized
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("point"), str) or not item["point"].strip():
            continue
        sanitized.append(
            {
                "point": item["point"],
                "evidence_ids": _sanitize_ids(item.get("evidence_ids", []), known_ids),
                "verdict": coerce_verdict(item.get("verdict")) or "draw",
            }
        )
    return sanitized


_TRUTHY_TOKENS = {"true", "yes", "y", "1", "是", "有", "有新論點"}
_FALSY_TOKENS = {"false", "no", "n", "0", "否", "沒有", "無", "無新論點"}


def _coerce_bool(value, default: bool = True) -> bool:
    """把模型回傳的布林欄位正規化。

    模型不一定會照規格回 JSON boolean——常見的是回字串 `"false"`，偶爾是中文
    「否」或數字 0。只認 `isinstance(x, bool)` 會把這些一律當成預設值，
    讓依賴這個欄位的機制悄悄失效。無法判讀時才落回 `default`。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().strip("\"'").lower()
        if token in _FALSY_TOKENS:
            return False
        if token in _TRUTHY_TOKENS:
            return True
    return default


def _union_ids(id_lists) -> list[str]:
    """跨輪次取 evidence id 聯集，保留首次出現的順序。"""
    seen: dict[str, None] = {}
    for ids in id_lists:
        for i in ids:
            seen[i] = None
    return list(seen)


def _build_debate(rounds: list[dict], stopped_reason: str) -> dict:
    """組裝 debate 契約。

    `rounds` 是多輪辯論的完整逐輪紀錄。頂層的 bull_*/bear_* 欄位是給既有下游
    （`report/builder.py`、`report/view_builder.py`、`webapp/templates/view.html`）
    的相容層，讓它們不必改動就能繼續運作：
    - 論證取**最後一輪**（經過反駁修正、最精煉的版本）
    - evidence id 取**所有輪次的聯集**，否則早期輪次引用的證據會在
      報告引用檢查與面板四的 bullish/risk 映射中被漏掉
    """
    last = rounds[-1]
    return {
        "rounds": rounds,
        "round_count": len(rounds),
        "stopped_reason": stopped_reason,
        "bull_argument": last["bull_argument"],
        "bull_evidence_ids": _union_ids(r["bull_evidence_ids"] for r in rounds),
        "bear_critique": last["bear_critique"],
        "bear_argument": last["bear_argument"],
        "bear_evidence_ids": _union_ids(r["bear_evidence_ids"] for r in rounds),
    }


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
    deadline: float | None = None,
) -> ReasoningResult:
    # 可被引用的 id **排除被注入隔離者**。證據清單會誠實揭露「哪幾筆被隔離」
    # （否則模型會誤以為證據涵蓋度比實際高），但那段揭露文字本身也把 id 送到了
    # 模型面前——若不在這裡收口，模型引用 ev-00X 時 `_sanitize_ids` 會放行，
    # 該筆的內容就會經由 report.md 的關鍵依據列重新出現在交付檔裡。
    known_ids = {e.id for e in evidences if not is_quarantined(e)}
    # 主視野由題目的時間範圍決定（R7-2）：問「最近一年」時 long/structural 才是
    # 當前訊號，五年結構資料不該被排除在共識投票外。未明示時沿用預設 medium。
    primary_horizon, primary_horizon_basis = resolve_primary_horizon(question)

    def _log(step: str, status: str, detail: str = "") -> None:
        if log_step:
            log_step(step, status, detail)

    _log(
        "primary_horizon",
        "ok",
        f"primary_horizon={primary_horizon.value}, basis={primary_horizon_basis or '（題目未明示，用預設）'}",
    )

    # Step A：事實層
    evidences_by_id = {e.id: e for e in evidences}
    step_a_prompt = build_step_a_prompt(
        coin, question, evidences, coin2=coin2, primary_horizon=primary_horizon, question_type=question_type
    )
    step_a_raw = _call_json_step(llm_client, step_a_prompt, "step_a_facts", deadline=deadline)
    facts = _sanitize_facts(step_a_raw.get("facts", []), known_ids)
    _log("step_a_facts", "ok", f"facts_count={len(facts)}")

    # Grounding 稽核：facts 是 Step C1/C2/D 唯一看得到的內容（見
    # `format_evidence_weight_index()`），原始證據到這裡就不再流入下游，
    # Step A 若把數值/指標寫錯，沒有任何下游機制能發現或修正。每筆 fact
    # 引用的數值/指標都要能在它自己宣稱的 evidence_ids 內容裡找到，找不到
    # 就退回重試一次；重試後仍違規就直接捨棄該筆 fact（R6-1 降級優先——
    # 寧可少一筆事實，不可讓一筆有毒的事實流進 Step B/C）。
    facts, violations = _validate_facts_grounding(facts, evidences_by_id)
    violations_found = len(violations)
    recovered = 0
    dropped = 0
    if violations:
        remaining = _remaining(deadline)
        if remaining is not None and remaining < MIN_LLM_STEP_SECONDS:
            dropped = len(violations)
            _log(
                "step_a_grounding_check",
                "skipped",
                f"{dropped} 筆 fact 未通過 grounding 稽核，剩餘時間不足以重試，直接捨棄",
            )
        else:
            violations_text = "\n".join(
                f"- {fact.get('summary', '')}（違規原因：{'; '.join(reasons)}）"
                for fact, reasons in violations
            )
            retry_prompt = (
                f"{step_a_prompt}\n\n"
                f"你上一次的回應裡，以下事實引用了證據中不存在的數值或指標，已被拒絕：\n"
                f"{violations_text}\n\n"
                f"請只重新產生這幾筆對應類別的事實，且只能使用來源證據的原文數值/措辭，"
                f"不可換算單位、代換統計量、或提及來源未提供的指標。"
                f"其餘沒有問題的事實不用重複輸出，仍然只輸出合法 JSON，格式與原本相同。"
            )
            try:
                retry_raw = _call_json_step(
                    llm_client, retry_prompt, "step_a_facts_grounding_retry", deadline=deadline
                )
                retried_facts = _sanitize_facts(retry_raw.get("facts", []), known_ids)
                retried_clean, retried_violations = _validate_facts_grounding(
                    retried_facts, evidences_by_id
                )
                facts.extend(retried_clean)
                recovered = len(retried_clean)
                dropped = len(retried_violations)
            except ReasoningStepError as exc:
                dropped = len(violations)
                _log("step_a_facts_grounding_retry", "error", f"重試失敗，捨棄違規 fact: {exc}")

            if dropped:
                _log(
                    "step_a_grounding_check",
                    "skipped",
                    f"{dropped} 筆 fact 重試後仍未通過 grounding 稽核，已捨棄",
                )

    if logger:
        logger.log(
            phase=LogPhase.REASON,
            action="l3_grounding_check",
            detail=(
                f"violations_found={violations_found}, recovered_by_retry={recovered}, "
                f"dropped={dropped}"
            ),
            status=LogStatus.OK,
            layer=PipelineLayer.FACT,
            metrics={
                "violations_found": violations_found,
                "recovered_by_retry": recovered,
                "dropped": dropped,
            },
        )
    if violations_found:
        _log("step_a_facts", "ok", f"facts_count_after_grounding={len(facts)}")

    # L3 metrics：事實提取層量化
    _log_l3_metrics(logger, evidences, facts)

    # Step B：交叉驗證層
    step_b_raw = _call_json_step(
        llm_client,
        build_step_b_prompt(
            coin,
            question,
            evidences,
            facts,
            coin2=coin2,
            primary_horizon=primary_horizon,
            question_type=question_type,
        ),
        "step_b_cross_validation",
        deadline=deadline,
    )
    cross_validation = {
        "consistent_signals": step_b_raw.get("consistent_signals", []) if isinstance(step_b_raw.get("consistent_signals"), list) else [],
        "contradictions": step_b_raw.get("contradictions", []) if isinstance(step_b_raw.get("contradictions"), list) else [],
        # horizon-aware R2-5/R2-7：跨尺度落差寫在 structural_context，不進 contradictions、不扣分。
        # 解析失敗各自降級為 []（R6-1 降級優先），不中斷推理。
        "structural_context": step_b_raw.get("structural_context", []) if isinstance(step_b_raw.get("structural_context"), list) else [],
        # R3-3：方向共識矩陣，sanitize 掉非法 direction 值與幻覺 evidence id。
        "direction_matrix": _sanitize_direction_matrix(step_b_raw.get("direction_matrix", []), known_ids),
    }
    _log(
        "step_b_cross_validation",
        "ok",
        f"consistent={len(cross_validation['consistent_signals'])}, "
        f"contradictions={len(cross_validation['contradictions'])}, "
        f"structural_context={len(cross_validation['structural_context'])}, "
        f"direction_matrix={len(cross_validation['direction_matrix'])}",
    )

    # L4 metrics：交叉驗證層量化
    if logger:
        consistent_count = len(cross_validation.get("consistent_signals", []))
        contradiction_count = len(cross_validation.get("contradictions", []))
        structural_count = len(cross_validation.get("structural_context", []))
        direction_count = len(cross_validation.get("direction_matrix", []))
        logger.log(
            phase=LogPhase.REASON,
            action="l4_cross_validation",
            detail=(
                f"consistent={consistent_count}, contradictions={contradiction_count}, "
                f"structural_context={structural_count}, direction_matrix={direction_count}"
            ),
            status=LogStatus.OK,
            layer=PipelineLayer.CROSS,
            metrics={
                "consistent": consistent_count,
                "contradictions": contradiction_count,
                "structural_context": structural_count,
                "direction_matrix": direction_count,
            },
        )

    # Step C：推論層，改為正方 vs 反方辯論（提升對抗性，避免單一模型自問自答式的假辯論）。
    # C1 / C2 的失敗分開處理：C1 失敗時沒有任何論證可留，整段退回單模型；C2 失敗時
    # 正方論證已經花掉一次呼叫且內容完好，丟掉重跑是浪費——改為保留它並用單模型
    # 補齊對立假設，讓裁判仍拿得到雙向觀點。兩種情況都不會中斷整條推理鏈。
    def _fallback_inference() -> list[dict]:
        step_c_raw = _call_json_step(
            llm_client,
            build_step_c_prompt(
                coin, question, question_type, facts, cross_validation,
                coin2=coin2, evidences=evidences,
            ),
            "step_c_inference_fallback",
            deadline=deadline,
        )
        hypotheses = _sanitize_inference(step_c_raw.get("inference", []), known_ids)
        _log("step_c_inference_fallback", "ok", f"hypotheses_count={len(hypotheses)}")
        return hypotheses

    def _run_bull(round_no: int, prior_rounds: list[dict]) -> tuple[str, list[str]]:
        step = f"step_c1_bull_r{round_no}"
        if round_no == 1:
            prompt = build_step_c1_bull_prompt(
                coin, question, question_type, facts, cross_validation,
                coin2=coin2, evidences=evidences,
            )
        else:
            prompt = build_step_c1_bull_rebuttal_prompt(
                coin, question, question_type, facts, cross_validation, prior_rounds,
                coin2=coin2, round_no=round_no, evidences=evidences,
            )
        raw = _call_json_step(llm_client, prompt, step, deadline=deadline)
        argument = raw.get("argument", "")
        ids = _sanitize_ids(raw.get("evidence_ids", []), known_ids)
        _log(step, "ok", f"evidence_count={len(ids)}")
        return argument, ids

    def _run_bear(round_no: int, bull_arg: str, prior_rounds: list[dict]) -> tuple[str, str, list[str], bool]:
        step = f"step_c2_bear_r{round_no}"
        raw = _call_json_step(
            llm_client,
            build_step_c2_bear_prompt(
                coin, question, question_type, facts, cross_validation, bull_arg,
                coin2=coin2, rounds=prior_rounds, round_no=round_no, evidences=evidences,
            ),
            step,
            deadline=deadline,
        )
        argument = raw.get("argument", "")
        critique = raw.get("critique", "")
        ids = _sanitize_ids(raw.get("evidence_ids", []), known_ids)
        # 欄位缺漏或無法判讀時預設繼續辯論——輪數本來就有上限，寧可多跑一輪也不要
        # 因為模型漏填欄位就把辯論悄悄砍成單輪。
        has_new = _coerce_bool(raw.get("has_new_points"), default=True)
        _log(step, "ok", f"evidence_count={len(ids)}, has_new_points={has_new}")
        return critique, argument, ids, has_new

    debate: dict = {}
    rounds: list[dict] = []
    inference: list[dict] = []
    stopped_reason = ""
    bull_argument = ""
    bull_evidence_ids: list[str] = []

    # 進辯論前先確認裁判的時間留得住。辯論至少要 2 次呼叫，裁判再 1 次；
    # 剩餘時間不足以走完「一輪辯論 + 裁判」時**整段跳過辯論**直接進結論——
    # 沒有結論的辯論沒有價值，而超時的產出主辦方可以不採計。
    debate_budget = _remaining(deadline)
    if debate_budget is not None and debate_budget < STEP_D_RESERVE_SECONDS + 2 * MIN_LLM_STEP_SECONDS:
        _log(
            "step_c_debate_skipped",
            "skipped",
            f"剩餘 {debate_budget:.1f}s 不足以走完「一輪辯論＋裁判」"
            f"（需 {STEP_D_RESERVE_SECONDS + 2 * MIN_LLM_STEP_SECONDS:.0f}s），"
            f"整段跳過辯論直接進裁判",
        )
        stopped_reason = "deadline"
        bull_opened = False
        skip_debate = True
    else:
        skip_debate = False

    # 第 1 輪的正方呼叫發生在迴圈外，但它一樣是「第 1 輪的成本」。計時起點必須拉到
    # 這裡，否則 `last_round_seconds` 只涵蓋反方，把一輪的成本低估四成左右
    # （2026-08-01 實測：round-1 量到 31.95s，實際 bull 20.7 + bear 31.9 = 52.6s），
    # 而那個值正是下一輪 deadline gate 的分母。
    first_round_started = time.monotonic()
    if not skip_debate:
        try:
            bull_argument, bull_evidence_ids = _run_bull(1, rounds)
            bull_opened = True
        except ReasoningStepError as exc:
            _log("step_c1_bull_r1", "error", f"正方首輪論證失敗，整段退回單模型推論: {exc}")
            bull_opened = False

    if skip_debate:
        # 連單模型 fallback 都不發——那也是一次 LLM 呼叫，而這條路徑的前提就是
        # 時間只夠給裁判。推論層留空，裁判仍拿得到事實層與交叉驗證層。
        inference = []
    elif not bull_opened:
        inference = _fallback_inference()
    else:
        last_round_seconds = 0.0
        for round_no in range(1, MAX_DEBATE_ROUNDS + 1):
            # 時間預算：一輪要花 2 次呼叫（正方＋反方），裁判還需要 1 次，所以要再開
            # 一輪至少得剩下「上一輪實測時間 × DEBATE_ROUND_TIME_FACTOR」。不夠就收在
            # 當輪，把時間留給裁判——沒有結論的辯論沒有價值。
            # 第一輪不檢查：沒有它就沒有任何辯論可言。
            if round_no > 1 and deadline is not None:
                remaining = deadline - time.monotonic()
                needed = last_round_seconds * DEBATE_ROUND_TIME_FACTOR
                if remaining < needed:
                    stopped_reason = "deadline"
                    _log(
                        "step_c_debate_deadline",
                        "skipped",
                        f"剩餘 {remaining:.1f}s < 需要 {needed:.1f}s，"
                        f"以已完成的 {len(rounds)} 輪進入裁判",
                    )
                    break

            round_started = first_round_started if round_no == 1 else time.monotonic()
            if round_no > 1:
                try:
                    bull_argument, bull_evidence_ids = _run_bull(round_no, rounds)
                except ReasoningStepError as exc:
                    stopped_reason = "bull_failed"
                    _log(
                        f"step_c1_bull_r{round_no}",
                        "error",
                        f"正方反駁失敗，以已完成的 {len(rounds)} 輪進入裁判: {exc}",
                    )
                    break
            try:
                bear_critique, bear_argument, bear_evidence_ids, has_new_points = _run_bear(
                    round_no, bull_argument, rounds
                )
            except ReasoningStepError as exc:
                stopped_reason = "bear_failed"
                _log(
                    f"step_c2_bear_r{round_no}",
                    "error",
                    f"反方論證失敗，已完成 {len(rounds)} 輪: {exc}",
                )
                break

            rounds.append(
                {
                    "round": round_no,
                    "bull_argument": bull_argument,
                    "bull_evidence_ids": bull_evidence_ids,
                    "bear_critique": bear_critique,
                    "bear_argument": bear_argument,
                    "bear_evidence_ids": bear_evidence_ids,
                    "bear_has_new_points": has_new_points,
                }
            )
            last_round_seconds = time.monotonic() - round_started

            if not has_new_points:
                stopped_reason = "converged"
                break
        else:
            stopped_reason = "max_rounds"

        if rounds:
            debate = _build_debate(rounds, stopped_reason)
            inference = [
                {
                    "hypothesis": f"[正方] {debate['bull_argument']}",
                    "supporting_evidence_ids": debate["bull_evidence_ids"],
                    "opposing_evidence_ids": debate["bear_evidence_ids"],
                },
                {
                    "hypothesis": f"[反方] {debate['bear_argument']}",
                    "supporting_evidence_ids": debate["bear_evidence_ids"],
                    "opposing_evidence_ids": debate["bull_evidence_ids"],
                },
            ]
            _log(
                "step_c_debate",
                "ok",
                f"rounds={len(rounds)}, stopped_reason={stopped_reason}",
            )
            if logger:
                logger.log(
                    phase=LogPhase.REASON,
                    action="l5_debate_rounds",
                    detail=f"rounds={len(rounds)}, stopped_reason={stopped_reason}",
                    status=LogStatus.OK,
                    layer=PipelineLayer.CONCLUSION,
                    metrics={"rounds": len(rounds), "stopped_reason": stopped_reason},
                )
        else:
            # 首輪反方就失敗：正方論證仍然有效，保留它並補上單模型的多假設。
            # debate 維持空 dict——單方面的「辯論」不成立，報告與四面板不該把它
            # 呈現成完整辯論（也避免 view_builder 走進 debate 分支而讓風險證據消失）。
            inference = [
                {
                    "hypothesis": f"[正方] {bull_argument}",
                    "supporting_evidence_ids": bull_evidence_ids,
                    "opposing_evidence_ids": [],
                }
            ] + _fallback_inference()

    # Step D：結論層
    step_d_raw = _call_json_step(
        llm_client,
        build_step_d_prompt(
            coin, question, question_type, facts, cross_validation, inference,
            coin2=coin2, debate=debate, evidences=evidences,
        ),
        "step_d_conclusion",
        deadline=deadline,
    )
    conclusion = {
        "market_judgment": step_d_raw.get("market_judgment", ""),
        "confidence": step_d_raw.get("confidence", "低"),
        "limitations": step_d_raw.get("limitations", []) if isinstance(step_d_raw.get("limitations"), list) else [],
        "invalidation_conditions": step_d_raw.get("invalidation_conditions", [])
        if isinstance(step_d_raw.get("invalidation_conditions"), list)
        else [],
        "evidence_ids": _sanitize_ids(step_d_raw.get("evidence_ids", []), known_ids),
        # 裁判整理的辯論重點摘要（3-5 點，各點附 evidence id）。fallback 路徑
        # （無辯論）prompt 已要求輸出空陣列，這裡不用另外分支處理。
        "debate_summary": _sanitize_debate_summary(step_d_raw.get("debate_summary", []), known_ids),
        # 裁判的辯論後信心調整：這裡只原樣接住，夾值（-15~+5）與「無理由視為 0」
        # 的規則屬於信心公式（design.md §3.6.4），由 Phase 4 的 compute_confidence()
        # 處理。先接住是因為不接的話模型產出後會被整段丟棄，白花 token 又沒人發現。
        "debate_adjustment_raw": step_d_raw.get("debate_adjustment"),
        "debate_adjustment_reason": (
            step_d_raw.get("debate_adjustment_reason", "")
            if isinstance(step_d_raw.get("debate_adjustment_reason"), str)
            else ""
        ),
    }
    follow_up_watchpoints = (
        [w for w in step_d_raw.get("follow_up_watchpoints", []) if isinstance(w, str)]
        if isinstance(step_d_raw.get("follow_up_watchpoints"), list)
        else []
    )
    _log("step_d_conclusion", "ok", f"confidence={conclusion['confidence']}")

    # L5：三維可解釋信心分數（R3）
    score, breakdown = compute_confidence(
        evidences,
        cross_validation,
        debate_adjustment=conclusion.get("debate_adjustment_raw"),
        debate_adjustment_reason=conclusion.get("debate_adjustment_reason", ""),
        primary_horizon=primary_horizon,
        debate_summary=conclusion.get("debate_summary"),
    )
    if logger:
        logger.log(
            phase=LogPhase.REASON,
            action="l5_confidence_score",
            detail=(
                f"score={score}, base={breakdown['base']}, "
                f"data={breakdown['data_confidence']}, consensus={breakdown['signal_consensus']}, "
                f"strength={breakdown['evidence_strength']}, "
                f"debate_adjustment={breakdown['debate_adjustment']}"
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
        confidence_breakdown=breakdown,
        primary_horizon=primary_horizon.value,
        primary_horizon_basis=primary_horizon_basis,
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
    deadline: float | None = None,
) -> ReasoningResult:
    """執行四步推理鏈。

    `deadline` 是 `time.monotonic()` 的絕對值，用來在多輪辯論之間做時間預算控制；
    傳 None 代表不限時（測試與 dry-run 皆如此）。
    """
    question_type = classify_question_type(question)

    if dry_run:
        return _dry_run_reasoning(coin, question, question_type, evidences, coin2=coin2, logger=logger)

    if llm_client is None:
        raise RuntimeError("非 dry-run 模式需要傳入 llm_client。")

    return _real_reasoning(
        coin, question, question_type, evidences, llm_client,
        log_step=log_step, coin2=coin2, logger=logger, deadline=deadline,
    )

"""四步推理鏈組裝：事實層 → 交叉驗證層 → 推論層 → 結論層。

Stage 1：`dry_run=True` 時回傳依實際 evidence 組成的假推理結果，
用於驗證整體 pipeline 與 report-evidence 對應檢查。
Stage 3：`dry_run=False` 時將接上 Bedrock 呼叫，依 prompts.py 的
四步驟分別呼叫並解析回應（目前為骨架，尚未實作）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.reasoning.prompts import classify_question_type
from agent.schemas import Evidence, QuestionType


@dataclass
class ReasoningResult:
    question_type: QuestionType
    facts: list[dict] = field(default_factory=list)
    cross_validation: dict = field(default_factory=dict)
    inference: list[dict] = field(default_factory=list)
    conclusion: dict = field(default_factory=dict)


def _dry_run_reasoning(coin: str, question: str, question_type: QuestionType, evidences: list[Evidence]) -> ReasoningResult:
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

    all_ids = [e.id for e in evidences]

    return ReasoningResult(
        question_type=question_type,
        facts=facts,
        cross_validation={
            "consistent_signals": ["（dry-run 假資料）各來源皆無法判斷實際一致性，僅為流程驗證"],
            "contradictions": [],
        },
        inference=[
            {
                "hypothesis": f"（dry-run 假資料）{coin} 市場狀態假設",
                "supporting_evidence_ids": all_ids[:1],
                "opposing_evidence_ids": [],
            }
        ],
        conclusion={
            "market_judgment": f"（dry-run 假資料，非真實分析）針對「{question}」，{coin} 的市場判斷待正式資料與 Bedrock 推理補上。",
            "confidence": "低",
            "limitations": ["本次為 --dry-run 假資料流程，未使用真實市場資料與 LLM 推理"],
            "invalidation_conditions": ["正式執行並取得真實資料後，本假結論應被取代"],
            "evidence_ids": all_ids,
        },
    )


def run_reasoning(
    coin: str,
    question: str,
    evidences: list[Evidence],
    dry_run: bool = True,
    bedrock_client=None,
) -> ReasoningResult:
    question_type = classify_question_type(question)

    if dry_run:
        return _dry_run_reasoning(coin, question, question_type, evidences)

    if bedrock_client is None:
        raise RuntimeError(
            "非 dry-run 模式需要傳入 bedrock_client。真實四步推理鏈將於 Stage 3 實作。"
        )

    raise NotImplementedError(
        "真實 Bedrock 推理鏈尚未實作，將於 Stage 3 完成（事實/交叉驗證/推論/結論四步呼叫）。"
    )

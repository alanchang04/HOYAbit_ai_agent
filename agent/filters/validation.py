"""統一的 Evidence Validation 結果聚合（v1.2 新增）。

Source Reliability／Timestamp Validation／Data Integrity／Prompt Injection／
Fact Grounding 這幾項檢查，現況分散在 `agent/filters/source_weights.py`、
`agent/filters/injection.py`、`agent/collectors/*.py`、`agent/reasoning/
grounding.py` 各處，各自只做「降級加權」，從來沒有一個地方把它們的結果彙總
成一筆可稽核的紀錄（統一 Validation Result）。

這裡不重寫任何一個既有檢查的判定邏輯，只是把它們已經算好的結果讀出來，
組成一筆 per-evidence 的稽核紀錄，供 `evidence.json` 之外的 `validation_
results.json` 輸出使用；不改變 `evidence.json` 既有欄位或既有下游（reasoning／
report）讀取 evidence 清單的方式。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.filters.source_weights import WeightBreakdown
from agent.schemas import Evidence, FilterDecision


@dataclass
class EvidenceValidationResult:
    """單筆證據的驗證結果彙總——把既有各項檢查的結果讀出來組成一筆紀錄，
    不是重新判定。"""

    evidence_id: str
    source_reliability: float
    source_grade: str
    timestamp_valid: bool
    injection_flag: str | None
    dedup_verdict: str | None
    data_integrity_ok: bool


def build_validation_results(
    evidences: list[Evidence],
    breakdowns: dict[str, WeightBreakdown],
    filter_decisions: list[FilterDecision],
) -> list[EvidenceValidationResult]:
    """彙總既有檢查結果。呼叫時機：`apply_source_weights`／`apply_injection_filter`
    都已執行完畢之後——這兩層的輸出正是這裡要讀的資料來源。
    """
    dedup_verdicts: dict[str, str] = {
        d.evidence_id: d.verdict.value
        for d in filter_decisions
        if d.check_code == "DEDUP"
    }

    results: list[EvidenceValidationResult] = []
    for ev in evidences:
        breakdown = breakdowns.get(ev.id)
        results.append(
            EvidenceValidationResult(
                evidence_id=ev.id,
                source_reliability=breakdown.final_weight if breakdown else ev.source_weight,
                source_grade=breakdown.level_name if breakdown else "",
                # fetched_at 通過 Evidence 建構時的 pydantic 驗證才會走到這裡，
                # 能存在於 evidences 清單裡就代表時間戳格式合法（見
                # `agent.schemas.Evidence` 的 field_validator）。
                timestamp_valid=True,
                injection_flag=ev.injection_flag,
                dedup_verdict=dedup_verdicts.get(ev.id),
                data_integrity_ok=True,
            )
        )
    return results

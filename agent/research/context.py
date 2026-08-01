"""組裝並輸出 versioned research_context.json sidecar。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.research.feature_extraction import extract_structured_features
from agent.research.graph import build_evidence_graph
from agent.research.knowledge import knowledge_for_features
from agent.research.models import ResearchContext


def _get(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _feature_eligible(evidence: Any, validation_by_id: dict[str, Any]) -> bool:
    """Structured Features 只從可進分析的 Evidence 產生。

    duplicate 仍留在 Evidence Graph 稽核，但不重複抽 feature；invalid／prompt
    injection quarantine 同樣不可進 Feature／Knowledge 層。
    """

    if _get(evidence, "duplicate_of"):
        return False
    if str(_get(evidence, "injection_flag", "")).lower() == "high":
        return False
    explicit_status = str(_get(evidence, "validation_status", "")).lower()
    if explicit_status in {"invalid", "quarantined", "rejected", "duplicate"}:
        return False
    result = validation_by_id.get(str(_get(evidence, "id", "")))
    if result is None:
        return True
    if str(_get(result, "injection_flag", "")).lower() == "high":
        return False
    if str(_get(result, "dedup_verdict", "")).lower() == "removed":
        return False
    certificate_status = str(_get(result, "status", "")).lower()
    if certificate_status in {"invalid", "quarantined", "rejected"}:
        return False
    if certificate_status in {"validated", "degraded"}:
        return True
    return not (
        _get(result, "timestamp_valid", True) is False
        or _get(result, "data_integrity_ok", True) is False
    )


def build_research_context(
    evidences: list[Any],
    reasoning_result: Any,
    *,
    question: str = "",
    question_type: str | None = None,
    validation_results: list[Any] | None = None,
    quarantined_drafts: list[dict] | None = None,
) -> ResearchContext:
    validation_by_id = {
        str(_get(result, "evidence_id", "")): result
        for result in (validation_results or [])
        if _get(result, "evidence_id")
    }
    feature_evidences = [
        evidence for evidence in evidences if _feature_eligible(evidence, validation_by_id)
    ]
    features = extract_structured_features(feature_evidences)
    resolved_type = question_type or str(getattr(reasoning_result, "question_type", "") or "")
    return ResearchContext(
        question=question,
        question_type=resolved_type,
        structured_features=features,
        knowledge_cards=knowledge_for_features(features),
        evidence_graph=build_evidence_graph(
            evidences,
            reasoning_result,
            validation_results=validation_results,
            quarantined_drafts=quarantined_drafts,
        ),
    )


def write_research_context(
    out_dir: str | Path,
    evidences: list[Any],
    reasoning_result: Any,
    *,
    question: str = "",
    question_type: str | None = None,
    validation_results: list[Any] | None = None,
    quarantined_drafts: list[dict] | None = None,
    filename: str = "research_context.json",
) -> tuple[Path, ResearchContext]:
    """以原子 replace 寫入 sidecar；錯誤交由 orchestrator 記錄並隔離。"""

    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    context = build_research_context(
        evidences,
        reasoning_result,
        question=question,
        question_type=question_type,
        validation_results=validation_results,
        quarantined_drafts=quarantined_drafts,
    )
    path = directory / filename
    temp_path = directory / f".{filename}.tmp"
    payload = json.dumps(
        context.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    temp_path.write_text(payload + "\n", encoding="utf-8")
    temp_path.replace(path)
    return path, context


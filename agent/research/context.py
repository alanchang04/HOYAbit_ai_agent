"""組裝並輸出 versioned research_context.json sidecar。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.research.feature_extraction import extract_structured_features
from agent.research.graph import build_evidence_graph
from agent.research.knowledge import knowledge_for_features
from agent.research.models import ResearchContext


def build_research_context(
    evidences: list[Any],
    reasoning_result: Any,
    *,
    question: str = "",
    question_type: str | None = None,
) -> ResearchContext:
    features = extract_structured_features(evidences)
    resolved_type = question_type or str(getattr(reasoning_result, "question_type", "") or "")
    return ResearchContext(
        question=question,
        question_type=resolved_type,
        structured_features=features,
        knowledge_cards=knowledge_for_features(features),
        evidence_graph=build_evidence_graph(evidences, reasoning_result),
    )


def write_research_context(
    out_dir: str | Path,
    evidences: list[Any],
    reasoning_result: Any,
    *,
    question: str = "",
    question_type: str | None = None,
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


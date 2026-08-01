from __future__ import annotations

import json
from types import SimpleNamespace

from agent.orchestrator import run_pipeline
from agent.research.context import build_research_context, write_research_context
from agent.research.graph import build_evidence_graph


def _evidence(
    eid: str,
    content: str,
    *,
    status: str = "valid",
    duplicate_of: str | None = None,
    related_claims: list | None = None,
) -> dict:
    return {
        "id": eid,
        "coin": "BTC",
        "source": "test-source",
        "source_type": "price",
        "source_weight": 0.8,
        "fetched_at": "2026-08-01T00:00:00Z",
        "window_start": "2026-07-18",
        "window_end": "2026-08-01",
        "horizon_class": "medium",
        "content_reference": content,
        "related_claim": "BTC 技術面主題",
        "related_claims": related_claims or [],
        "validation_status": status,
        "validation_issues": ["test issue"] if status != "valid" else [],
        "duplicate_of": duplicate_of,
        "injection_flag": None,
        "injection_reason": "",
    }


def _reasoning_result() -> SimpleNamespace:
    return SimpleNamespace(
        question_type="hypothesis_test",
        facts=[{"summary": "BTC 動能處於中性區間", "evidence_ids": ["ev-001", "ev-002"]}],
        inference=[
            {
                "hypothesis": "目前資料未支持單一路徑推論",
                "supporting_evidence_ids": ["ev-001"],
                "opposing_evidence_ids": ["ev-003"],
            }
        ],
        conclusion={
            "market_judgment": "證據混合，應維持條件式判斷。",
            "evidence_ids": ["ev-001"],
            "debate_summary": [
                {"point": "反方指出資料缺口", "evidence_ids": ["ev-003"], "verdict": "bear_valid"}
            ],
        },
        cross_validation={
            "direction_matrix": [
                {"source_type": "price", "direction": 0, "basis": ["ev-001", "ev-003"]}
            ]
        },
        related_claims=[
            {"topic": "BTC 價格", "related_claims": ["BTC 動能處於中性區間"]}
        ],
    )


def test_graph_preserves_topics_claims_duplicates_and_quarantine() -> None:
    evidences = [
        _evidence(
            "ev-001",
            "RSI14=55.0",
            related_claims=[{"claim": "RSI 未顯示極端動能", "relation": "supports"}],
        ),
        _evidence("ev-002", "RSI14=55.0", duplicate_of="ev-001"),
        _evidence("ev-003", "惡意外部內容", status="quarantined"),
    ]
    validation_results = [
        SimpleNamespace(
            evidence_id="ev-001", source_reliability=0.8, source_grade="A",
            timestamp_valid=True, data_integrity_ok=True, injection_flag=None,
            dedup_verdict=None,
        ),
        SimpleNamespace(
            evidence_id="ev-002", source_reliability=0.2, source_grade="C",
            timestamp_valid=True, data_integrity_ok=True, injection_flag=None,
            dedup_verdict="removed",
        ),
        SimpleNamespace(
            evidence_id="ev-003", source_reliability=0.4, source_grade="B",
            timestamp_valid=True, data_integrity_ok=True, injection_flag="high",
            dedup_verdict=None,
        ),
    ]
    graph = build_evidence_graph(
        evidences,
        _reasoning_result(),
        validation_results=validation_results,
        quarantined_drafts=[
            {"index": 4, "source": "bad-source", "coin": "BTC", "reason": "invalid schema"}
        ],
    )

    assert graph.stats["evidence_nodes"] == 4
    assert graph.stats["claim_nodes"] >= 5
    assert graph.stats["topic_nodes"] == 2
    assert any(edge.relation == "duplicate_of" and edge.source == "ev-002" for edge in graph.edges)
    assert any(node.metadata.get("layer") == "claim_mapping" for node in graph.nodes)
    quarantined = next(node for node in graph.nodes if node.id == "ev-003")
    assert quarantined.metadata["validation_status"] == "quarantined"
    assert graph.stats["validation_violations"] >= 1
    assert graph.stats["validated_evidence"] == 1
    assert graph.stats["duplicate_evidence"] == 1
    assert graph.stats["quarantined_evidence"] == 1
    assert graph.stats["invalid_evidence"] == 1
    assert any(node.id == "quarantine:draft:004" for node in graph.nodes)
    assert not any(
        edge.source == "ev-002" and edge.metadata.get("validation_violation")
        for edge in graph.edges
    )
    assert any(
        edge.source == "fact-001" and edge.relation == "maps_to"
        for edge in graph.edges
    )
    topic_ids = {node.id for node in graph.nodes if node.kind == "topic"}
    assert any(
        edge.target in topic_ids and edge.relation == "about"
        for edge in graph.edges
    )


def test_unknown_evidence_ids_do_not_create_dangling_edges() -> None:
    result = _reasoning_result()
    result.facts[0]["evidence_ids"].append("ev-999")
    graph = build_evidence_graph([_evidence("ev-001", "RSI14=55.0")], result)

    assert all(edge.source != "ev-999" and edge.target != "ev-999" for edge in graph.edges)


def test_degraded_certificate_remains_feature_eligible() -> None:
    evidence = _evidence("ev-001", "RSI14=55.0")
    validation = SimpleNamespace(
        evidence_id="ev-001",
        status="DEGRADED",
        injection_flag=None,
        dedup_verdict=None,
        timestamp_valid=False,
        data_integrity_ok=False,
        source_reliability=0.8,
        source_grade="A",
    )
    context = build_research_context(
        [evidence], _reasoning_result(), validation_results=[validation]
    )
    assert any(feature.evidence_id == "ev-001" for feature in context.structured_features)


def test_research_context_is_deterministic_and_writable(tmp_path) -> None:
    evidences = [_evidence("ev-001", "RSI14=55.0，近14日日報酬波動率=2.10%")]
    result = _reasoning_result()
    first = build_research_context(evidences, result, question="BTC 的動能是否過熱？")
    second = build_research_context(evidences, result, question="BTC 的動能是否過熱？")

    assert first.model_dump() == second.model_dump()
    assert first.schema_version == "1.0"
    assert {item.name for item in first.structured_features} == {"rsi_14", "volatility_14d_pct"}

    path, written = write_research_context(
        tmp_path,
        evidences,
        result,
        question="BTC 的動能是否過熱？",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert written == first
    assert payload["schema_version"] == "1.0"
    assert payload["evidence_graph"]["stats"]["evidence_nodes"] == 1


def test_features_only_use_validated_non_duplicate_evidence() -> None:
    evidences = [
        _evidence("ev-001", "RSI14=51.0"),
        _evidence("ev-002", "RSI14=99.0", duplicate_of="ev-001"),
        _evidence("ev-003", "RSI14=88.0", status="quarantined"),
    ]
    validation_results = [
        SimpleNamespace(
            evidence_id="ev-001", timestamp_valid=True, data_integrity_ok=True,
            injection_flag=None, dedup_verdict=None,
        ),
        SimpleNamespace(
            evidence_id="ev-002", timestamp_valid=True, data_integrity_ok=True,
            injection_flag=None, dedup_verdict="removed",
        ),
        SimpleNamespace(
            evidence_id="ev-003", timestamp_valid=True, data_integrity_ok=True,
            injection_flag="high", dedup_verdict=None,
        ),
    ]
    context = build_research_context(
        evidences,
        _reasoning_result(),
        validation_results=validation_results,
    )

    assert [(feature.evidence_id, feature.value) for feature in context.structured_features] == [
        ("ev-001", 51)
    ]
    assert context.evidence_graph.stats["evidence_nodes"] == 3


def test_sidecar_contract_with_actual_v1_dry_run(tmp_path) -> None:
    run = run_pipeline(
        coin="BTC",
        question="分析 BTC 過去兩週市場表現",
        dry_run=True,
        output_dir=str(tmp_path / "run"),
    )
    path = tmp_path / "run" / "research_context.json"
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["question_type"] == "multi_source"
    assert payload["evidence_graph"]["stats"]["evidence_nodes"] == len(run.evidences)
    known_ids = {evidence.id for evidence in run.evidences}
    assert all(feature["evidence_id"] in known_ids for feature in payload["structured_features"])

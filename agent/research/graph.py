"""把 v1.2 已存在的推理關係轉成唯讀 Evidence Relationship Graph Lite。"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

from agent.research.models import EvidenceGraph, GraphEdge, GraphNode


def _get(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value or ""))


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


def _validation_status(evidence: Any, validation_result: Any = None) -> str:
    if validation_result is not None:
        explicit = str(_get(validation_result, "status", "")).lower()
        if explicit in {"validated", "degraded", "quarantined", "invalid"}:
            return explicit
        if str(_get(validation_result, "injection_flag", "")).lower() == "high":
            return "quarantined"
        if str(_get(validation_result, "dedup_verdict", "")).lower() == "removed":
            return "duplicate"
        if _get(validation_result, "timestamp_valid", True) is False:
            return "invalid"
        if _get(validation_result, "data_integrity_ok", True) is False:
            return "invalid"
        return "validated"
    explicit = _get(evidence, "validation_status")
    if explicit:
        return _enum_value(explicit).lower()
    result = _get(evidence, "validation_result")
    nested = _get(result, "status") if result is not None else None
    if nested:
        return _enum_value(nested).lower()
    if str(_get(evidence, "injection_flag", "")).lower() == "high":
        return "quarantined"
    if _get(evidence, "duplicate_of"):
        return "duplicate"
    return "valid"


def _validation_issues(evidence: Any, validation_result: Any = None) -> list[Any]:
    issues = _get(evidence, "validation_issues")
    if issues is None:
        result = _get(evidence, "validation_result")
        issues = _get(result, "issues", []) if result is not None else []
    output = list(issues) if isinstance(issues, list) else []
    injection_reason = _get(evidence, "injection_reason")
    if injection_reason and injection_reason not in output:
        output.append(injection_reason)
    if validation_result is not None:
        certificate_reasons = _get(validation_result, "reasons", [])
        if isinstance(certificate_reasons, list):
            output.extend(str(reason) for reason in certificate_reasons)
        checks = _get(validation_result, "checks", {})
        timestamp_check = checks.get("timestamp") if isinstance(checks, dict) else None
        integrity_check = checks.get("data_integrity") if isinstance(checks, dict) else None
        timestamp_failed = (
            str(_get(timestamp_check, "status", "")) == "fail"
            if timestamp_check is not None
            else _get(validation_result, "timestamp_valid", True) is False
        )
        integrity_failed = (
            str(_get(integrity_check, "status", "")) == "fail"
            if integrity_check is not None
            else _get(validation_result, "data_integrity_ok", True) is False
        )
        if timestamp_failed:
            output.append("invalid_timestamp")
        if integrity_failed:
            output.append("data_integrity_failed")
        injection_flag = _get(validation_result, "injection_flag")
        if injection_flag:
            output.append(f"injection:{injection_flag}")
        dedup_verdict = _get(validation_result, "dedup_verdict")
        if dedup_verdict:
            output.append(f"dedup:{dedup_verdict}")
    return output


def _ids(raw: Any, known: set[str]) -> list[str]:
    if not isinstance(raw, list):
        return []
    return sorted({value for value in raw if isinstance(value, str) and value in known})


def _related_claims(evidence: Any) -> list[Any]:
    claims = _get(evidence, "related_claims", [])
    return claims if isinstance(claims, list) else []


def build_evidence_graph(
    evidences: Iterable[Any],
    reasoning_result: Any,
    *,
    validation_results: Iterable[Any] | None = None,
    quarantined_drafts: Iterable[dict] | None = None,
) -> EvidenceGraph:
    """忠實轉錄既有關係；不產生新方向、不修改 reasoning_result。"""

    evidence_list = sorted(list(evidences), key=lambda item: str(_get(item, "id", "")))
    known = {str(_get(item, "id", "")) for item in evidence_list if _get(item, "id")}
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    statuses: dict[str, str] = {}
    validation_by_id = {
        str(_get(result, "evidence_id", "")): result
        for result in (validation_results or [])
        if _get(result, "evidence_id")
    }

    def add_node(node: GraphNode) -> None:
        nodes.setdefault(node.id, node)

    def add_edge(
        source: str,
        target: str,
        relation: str,
        *,
        evidence_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        edge_meta = dict(metadata or {})
        if source in statuses and statuses[source] in {"invalid", "quarantined", "rejected"}:
            edge_meta["validation_violation"] = relation not in {"duplicate_of", "about"}
            edge_meta["source_validation_status"] = statuses[source]
        edges.append(
            GraphEdge(
                source=source,
                target=target,
                relation=relation,
                evidence_ids=evidence_ids or ([source] if source in known else []),
                metadata=edge_meta,
            )
        )

    for evidence in evidence_list:
        evidence_id = str(_get(evidence, "id", ""))
        if not evidence_id:
            continue
        validation_result = validation_by_id.get(evidence_id)
        status = _validation_status(evidence, validation_result)
        statuses[evidence_id] = status
        validation_metadata = {}
        if validation_result is not None:
            checks = _get(validation_result, "checks", {})
            serialized_checks = {
                key: (
                    value.to_dict()
                    if hasattr(value, "to_dict")
                    else value.__dict__
                    if hasattr(value, "__dict__")
                    else value
                )
                for key, value in checks.items()
            } if isinstance(checks, dict) else {}
            validation_metadata = {
                "status": _get(validation_result, "status", status),
                "source_reliability": _get(validation_result, "source_reliability"),
                "source_grade": _get(validation_result, "source_grade", ""),
                "timestamp_valid": _get(validation_result, "timestamp_valid", True),
                "data_integrity_ok": _get(validation_result, "data_integrity_ok", True),
                "dedup_verdict": _get(validation_result, "dedup_verdict"),
                "checks": serialized_checks,
            }
        add_node(
            GraphNode(
                id=evidence_id,
                kind="evidence",
                label=str(_get(evidence, "content_reference", ""))[:240],
                metadata={
                    "coin": str(_get(evidence, "coin", "")),
                    "source": str(_get(evidence, "source", "")),
                    "source_type": _enum_value(_get(evidence, "source_type")),
                    "source_weight": _get(evidence, "source_weight", 0.0),
                    "validation_status": status,
                    "validation_issues": _validation_issues(evidence, validation_result),
                    "validation_result": validation_metadata,
                },
            )
        )

        topic = str(_get(evidence, "related_claim", "") or "").strip()
        if topic:
            topic_id = _stable_id("topic", f"{_get(evidence, 'coin', '')}|{topic}")
            add_node(GraphNode(id=topic_id, kind="topic", label=topic, metadata={"legacy_field": "related_claim"}))
            add_edge(evidence_id, topic_id, "about")

        for mapped in _related_claims(evidence):
            if isinstance(mapped, str):
                claim_text, relation = mapped.strip(), "supports"
            elif isinstance(mapped, dict):
                claim_text = str(mapped.get("claim") or mapped.get("text") or "").strip()
                relation = str(mapped.get("relation") or "supports").lower()
            else:
                continue
            if not claim_text:
                continue
            if relation not in {"supports", "contradicts"}:
                relation = "supports"
            claim_id = _stable_id("claim:mapped", claim_text)
            add_node(GraphNode(id=claim_id, kind="claim", label=claim_text, metadata={"layer": "claim_mapping"}))
            add_edge(evidence_id, claim_id, relation)

        duplicate_of = _get(evidence, "duplicate_of")
        if isinstance(duplicate_of, str) and duplicate_of in known:
            add_edge(evidence_id, duplicate_of, "duplicate_of")

    for draft in quarantined_drafts or []:
        index = _get(draft, "index", "unknown")
        index_text = str(index)
        suffix = f"{int(index_text):03d}" if index_text.isdigit() else index_text
        node_id = f"quarantine:draft:{suffix}"
        statuses[node_id] = "invalid"
        add_node(
            GraphNode(
                id=node_id,
                kind="evidence",
                label=str(_get(draft, "reason", "Evidence construction failed"))[:240],
                metadata={
                    "coin": str(_get(draft, "coin", "")),
                    "source": str(_get(draft, "source", "")),
                    "validation_status": "invalid",
                    "validation_issues": [str(_get(draft, "reason", "construction_failed"))],
                    "pre_schema_quarantine": True,
                },
            )
        )

    facts = _get(reasoning_result, "facts", [])
    fact_claim_ids_by_text: dict[str, list[str]] = {}
    if isinstance(facts, list):
        for index, fact in enumerate(facts, 1):
            if not isinstance(fact, dict):
                continue
            text = str(fact.get("summary", "")).strip()
            if not text:
                continue
            claim_id = f"fact-{index:03d}"
            add_node(GraphNode(id=claim_id, kind="fact", label=text, metadata={"layer": "fact"}))
            fact_claim_ids_by_text.setdefault(text, []).append(claim_id)
            for evidence_id in _ids(fact.get("evidence_ids"), known):
                add_edge(evidence_id, claim_id, "supports")

    related_claim_groups = _get(reasoning_result, "related_claims", [])
    if isinstance(related_claim_groups, list):
        for group in related_claim_groups:
            if not isinstance(group, dict):
                continue
            topic = str(group.get("topic", "")).strip()
            claims = group.get("related_claims", [])
            if not topic or not isinstance(claims, list):
                continue
            topic_id = _stable_id("topic:mapped", topic)
            add_node(
                GraphNode(
                    id=topic_id,
                    kind="topic",
                    label=topic,
                    metadata={"source": "reasoning_result.related_claims"},
                )
            )
            for claim in claims:
                claim_text = str(claim).strip()
                if not claim_text:
                    continue
                # Claim mapping must be visible as its own layer.  Earlier code reused
                # the Fact node when labels matched, collapsing Fact→Claim into one
                # opaque node and making the advertised lineage impossible to audit.
                claim_id = _stable_id("claim:grouped", f"{topic}|{claim_text}")
                add_node(
                    GraphNode(
                        id=claim_id,
                        kind="claim",
                        label=claim_text,
                        metadata={"layer": "claim_mapping"},
                    )
                )
                for fact_id in fact_claim_ids_by_text.get(claim_text, []):
                    add_edge(fact_id, claim_id, "maps_to")
                add_edge(claim_id, topic_id, "about")

    inference = _get(reasoning_result, "inference", [])
    if isinstance(inference, list):
        for index, item in enumerate(inference, 1):
            if not isinstance(item, dict):
                continue
            text = str(item.get("hypothesis", "")).strip()
            if not text:
                continue
            claim_id = f"claim:inference:{index:03d}"
            add_node(GraphNode(id=claim_id, kind="claim", label=text, metadata={"layer": "inference"}))
            for evidence_id in _ids(item.get("supporting_evidence_ids"), known):
                add_edge(evidence_id, claim_id, "supports")
            for evidence_id in _ids(item.get("opposing_evidence_ids"), known):
                add_edge(evidence_id, claim_id, "contradicts")

    conclusion = _get(reasoning_result, "conclusion", {})
    conclusion_claim_id: str | None = None
    if isinstance(conclusion, dict):
        judgment = str(conclusion.get("market_judgment", "")).strip()
        if judgment:
            claim_id = "claim:conclusion:001"
            conclusion_claim_id = claim_id
            add_node(GraphNode(id=claim_id, kind="claim", label=judgment, metadata={"layer": "conclusion"}))
            for evidence_id in _ids(conclusion.get("evidence_ids"), known):
                add_edge(evidence_id, claim_id, "supports")

        summaries = conclusion.get("debate_summary", [])
        if isinstance(summaries, list):
            for index, item in enumerate(summaries, 1):
                if not isinstance(item, dict):
                    continue
                point = str(item.get("point", "")).strip()
                if not point:
                    continue
                claim_id = f"claim:debate:{index:03d}"
                add_node(
                    GraphNode(
                        id=claim_id,
                        kind="claim",
                        label=point,
                        metadata={"layer": "debate", "verdict": item.get("verdict", "")},
                    )
                )
                for evidence_id in _ids(item.get("evidence_ids"), known):
                    add_edge(evidence_id, claim_id, "cited_by")

    # Complete the audit lineage without inventing market direction: Facts, mapped
    # Claims, hypotheses and debate verdicts are all existing reasoning outputs.
    # ``informs`` only records that they were inputs available to the final Judge.
    if conclusion_claim_id:
        for node in list(nodes.values()):
            layer = str(node.metadata.get("layer", ""))
            if node.id == conclusion_claim_id:
                continue
            if layer in {"fact", "claim_mapping", "inference", "debate"}:
                add_edge(node.id, conclusion_claim_id, "informs")

    cross_validation = _get(reasoning_result, "cross_validation", {})
    matrix = cross_validation.get("direction_matrix", []) if isinstance(cross_validation, dict) else []
    if isinstance(matrix, list):
        for row in matrix:
            if not isinstance(row, dict):
                continue
            source_type = str(row.get("source_type", "")).strip()
            direction = row.get("direction")
            if not source_type or direction not in {-1, 0, 1}:
                continue
            signal_id = f"signal:{source_type}"
            label = {-1: "negative", 0: "neutral", 1: "positive"}[direction]
            add_node(
                GraphNode(
                    id=signal_id,
                    kind="signal",
                    label=f"{source_type}: {label}",
                    metadata={"source_type": source_type, "direction": direction},
                )
            )
            for evidence_id in _ids(row.get("basis"), known):
                add_edge(
                    evidence_id,
                    signal_id,
                    "contributes_to_direction",
                    metadata={"direction": direction},
                )

    unique_edges: dict[tuple, GraphEdge] = {}
    for edge in edges:
        key = (edge.source, edge.target, edge.relation, tuple(edge.evidence_ids))
        unique_edges.setdefault(key, edge)
    ordered_edges = sorted(unique_edges.values(), key=lambda edge: (edge.source, edge.target, edge.relation))
    ordered_nodes = sorted(nodes.values(), key=lambda node: (node.kind, node.id))
    violations = sum(bool(edge.metadata.get("validation_violation")) for edge in ordered_edges)
    return EvidenceGraph(
        nodes=ordered_nodes,
        edges=ordered_edges,
        stats={
            "evidence_nodes": sum(node.kind == "evidence" for node in ordered_nodes),
            "fact_nodes": sum(node.kind == "fact" for node in ordered_nodes),
            "claim_nodes": sum(node.kind == "claim" for node in ordered_nodes),
            "topic_nodes": sum(node.kind == "topic" for node in ordered_nodes),
            "signal_nodes": sum(node.kind == "signal" for node in ordered_nodes),
            "edges": len(ordered_edges),
            "validation_violations": violations,
            "validated_evidence": sum(status in {"valid", "validated", "ok"} for status in statuses.values()),
            "degraded_evidence": sum(status == "degraded" for status in statuses.values()),
            "duplicate_evidence": sum(status == "duplicate" for status in statuses.values()),
            "quarantined_evidence": sum(status == "quarantined" for status in statuses.values()),
            "invalid_evidence": sum(status in {"invalid", "rejected"} for status in statuses.values()),
        },
    )


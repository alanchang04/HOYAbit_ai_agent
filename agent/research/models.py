"""Research sidecar 的版本化資料契約。

刻意不修改 ``agent.schemas.Evidence``，避免與 v1.2 Validation／claim mapping 的
平行開發互相衝突。正式整合時由 adapter 讀取 Evidence 的新舊欄位。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FeatureQuality(BaseModel):
    status: Literal["ok", "partial"] = "ok"
    sample_size: int | None = None
    missing_ratio: float | None = None
    notes: list[str] = Field(default_factory=list)


class StructuredFeature(BaseModel):
    id: str
    evidence_id: str
    coin: str
    name: str
    value: float | int | str | bool
    unit: str = ""
    window: str | None = None
    as_of: str | None = None
    method: str
    extraction_mode: Literal["explicit", "deterministic_parser"]
    quality: FeatureQuality = Field(default_factory=FeatureQuality)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeReference(BaseModel):
    kind: Literal["academic", "industry", "method", "official"]
    citation: str


class KnowledgeCard(BaseModel):
    feature_name: str
    category: Literal["statistical", "market", "derivatives", "onchain"]
    definition: str
    interpretation: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evidence_scope: list[str] = Field(default_factory=list)
    references: list[KnowledgeReference] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    kind: Literal["evidence", "claim", "topic", "signal"]
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: Literal[
        "supports",
        "contradicts",
        "cited_by",
        "about",
        "duplicate_of",
        "contributes_to_direction",
    ]
    evidence_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)


class ResearchContext(BaseModel):
    schema_version: str = "1.0"
    question: str = ""
    question_type: str = ""
    structured_features: list[StructuredFeature] = Field(default_factory=list)
    knowledge_cards: list[KnowledgeCard] = Field(default_factory=list)
    evidence_graph: EvidenceGraph = Field(default_factory=EvidenceGraph)


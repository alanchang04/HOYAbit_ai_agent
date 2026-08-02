"""v1.2 的低耦合 research sidecar：structured features、knowledge 與 evidence graph。"""

from agent.research.context import build_research_context, write_research_context
from agent.research.feature_extraction import extract_structured_features
from agent.research.graph import build_evidence_graph
from agent.research.knowledge import knowledge_for_features
from agent.research.models import (
    EvidenceGraph,
    GraphEdge,
    GraphNode,
    KnowledgeCard,
    ResearchContext,
    StructuredFeature,
)

__all__ = [
    "EvidenceGraph",
    "GraphEdge",
    "GraphNode",
    "KnowledgeCard",
    "ResearchContext",
    "StructuredFeature",
    "build_evidence_graph",
    "build_research_context",
    "extract_structured_features",
    "knowledge_for_features",
    "write_research_context",
]


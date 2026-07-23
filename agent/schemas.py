"""Evidence 與 Execution Log 的資料結構定義（對應命題文件的 schema 要求）。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SourceType(str, Enum):
    PRICE = "price"
    ONCHAIN = "onchain"
    NEWS = "news"
    SOCIAL = "social"
    MACRO = "macro"
    DERIVATIVES = "derivatives"


class PipelineLayer(str, Enum):
    """信任提煉管線各層標記。"""

    SOURCE = "L1_source"
    CONTENT = "L2_content"
    FACT = "L3_fact"
    CROSS = "L4_cross"
    CONCLUSION = "L5_conclusion"


class FilterVerdict(str, Enum):
    """過濾決定結果。"""

    KEPT = "kept"
    DOWNWEIGHTED = "downweighted"
    REMOVED = "removed"


class FilterDecision(BaseModel):
    """單筆證據經過濾層後的決定紀錄。"""

    evidence_id: str
    check_code: str  # "PR" | "F10" | "F9" | "SUBJ"
    verdict: FilterVerdict
    reason: str
    weight_before: float | None = None
    weight_after: float | None = None


class RunMetrics(BaseModel):
    """單次執行的整體品質指標。"""

    confidence: int = 0
    noise_removal_rate: float = 0.0
    total_tokens: int = 0
    integrity_status: str = "INTACT"  # INTACT | DEGRADED
    raw_evidence_count: int = 0
    kept_fact_count: int = 0
    degraded_reasons: list[str] = Field(default_factory=list)


class EvidenceDraft(BaseModel):
    """Collector 產出的證據草稿，尚未分配全域唯一 id（由 orchestrator 統一分配）。"""

    coin: str
    source: str
    source_url: str | None = None
    fetched_at: str
    content_reference: str
    related_claim: str
    source_type: SourceType

    # R3-1: 來源權重與 RAG 介面欄位
    source_weight: float = 0.5
    weight_reason: str = ""
    rag_verified: bool | None = None
    rag_support: str = ""

    @field_validator("fetched_at")
    @classmethod
    def _validate_iso8601(cls, v: str) -> str:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class Evidence(EvidenceDraft):
    """單筆可回溯證據，對應命題文件要求的 Evidence List schema。"""

    id: str = Field(..., pattern=r"^ev-\d{3,}$")


class LogStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    SKIPPED = "skipped"


class LogPhase(str, Enum):
    COLLECT = "collect"
    REASON = "reason"
    REPORT = "report"


class LogEntry(BaseModel):
    """execution_log.jsonl 單行紀錄格式。"""

    ts: str
    phase: LogPhase
    action: str
    detail: str = ""
    status: LogStatus

    # R3-2: 管線層標記與指標
    layer: PipelineLayer | None = None
    metrics: dict = Field(default_factory=dict)

    @field_validator("ts")
    @classmethod
    def _validate_iso8601(cls, v: str) -> str:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


QuestionType = Literal["multi_source", "hypothesis_test", "comparison"]

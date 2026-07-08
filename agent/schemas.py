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


class EvidenceDraft(BaseModel):
    """Collector 產出的證據草稿，尚未分配全域唯一 id（由 orchestrator 統一分配）。"""

    coin: str
    source: str
    source_url: str | None = None
    fetched_at: str
    content_reference: str
    related_claim: str
    source_type: SourceType

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

    @field_validator("ts")
    @classmethod
    def _validate_iso8601(cls, v: str) -> str:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


QuestionType = Literal["multi_source", "hypothesis_test", "comparison"]

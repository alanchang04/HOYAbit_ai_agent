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


class HorizonClass(str, Enum):
    """單筆證據代表的時間尺度分帶。由 collector 決定性標註（spec ADR-2），不由 LLM 推斷。

    分帶依實際查詢參數／資料範圍推導（limit／interval／t=week／days 這些自己傳出去的值）。
    「當前訊號」三帶正常參與辯論、矛盾判定與共識投票；「結構脈絡」兩帶只用來定位大週期
    位置，不參與上述三者，避免不同尺度的正常差異被誤判成矛盾（假矛盾）。
    """

    SPOT = "spot"              # 當下快照
    SHORT = "short"            # ≤7 天
    MEDIUM = "medium"          # 8–30 天（主視野）
    LONG = "long"              # 31–180 天
    STRUCTURAL = "structural"  # >180 天


# 當前訊號三帶：參與辯論、矛盾判定與共識投票
CURRENT_SIGNAL_HORIZONS: set[HorizonClass] = {
    HorizonClass.SPOT,
    HorizonClass.SHORT,
    HorizonClass.MEDIUM,
}
# 結構脈絡兩帶：只定位大週期位置，不參與矛盾判定與共識投票
STRUCTURAL_HORIZONS: set[HorizonClass] = {
    HorizonClass.LONG,
    HorizonClass.STRUCTURAL,
}
# 主視野：一次分析的主判斷尺度，固定為 medium（8–30 天），對應命題「過去兩週」尺度
PRIMARY_HORIZON: HorizonClass = HorizonClass.MEDIUM


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
    check_code: str  # "PR" | "F10" | "F9" | "SUBJ" | "DEDUP"
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

    # R12-1: Phase 2 去重 metadata（news/social 依 (coin, source_type) 群組計算，
    # 隨證據一併保存進 evidence.json；非敘事類證據維持 None）
    dedup_raw_count: int | None = None
    dedup_deduped_count: int | None = None
    dedup_rate: float | None = None
    duplicate_of: str | None = None  # 被去重剔除時，指向保留的那筆證據 id

    # horizon-aware R2: 時間尺度標註（由 collector 決定性填入，見 .kiro/steering/horizon-annotation.md）
    # window_end ≠ fetched_at：前者是「觀察涵蓋到哪一天」，後者是「何時抓的」。
    # 官方 CSV 證據的 fetched_at 是執行日，但 window_end 是 CSV 末日——這兩個值不同正是本欄位存在的理由。
    # 皆有預設值以滿足向後相容（舊 evidence.json 無這三欄位仍可正常載入，R2-9）。
    window_start: str | None = None
    window_end: str | None = None
    horizon_class: HorizonClass = HorizonClass.SPOT

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

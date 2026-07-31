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

    SPOT = "spot"              # 當下快照或最近 1 日 —— 標準粒度「日」
    SHORT = "short"            # ≤10 天 —— 標準粒度「10 日」
    MEDIUM = "medium"          # 11–30 天 —— 標準粒度「月」（預設主視野）
    LONG = "long"              # 31–180 天 —— 標準粒度「季」
    STRUCTURAL = "structural"  # >180 天 —— 標準粒度「年」


# 由短到長排序；角色推導與大小比較都以此為準（R7-3）
HORIZON_ORDER: list[HorizonClass] = [
    HorizonClass.SPOT,
    HorizonClass.SHORT,
    HorizonClass.MEDIUM,
    HorizonClass.LONG,
    HorizonClass.STRUCTURAL,
]

# 五檔標準粒度 → 回看天數（R7-1）。與上面五帶一一對應。
HORIZON_STANDARD_DAYS: dict[HorizonClass, int] = {
    HorizonClass.SPOT: 1,
    HorizonClass.SHORT: 10,
    HorizonClass.MEDIUM: 30,
    HorizonClass.LONG: 90,
    HorizonClass.STRUCTURAL: 365,
}

# 分帶上界（天）：用於「回看 N 天 → 哪一帶」的換算，與 R2-1 的邊界一致。
_HORIZON_UPPER_BOUND_DAYS: list[tuple[int, HorizonClass]] = [
    (1, HorizonClass.SPOT),
    (10, HorizonClass.SHORT),
    (30, HorizonClass.MEDIUM),
    (180, HorizonClass.LONG),
]

# 預設主視野。實際主視野由 `resolve_primary_horizon()` 依題目動態決定（R7-2）。
DEFAULT_PRIMARY_HORIZON: HorizonClass = HorizonClass.MEDIUM

# 相容性別名：主視野為 medium 時的預設分組。**新程式碼請改用 `is_current_signal()`**——
# 角色不再寫死綁定於特定帶（R7-3），問「最近一年」時 long/structural 也是當前訊號。
CURRENT_SIGNAL_HORIZONS: set[HorizonClass] = {
    HorizonClass.SPOT,
    HorizonClass.SHORT,
    HorizonClass.MEDIUM,
}
STRUCTURAL_HORIZONS: set[HorizonClass] = {
    HorizonClass.LONG,
    HorizonClass.STRUCTURAL,
}
PRIMARY_HORIZON: HorizonClass = DEFAULT_PRIMARY_HORIZON


def horizon_for_days(days: int) -> HorizonClass:
    """回看天數 → horizon 分帶（R7-1）。"""
    for upper, horizon in _HORIZON_UPPER_BOUND_DAYS:
        if days <= upper:
            return horizon
    return HorizonClass.STRUCTURAL


def is_current_signal(horizon: HorizonClass, primary: HorizonClass | None = None) -> bool:
    """`horizon ≤ 主視野` → 當前訊號；`>` → 結構脈絡（R7-3）。

    角色相對主視野推導而非寫死綁帶：題目問「最近一年」時主視野是 structural，
    此時 long/structural 帶才是當前訊號，五年結構資料不該被排除在共識投票外。
    `primary=None` 時退回預設 medium，行為與動態主視野接線前完全相同。
    """
    target = primary or DEFAULT_PRIMARY_HORIZON
    return HORIZON_ORDER.index(horizon) <= HORIZON_ORDER.index(target)


class Persistence(str, Enum):
    """訊號還有效多久（R8-1，design.md §3.9.1）。

    與 `horizon_class` 回答的是不同問題，不可混為一談：
    `horizon_class` 是「這筆觀察涵蓋多長的窗」，`persistence` 是「這個訊號
    還能信多久」。funding 費率百分位觀察窗是 30 天（horizon=medium），但訊號
    本身 1-3 天後就衰減——現行系統若不分這兩者，會把它跟 30 天新聞覆蓋
    當成同等份量的證據。
    """

    SHORT = "short"    # 有效期 ≤7 天（情緒、資金費率極值等易衰減訊號）
    MEDIUM = "medium"  # 8–30 天
    LONG = "long"      # >30 天（估值指標、結構性供給等慢變數）


class DecayPattern(str, Enum):
    """訊號失效的方式（R8-1）。與 persistence 是互補資訊：persistence 回答
    「還能信多久」，decay 回答「失效時是瞬間過期還是逐漸鈍化」。
    """

    FAST = "fast"  # 事件過後迅速失效（情緒、資金費率極值）
    SLOW = "slow"  # 逐步衰減（估值指標、結構性供給）


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
    # ⚠ 名字叫 claim，內容是**主題標籤**（「BTC 鏈上活躍度」「BTC 官方發布新聞事件」），
    # **不是方向性主張**——這裡永遠不該出現「看多／看空／利多／利空」。命名確實誤導，
    # Ken 的 v3 提案就因此判斷我們有一層會造成錨定的 Claim（見 10_v3提案評估回覆.md §三）。
    # 賽前不改名：散在 8 個 collector ＋ 18 個測試檔共 80 處引用，純改名不划算。賽後改為 `topic`。
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

    # R8-1：訊號有效期與失效方式，由 collector 決定性標註（比照 horizon_class）。
    # 預設值 medium/slow 是「不確定就保守」——寧可低估某訊號的衰減速度，
    # 也不要無根據地把它判成 short/fast 而錯誤壓低其份量。
    persistence: Persistence = Persistence.MEDIUM
    decay: DecayPattern = DecayPattern.SLOW

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

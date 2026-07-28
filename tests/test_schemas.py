import pytest
from pydantic import ValidationError

from agent.schemas import (
    CURRENT_SIGNAL_HORIZONS,
    PRIMARY_HORIZON,
    STRUCTURAL_HORIZONS,
    Evidence,
    EvidenceDraft,
    HorizonClass,
    LogEntry,
    LogPhase,
    LogStatus,
    now_iso,
)


def test_evidence_draft_valid():
    draft = EvidenceDraft(
        coin="BTC",
        source="CoinGecko",
        source_url="https://api.coingecko.com/api/v3/simple/price",
        fetched_at=now_iso(),
        content_reference="BTC 現價 65000 USDT",
        related_claim="BTC 當前報價",
        source_type="price",
    )
    assert draft.source_type.value == "price"


def test_evidence_requires_valid_id_pattern():
    with pytest.raises(ValidationError):
        Evidence(
            id="not-a-valid-id",
            coin="BTC",
            source="x",
            fetched_at=now_iso(),
            content_reference="x",
            related_claim="x",
            source_type="price",
        )


def test_evidence_valid_id():
    ev = Evidence(
        id="ev-001",
        coin="BTC",
        source="x",
        fetched_at=now_iso(),
        content_reference="x",
        related_claim="x",
        source_type="news",
    )
    assert ev.id == "ev-001"


def test_evidence_rejects_bad_timestamp():
    with pytest.raises(ValidationError):
        EvidenceDraft(
            coin="BTC",
            source="x",
            fetched_at="not-a-timestamp",
            content_reference="x",
            related_claim="x",
            source_type="macro",
        )


def test_evidence_draft_horizon_defaults():
    """horizon-aware R2-1/R2-3：新欄位有預設值，未標註時 horizon_class 落 spot、窗口為 None。"""
    draft = EvidenceDraft(
        coin="BTC",
        source="CoinGecko",
        fetched_at=now_iso(),
        content_reference="x",
        related_claim="x",
        source_type="price",
    )
    assert draft.horizon_class == HorizonClass.SPOT
    assert draft.window_start is None
    assert draft.window_end is None


def test_evidence_draft_horizon_explicit():
    """collector 顯式標註時，window_end 可與 fetched_at 不同（正是本欄位存在的理由）。"""
    draft = EvidenceDraft(
        coin="BTC",
        source="official_csv",
        fetched_at="2026-07-25T00:00:00Z",
        content_reference="MA120 位置",
        related_claim="x",
        source_type="price",
        window_start="2021-06-01",
        window_end="2026-05-31",
        horizon_class="structural",
    )
    assert draft.horizon_class == HorizonClass.STRUCTURAL
    assert draft.window_end == "2026-05-31"
    assert draft.window_end != draft.fetched_at


def test_evidence_loads_legacy_json_without_horizon():
    """R2-9 回歸：舊格式 evidence.json（無 horizon 三欄位）可正常載入為 Evidence，不拋錯。"""
    legacy = {
        "id": "ev-001",
        "coin": "BTC",
        "source": "x",
        "fetched_at": now_iso(),
        "content_reference": "x",
        "related_claim": "x",
        "source_type": "news",
    }
    ev = Evidence(**legacy)
    assert ev.horizon_class == HorizonClass.SPOT
    assert ev.window_start is None


def test_horizon_class_five_values():
    assert {h.value for h in HorizonClass} == {"spot", "short", "medium", "long", "structural"}


def test_horizon_band_membership():
    """當前訊號三帶與結構脈絡兩帶互斥且完整涵蓋五帶；主視野屬當前訊號。"""
    assert CURRENT_SIGNAL_HORIZONS == {HorizonClass.SPOT, HorizonClass.SHORT, HorizonClass.MEDIUM}
    assert STRUCTURAL_HORIZONS == {HorizonClass.LONG, HorizonClass.STRUCTURAL}
    assert CURRENT_SIGNAL_HORIZONS.isdisjoint(STRUCTURAL_HORIZONS)
    assert CURRENT_SIGNAL_HORIZONS | STRUCTURAL_HORIZONS == set(HorizonClass)
    assert PRIMARY_HORIZON in CURRENT_SIGNAL_HORIZONS
    assert PRIMARY_HORIZON == HorizonClass.MEDIUM


def test_log_entry_valid():
    entry = LogEntry(ts=now_iso(), phase=LogPhase.COLLECT, action="price_collector", detail="ok", status=LogStatus.OK)
    assert entry.status == LogStatus.OK


def test_log_entry_rejects_invalid_phase():
    with pytest.raises(ValidationError):
        LogEntry(ts=now_iso(), phase="not-a-phase", action="x", status=LogStatus.OK)

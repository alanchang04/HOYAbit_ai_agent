import pytest
from pydantic import ValidationError

from agent.schemas import Evidence, EvidenceDraft, LogEntry, LogPhase, LogStatus, now_iso


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


def test_log_entry_valid():
    entry = LogEntry(ts=now_iso(), phase=LogPhase.COLLECT, action="price_collector", detail="ok", status=LogStatus.OK)
    assert entry.status == LogStatus.OK


def test_log_entry_rejects_invalid_phase():
    with pytest.raises(ValidationError):
        LogEntry(ts=now_iso(), phase="not-a-phase", action="x", status=LogStatus.OK)

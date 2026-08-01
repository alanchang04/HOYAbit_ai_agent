from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from pipeline.update_price_history import (
    binance_klines_to_rows,
    coinbase_candles_to_rows,
    merge_extension_rows,
)


def _seconds(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def test_coinbase_candles_are_mapped_sorted_and_cut_off():
    payload = [
        [_seconds(date(2026, 8, 1)), 90, 110, 100, 105, 12],
        [_seconds(date(2026, 7, 31)), 80, 120, 95, 100, 15],
        [_seconds(date(2026, 7, 30)), 70, 115, 90, 95, 10],
    ]
    rows = coinbase_candles_to_rows(payload, date(2026, 7, 30), date(2026, 8, 1))
    assert [row["date"] for row in rows] == ["2026-07-30", "2026-07-31"]
    assert rows[-1] == {
        "date": "2026-07-31",
        "open": "95",
        "high": "120",
        "low": "80",
        "close": "100",
        "volume": "15",
    }


def test_binance_klines_are_mapped_and_open_day_is_excluded():
    complete_ms = _seconds(date(2026, 7, 31)) * 1000
    open_ms = _seconds(date(2026, 8, 1)) * 1000
    payload = [
        [complete_ms, "1", "2", "0.5", "1.5", "99"],
        [open_ms, "2", "3", "1", "2.5", "100"],
    ]
    rows = binance_klines_to_rows(payload, date(2026, 7, 31), date(2026, 8, 1))
    assert rows == [{
        "date": "2026-07-31",
        "open": "1",
        "high": "2",
        "low": "0.5",
        "close": "1.5",
        "volume": "99",
    }]


def test_merge_prefers_coinbase_and_uses_binance_for_missing_day():
    coinbase = [
        {"date": "2026-07-30", "open": "1", "high": "1", "low": "1", "close": "CB", "volume": "1"},
    ]
    binance = [
        {"date": "2026-07-30", "open": "1", "high": "1", "low": "1", "close": "BN", "volume": "1"},
        {"date": "2026-07-31", "open": "2", "high": "2", "low": "2", "close": "BN", "volume": "2"},
    ]
    rows, counts = merge_extension_rows(
        coinbase, binance, date(2026, 7, 30), date(2026, 8, 1)
    )
    assert [row["close"] for row in rows] == ["CB", "BN"]
    assert counts == {"coinbase_exchange_usd": 1, "binance_spot_usdt": 1}


def test_merge_rejects_a_gap_instead_of_silently_writing_partial_history():
    with pytest.raises(RuntimeError, match="2026-07-31"):
        merge_extension_rows([], [], date(2026, 7, 31), date(2026, 8, 1))

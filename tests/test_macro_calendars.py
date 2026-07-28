"""測試併自 pipeline/fetch_supply_calendar.py + fetch_event_calendar.py 的
供給節奏日曆／FOMC-CPI 事件日曆（純本地靜態資料 + 日期運算，零連線）。
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.collectors.macro import (
    MacroCollector,
    NEXT_HALVING_ESTIMATED_DATE,
    event_calendar_summary,
    supply_calendar_summary,
)
from agent.logging_utils import ExecutionLogger


@pytest.fixture
def mock_logger(tmp_path):
    return ExecutionLogger(tmp_path / "test.jsonl")


# --- supply_calendar_summary ---


def test_supply_calendar_summary_none_for_eth():
    # ETH 查證後確認沒有等價的固定日期供給事件，維持不掛這格
    assert supply_calendar_summary("ETH", date(2026, 7, 23)) is None


def test_supply_calendar_summary_btc_includes_days_until_halving():
    today = date(2026, 7, 23)
    summary = supply_calendar_summary("BTC", today)
    expected_days = (NEXT_HALVING_ESTIMATED_DATE - today).days
    assert "halving" in summary
    assert f"距今約{expected_days}天" in summary
    assert "2024-04-20" in summary  # 上次減半


def test_supply_calendar_summary_bnb_includes_burn_amounts():
    summary = supply_calendar_summary("BNB", date(2026, 7, 23))
    assert "quarterly_burn" in summary
    assert "2026-07-15" in summary
    assert "2026-10" in summary


def test_supply_calendar_summary_xrp_includes_escrow_release():
    summary = supply_calendar_summary("XRP", date(2026, 7, 23))
    assert "monthly_escrow_release" in summary
    assert "2026-08-01" in summary


def test_supply_calendar_summary_sol_includes_remaining_estate_position():
    summary = supply_calendar_summary("SOL", date(2026, 7, 23))
    assert "irregular_estate_liquidation" in summary
    assert "剩餘部位約4,180,000枚" in summary


def test_supply_calendar_summary_case_insensitive():
    assert supply_calendar_summary("btc", date(2026, 7, 23)) is not None


# --- event_calendar_summary ---


def test_event_calendar_summary_reports_next_fomc_and_cpi():
    # 對照流程紀錄.md 2026-07-21 實測：距下次FOMC 8天、距下次CPI 22天
    summary = event_calendar_summary("BTC", date(2026, 7, 21))
    assert "下次FOMC決議2026-07-29（8天後）" in summary
    assert "下次CPI公布2026-08-12（22天後，2026-07資料）" in summary


def test_event_calendar_summary_reports_last_event_when_available():
    summary = event_calendar_summary("BTC", date(2026, 7, 21))
    assert "上次FOMC決議2026-06-17（34天前）" in summary
    assert "上次CPI公布2026-07-14（7天前）" in summary


def test_event_calendar_summary_adds_sol_specific_event():
    summary = event_calendar_summary("SOL", date(2026, 7, 21))
    assert "SOL特有" in summary
    assert "FTX estate" in summary


def test_event_calendar_summary_adds_xrp_specific_event():
    summary = event_calendar_summary("XRP", date(2026, 7, 21))
    assert "XRP特有" in summary
    assert "2026-08-01" in summary


def test_event_calendar_summary_no_coin_specific_note_for_btc():
    summary = event_calendar_summary("BTC", date(2026, 7, 21))
    assert "特有" not in summary


# --- 併進 fetch() 之後的整合驗證 ---


def _mock_client(mock_get):
    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.mark.asyncio
async def test_fetch_includes_supply_and_event_calendar_evidence(mock_logger):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": [], "rates": {}}

    async def mock_get(url, **kwargs):
        return mock_resp

    collector = MacroCollector(mock_logger)
    with patch("agent.collectors.macro.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _mock_client(mock_get)
        evidences = await collector.fetch("BTC")

    sources = [e.source for e in evidences]
    assert any("供給節奏日曆" in s for s in sources)
    assert any("FOMC／CPI 事件日曆" in s for s in sources)


@pytest.mark.asyncio
async def test_fetch_skips_supply_calendar_for_eth_without_error(mock_logger):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": [], "rates": {}}

    async def mock_get(url, **kwargs):
        return mock_resp

    collector = MacroCollector(mock_logger)
    with patch("agent.collectors.macro.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _mock_client(mock_get)
        evidences = await collector.fetch("ETH")

    sources = [e.source for e in evidences]
    assert not any("供給節奏日曆" in s for s in sources)
    assert any("FOMC／CPI 事件日曆" in s for s in sources)  # FOMC/CPI 五幣皆有，跟供給日曆是獨立的

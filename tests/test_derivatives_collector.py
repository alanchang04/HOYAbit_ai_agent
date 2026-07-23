"""DerivativesCollector 測試：七項子來源各自的證據產出、單一子來源失敗隔離、
CME COT／選擇權 IV 的已知跳過情境（BNB 無 CME 期貨、掛牌數不足）。

打 API 的部分用 unittest.mock 攔截 httpx.AsyncClient，不連真實網路，跟
`test_macro_news_upgrade.py` 同一套 mocking 慣例。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.collectors.derivatives import DerivativesCollector, crowd_label, percentile_rank
from agent.logging_utils import ExecutionLogger
from agent.schemas import LogStatus


@pytest.fixture
def mock_logger(tmp_path):
    return ExecutionLogger(tmp_path / "test.jsonl")


def _resp(json_data):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.json.return_value = json_data
    return m


def _funding_rows(latest_rate: float, count: int = 90) -> list[dict]:
    rows = [{"fundingRate": "0.0001", "fundingTime": 1700000000000 + i} for i in range(count - 1)]
    rows.append({"fundingRate": str(latest_rate), "fundingTime": 1700000000000 + count})
    return rows


def _oi_hist_rows() -> list[dict]:
    return [
        {"timestamp": 1700000000000, "sumOpenInterest": "1000"},
        {"timestamp": 1700003600000, "sumOpenInterest": "1100"},
    ]


def _kline_rows() -> list[list]:
    return [
        [1700000000000, "10", "11", "9", "100", "1"],
        [1700003600000, "10", "11", "9", "110", "1"],
    ]


def _long_short_rows(ratio: float) -> list[dict]:
    return [
        {"timestamp": 1700000000000, "longShortRatio": "1.0"},
        {"timestamp": 1700003600000, "longShortRatio": str(ratio)},
    ]


def _exchange_info() -> dict:
    return {
        "symbols": [
            {"pair": "BTCUSD", "contractType": "CURRENT_QUARTER", "contractStatus": "TRADING",
             "symbol": "BTCUSD_240927", "deliveryDate": 9999999999999},
            {"pair": "BTCUSD", "contractType": "NEXT_QUARTER", "contractStatus": "TRADING",
             "symbol": "BTCUSD_241227", "deliveryDate": 9999999999999},
        ]
    }


def _premium_index_row(mark: float, index: float) -> list[dict]:
    return [{"markPrice": str(mark), "indexPrice": str(index)}]


def _cot_rows() -> list[dict]:
    return [
        {
            "report_date_as_yyyy_mm_dd": "2026-07-14T00:00:00.000",
            "open_interest_all": "100000",
            "asset_mgr_positions_long": "5000",
            "asset_mgr_positions_short": "2000",
            "lev_money_positions_long": "1000",
            "lev_money_positions_short": "3000",
            "change_in_asset_mgr_long": "100",
            "change_in_asset_mgr_short": "50",
            "contract_units": "5 BTC",
        }
    ]


def _options_mark_rows(coin: str) -> list[dict]:
    # OPTIONS_MIN_CONTRACTS=10、OPTIONS_MIN_POINTS_FOR_CURVE=4，掛牌數與有效
    # 報價點都要湊夠，才會走到正常產出證據的路徑（不是被門檻跳過）。
    rows = []
    for strike, delta in (
        (70, 0.1), (80, 0.2), (85, 0.3), (90, 0.4), (95, 0.5),
        (100, 0.5), (105, 0.6), (110, 0.7), (115, 0.8), (120, 0.9), (125, 0.95),
    ):
        rows.append(
            {
                "symbol": f"{coin}-260930-{strike}-C",
                "delta": str(delta),
                "markIV": "0.6",
                "bidIV": "0.58",
                "askIV": "0.62",
            }
        )
    return rows


def _options_oi_rows() -> list[dict]:
    return [
        {"symbol": "BTC-260930-100-C", "sumOpenInterest": "10"},
        {"symbol": "BTC-260930-100-P", "sumOpenInterest": "5"},
    ]


def _hyperliquid_meta() -> list:
    meta = {"universe": [{"name": "BTC"}, {"name": "ETH"}]}
    asset_ctxs = [{"funding": "0.00001"}, {"funding": "0.00002"}]
    return [meta, asset_ctxs]


def _build_router(*, funding_rate=0.0002, oi_ok=True, ls_ok=True, term_ok=True, cot_ok=True, options_ok=True, cex_dex_ok=True):
    """依 URL 分派假回應，任何一段可以關掉（回傳失敗）來測試隔離。"""

    async def mock_get(url, **kwargs):
        if "fundingRate" in url:
            if funding_rate is None:
                raise RuntimeError("simulated funding rate failure")
            return _resp(_funding_rows(funding_rate))
        if "openInterestHist" in url:
            if not oi_ok:
                raise RuntimeError("simulated oi hist failure")
            return _resp(_oi_hist_rows())
        if "/fapi/v1/openInterest" in url:
            return _resp({"openInterest": "1000", "time": 1700000000000})
        if "klines" in url:
            return _resp(_kline_rows())
        if "globalLongShortAccountRatio" in url:
            if not ls_ok:
                raise RuntimeError("simulated long/short failure")
            return _resp(_long_short_rows(1.5))
        if "topLongShortPositionRatio" in url:
            return _resp(_long_short_rows(0.8))
        if "dapi/v1/exchangeInfo" in url:
            if not term_ok:
                raise RuntimeError("simulated term structure failure")
            return _resp(_exchange_info())
        if "dapi/v1/premiumIndex" in url:
            return _resp(_premium_index_row(101.0, 100.0))
        if "publicreporting.cftc.gov" in url:
            if not cot_ok:
                raise RuntimeError("simulated cot failure")
            return _resp(_cot_rows())
        if "eapi/v1/mark" in url:
            if not options_ok:
                raise RuntimeError("simulated options failure")
            return _resp(_options_mark_rows("BTC"))
        if "eapi/v1/openInterest" in url:
            return _resp(_options_oi_rows())
        if "premiumIndex" in url and "fapi.binance.com/fapi/v1" in url:
            if not cex_dex_ok:
                raise RuntimeError("simulated cex funding failure")
            return _resp({"lastFundingRate": "0.0001"})
        raise AssertionError(f"unexpected GET url: {url}")

    async def mock_post(url, **kwargs):
        if "hyperliquid" in url:
            return _resp(_hyperliquid_meta())
        raise AssertionError(f"unexpected POST url: {url}")

    return mock_get, mock_post


def _patched_client(mock_get, mock_post):
    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def test_percentile_rank_and_crowd_label():
    series = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile_rank(5.0, series) == 100.0
    assert percentile_rank(1.0, series) == 20.0
    assert crowd_label(95.0) == "極度擁擠"
    assert crowd_label(5.0) == "極度寬鬆"
    assert crowd_label(50.0) == "中性區間"


@pytest.mark.asyncio
async def test_all_seven_subsources_produce_evidence(mock_logger):
    mock_get, mock_post = _build_router()
    collector = DerivativesCollector(mock_logger)

    with patch("agent.collectors.derivatives.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _patched_client(mock_get, mock_post)
        evidences = await collector.fetch("BTC")

    assert len(evidences) == 7
    assert all(e.source_type == "derivatives" for e in evidences)
    assert all(e.coin == "BTC" for e in evidences)

    funding_ev = next(e for e in evidences if "fundingRate" in e.source)
    assert "百分位" in funding_ev.content_reference


@pytest.mark.asyncio
async def test_cme_cot_skips_bnb_without_network_call(mock_logger):
    """BNB 沒有 CME 期貨，這項要在打 API 前就跳過，不產生證據也不報錯。"""
    mock_get, mock_post = _build_router()
    collector = DerivativesCollector(mock_logger)

    with patch("agent.collectors.derivatives.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _patched_client(mock_get, mock_post)
        evidences = await collector.fetch("BNB")

    assert not any("CFTC" in e.source for e in evidences)
    entries = mock_logger.read_all()
    assert any(
        e.status == LogStatus.SKIPPED and "cme_cot" in e.action and "BNB" in e.detail
        for e in entries
    )


@pytest.mark.asyncio
async def test_single_subsource_failure_does_not_block_others(mock_logger):
    """費率擁擠度打 API 失敗時，其他六項子來源仍要各自產出證據，不能整個 fetch() 掛掉。"""
    mock_get, mock_post = _build_router(funding_rate=None)
    collector = DerivativesCollector(mock_logger)

    with patch("agent.collectors.derivatives.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _patched_client(mock_get, mock_post)
        evidences = await collector.fetch("BTC")

    assert len(evidences) == 6
    assert not any("fundingRate" in e.source for e in evidences)
    entries = mock_logger.read_all()
    assert any(
        e.status == LogStatus.ERROR and "funding_rate_percentile" in e.action for e in entries
    )


@pytest.mark.asyncio
async def test_options_skipped_when_below_min_contracts(mock_logger):
    """掛牌合約數低於門檻時要跳過，不強行插值。"""

    async def mock_get(url, **kwargs):
        if "eapi/v1/mark" in url:
            return _resp([{"symbol": "BTC-260930-100-C", "delta": "0.5", "markIV": "0.6",
                            "bidIV": "0.58", "askIV": "0.62"}])
        raise AssertionError(f"unexpected GET url in options-only test: {url}")

    async def mock_post(url, **kwargs):
        raise AssertionError("should not reach hyperliquid in this isolated call")

    collector = DerivativesCollector(mock_logger)
    client = _patched_client(mock_get, mock_post)
    result = await collector._fetch_options_iv_skew(client, "BTC", "BTCUSDT")

    assert result is None
    entries = mock_logger.read_all()
    assert any(e.status == LogStatus.SKIPPED and "options_iv_skew" in e.action for e in entries)


@pytest.mark.asyncio
async def test_unsupported_coin_returns_empty(mock_logger):
    collector = DerivativesCollector(mock_logger)
    evidences = await collector.fetch("DOGE")
    assert evidences == []

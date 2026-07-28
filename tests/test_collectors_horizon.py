"""horizon-aware R2-2：逐 collector 斷言 `horizon_class`／觀察窗與 design.md §3.2
對照表一致。全部用 mock 或本地 CSV，不打真實 API。

這裡驗的是「標註是否決定性且正確」，不是資料內容——內容正確性由各 collector
自己既有的測試檔負責。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.collectors.derivatives import DerivativesCollector
from agent.collectors.horizon import window_back
from agent.collectors.macro import MacroCollector
from agent.collectors.news import NewsCollector
from agent.collectors.onchain import OnchainCollector
from agent.collectors.price import PriceCollector
from agent.collectors.relative import compute_relative_metrics
from agent.collectors.social import SocialCollector
from agent.logging_utils import ExecutionLogger
from agent.schemas import HorizonClass
from tests.test_derivatives_collector import _build_router, _patched_client


@pytest.fixture
def logger(tmp_path):
    return ExecutionLogger(tmp_path / "test.jsonl")


def _resp(json_data=None, text=None):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    if json_data is not None:
        m.json.return_value = json_data
    if text is not None:
        m.text = text
    return m


def _client(get=None, post=None):
    c = AsyncMock()
    if get is not None:
        c.get = get
    if post is not None:
        c.post = post
    c.__aenter__ = AsyncMock(return_value=c)
    c.__aexit__ = AsyncMock(return_value=False)
    return c


def _by_horizon(evidences) -> dict[HorizonClass, list]:
    out: dict[HorizonClass, list] = {}
    for e in evidences:
        out.setdefault(e.horizon_class, []).append(e)
    return out


def _assert_no_window(evidence):
    assert evidence.window_start is None
    assert evidence.window_end is None


# --- price ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_price_csv_evidences_split_medium_and_structural(logger):
    """CSV 那三筆：近兩週走勢＋當前動能＝medium，長均線／全歷史波動率百分位＝structural。

    拆分是本規格的核心：合成一筆的話「RSI 超買」與「現價在 5 年分佈高位」共用一個
    horizon，Step B 就會把兩者的方向差異讀成矛盾（design.md D2）。
    """
    async def failing_get(url, **kwargs):
        raise RuntimeError("本測試只驗 CSV 端的標註，外部 API 一律失敗")

    collector = PriceCollector(logger)
    with patch("agent.collectors.price.httpx.AsyncClient") as cls:
        cls.return_value = _client(get=failing_get)
        evidences = await collector.fetch("BTC")

    grouped = _by_horizon(evidences)
    assert set(grouped) == {HorizonClass.MEDIUM, HorizonClass.STRUCTURAL}
    assert len(grouped[HorizonClass.MEDIUM]) == 2
    assert len(grouped[HorizonClass.STRUCTURAL]) == 1

    structural = grouped[HorizonClass.STRUCTURAL][0]
    assert "MA120" in structural.content_reference
    assert "全歷史" in structural.content_reference
    # 結構帶窗口自 CSV 首日起算，遠長於 medium 帶
    assert structural.window_start == "2021-06-01"
    for ev in grouped[HorizonClass.MEDIUM]:
        assert "MA120" not in ev.content_reference
        assert ev.window_start > structural.window_start


@pytest.mark.asyncio
async def test_price_realtime_quote_and_perp_basis_are_spot(logger):
    async def mock_get(url, **kwargs):
        if "coingecko" in url:
            return _resp({"bitcoin": {"usd": 100.0, "usd_24h_change": 1.0, "usd_24h_vol": 10.0}})
        if "premiumIndex" in url:
            return _resp({"markPrice": "101", "indexPrice": "100", "lastFundingRate": "0.0001"})
        raise AssertionError(f"unexpected url: {url}")

    collector = PriceCollector(logger)
    with patch("agent.collectors.price.httpx.AsyncClient") as cls:
        cls.return_value = _client(get=mock_get)
        evidences = await collector.fetch("BTC")

    spot = [e for e in evidences if e.horizon_class == HorizonClass.SPOT]
    assert len(spot) == 2  # CoinGecko 報價 + 永續基差
    for ev in spot:
        _assert_no_window(ev)


# --- onchain -------------------------------------------------------------


@pytest.mark.asyncio
async def test_onchain_is_spot_without_window(logger):
    async def mock_get(url, **kwargs):
        return _resp({"data": {"blocks": 1, "mempool_transactions": 2, "transactions_24h": 3, "hashrate_24h": "4"}})

    collector = OnchainCollector(logger)
    with patch("agent.collectors.onchain.httpx.AsyncClient") as cls:
        cls.return_value = _client(get=mock_get)
        evidences = await collector.fetch("BTC")

    assert evidences
    for ev in evidences:
        assert ev.horizon_class == HorizonClass.SPOT
        _assert_no_window(ev)


# --- news ----------------------------------------------------------------


RSS_SAMPLE = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Test post</title><link>https://example.com/a</link>
<pubDate>Mon, 20 Jul 2026 00:00:00 +0000</pubDate></item>
</channel></rss>"""


@pytest.mark.asyncio
async def test_news_is_medium_with_14_day_window(logger):
    async def mock_get(url, **kwargs):
        return _resp(text=RSS_SAMPLE)

    collector = NewsCollector(logger)
    with patch("agent.collectors.news.httpx.AsyncClient") as cls:
        cls.return_value = _client(get=mock_get)
        evidences = await collector.fetch("BTC")

    assert evidences
    expected_start, expected_end = window_back(14)
    for ev in evidences:
        assert ev.horizon_class == HorizonClass.MEDIUM
        assert (ev.window_start, ev.window_end) == (expected_start, expected_end)


# --- social --------------------------------------------------------------


@pytest.mark.asyncio
async def test_social_is_short_with_7_day_window(logger):
    """Reddit 查詢帶 t=week，窗口由該參數決定性推導（ADR-2），不是猜的。"""
    async def mock_get(url, **kwargs):
        assert kwargs["params"]["t"] == "week"
        return _resp({"data": {"children": [
            {"data": {"title": "t", "score": 1, "num_comments": 2, "created_utc": 1.0, "permalink": "/p"}}
        ]}})

    collector = SocialCollector(logger)
    with patch("agent.collectors.social.httpx.AsyncClient") as cls:
        cls.return_value = _client(get=mock_get)
        evidences = await collector.fetch("BTC")

    assert evidences
    expected_start, expected_end = window_back(7)
    for ev in evidences:
        assert ev.horizon_class == HorizonClass.SHORT
        assert (ev.window_start, ev.window_end) == (expected_start, expected_end)


# --- macro ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_macro_fng_is_medium_and_fx_is_spot(logger):
    values = list(range(30, 60))

    async def mock_get(url, **kwargs):
        if "fng" in url:
            return _resp({"data": [{"value": str(v), "value_classification": "Greed"} for v in values]})
        return _resp({"date": "2026-07-25", "rates": {"EUR": 0.92, "JPY": 150.0, "GBP": 0.79}})

    collector = MacroCollector(logger)
    with patch("agent.collectors.macro.httpx.AsyncClient") as cls:
        cls.return_value = _client(get=mock_get)
        evidences = await collector.fetch("BTC")

    fng = next(e for e in evidences if "Fear & Greed" in e.source)
    assert fng.horizon_class == HorizonClass.MEDIUM
    assert (fng.window_start, fng.window_end) == window_back(len(values))

    fx = next(e for e in evidences if "Frankfurter" in e.source)
    assert fx.horizon_class == HorizonClass.SPOT
    _assert_no_window(fx)


# --- derivatives ---------------------------------------------------------


@pytest.mark.asyncio
async def test_derivatives_horizon_matches_table(logger):
    """七項子來源逐項對照 §3.2：費率百分位=medium、CME COT=long、其餘=spot。"""
    mock_get, mock_post = _build_router()
    collector = DerivativesCollector(logger)

    with patch("agent.collectors.derivatives.httpx.AsyncClient") as cls:
        cls.return_value = _patched_client(mock_get, mock_post)
        evidences = await collector.fetch("BTC")

    by_claim = {e.related_claim: e for e in evidences}

    funding = next(e for k, e in by_claim.items() if "資金費率擁擠度" in k)
    assert funding.horizon_class == HorizonClass.MEDIUM
    assert funding.window_start and funding.window_end

    cot = next(e for k, e in by_claim.items() if "CME 期貨機構淨倉位" in k)
    assert cot.horizon_class == HorizonClass.LONG
    # 窗口取實際報告日，不是 today 回推（CFTC 週報落後至當週二）
    assert cot.window_end == "2026-07-14"

    for keyword in ("四象限", "背離", "期貨到期結構", "隱含波動率", "資金費率背離"):
        ev = next(e for k, e in by_claim.items() if keyword in k)
        assert ev.horizon_class == HorizonClass.SPOT, keyword


@pytest.mark.asyncio
async def test_derivatives_intraday_spot_windows_stay_short(logger):
    """OI 四象限／多空帳戶比是 30 小時趨勢：標 spot 但帶跨日窗口，窗長不得超過 2 天，
    否則會觸發 orchestrator 的漏標警示（見 SPOT_MAX_WINDOW_DAYS）。"""
    from datetime import date

    mock_get, mock_post = _build_router()
    collector = DerivativesCollector(logger)

    with patch("agent.collectors.derivatives.httpx.AsyncClient") as cls:
        cls.return_value = _patched_client(mock_get, mock_post)
        evidences = await collector.fetch("BTC")

    for keyword in ("四象限", "持倉方向是否背離"):
        ev = next((e for e in evidences if keyword in e.related_claim), None)
        assert ev is not None, keyword
        if ev.window_start is None:
            continue
        span = (date.fromisoformat(ev.window_end) - date.fromisoformat(ev.window_start)).days + 1
        assert span <= 2, f"{keyword} 窗長 {span} 天，超過 spot 容許值"


# --- relative ------------------------------------------------------------


def test_relative_metrics_is_long():
    """雙幣 90 日相對強弱＝long（31-180 天），屬結構脈絡而非當前訊號。"""
    draft = compute_relative_metrics("BTC", "ETH")
    assert draft.horizon_class == HorizonClass.LONG
    assert draft.window_start and draft.window_end
    assert draft.window_start < draft.window_end

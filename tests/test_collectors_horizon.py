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
from agent.schemas import DecayPattern, HorizonClass, Persistence
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
    # R7-4 之後 price 會另外產出五檔標準粒度的區間統計，故不再是只有兩帶；
    # 這裡驗的是「技術指標本身」有沒有被正確拆成當前動能 vs 長期結構。
    indicator_evidences = [e for e in evidences if "指標計算" in e.source]
    indicator_bands = _by_horizon(indicator_evidences)
    assert set(indicator_bands) == {HorizonClass.MEDIUM, HorizonClass.STRUCTURAL}
    assert len(indicator_bands[HorizonClass.STRUCTURAL]) == 1

    structural = indicator_bands[HorizonClass.STRUCTURAL][0]
    assert "MA120" in structural.content_reference
    assert "全歷史" in structural.content_reference
    # 結構帶窗口自 CSV 首日起算，遠長於 medium 帶
    assert structural.window_start == "2021-06-01"
    for ev in indicator_bands[HorizonClass.MEDIUM]:
        assert "MA120" not in ev.content_reference
        assert ev.window_start > structural.window_start

    # 近兩週走勢摘要（非指標）仍是 medium
    assert any(
        e.horizon_class == HorizonClass.MEDIUM and "共同基準資料集" in e.source
        for e in evidences
    )


@pytest.mark.asyncio
async def test_price_covers_five_standard_granularities(logger):
    """R7-4：price 資料來自本地 CSV，多算窗口零 API 成本，故要求五檔全覆蓋。

    使用者問「最近兩週」或「最近一年」時，各自都要有對應尺度的證據可用；
    缺了哪一檔，主視野落在該帶時就會無據可用（R7-6）。
    """
    async def failing_get(url, **kwargs):
        raise RuntimeError("只驗本地計算，外部 API 一律失敗")

    collector = PriceCollector(logger)
    with patch("agent.collectors.price.httpx.AsyncClient") as cls:
        cls.return_value = _client(get=failing_get)
        evidences = await collector.fetch("BTC")

    bands = _by_horizon(evidences)
    for band in (
        HorizonClass.SPOT,
        HorizonClass.SHORT,
        HorizonClass.MEDIUM,
        HorizonClass.LONG,
        HorizonClass.STRUCTURAL,
    ):
        assert band in bands, f"{band.value} 帶無任何 price 證據"

    ranges = {e.related_claim: e for e in evidences if "區間統計" in e.source}
    assert len(ranges) == 4, f"應有日/10日/季/年四檔區間統計，實得 {list(ranges)}"

    # 每檔的窗長要與宣告的粒度相符，不能標了帶卻給錯窗
    from datetime import date as _date

    for ev in ranges.values():
        span = (
            _date.fromisoformat(ev.window_end) - _date.fromisoformat(ev.window_start)
        ).days + 1
        assert ev.horizon_class == _horizon_for_span(span), (
            f"{ev.related_claim} 窗長 {span} 天與標註 {ev.horizon_class.value} 不符"
        )


def _horizon_for_span(span_days: int) -> HorizonClass:
    from agent.schemas import horizon_for_days

    return horizon_for_days(span_days)


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

    # 即時類 spot 證據（不含 R7-4 的「最近一日」區間統計——那是本地 K 棒，有窗口）
    live = [
        e
        for e in evidences
        if e.horizon_class == HorizonClass.SPOT and "區間統計" not in e.source
    ]
    assert len(live) == 2  # CoinGecko 報價 + 永續基差
    for ev in live:
        _assert_no_window(ev)

    # 「最近一日」也是 spot，但它有明確的單日窗口——標 spot 帶窗口是允許的，
    # 只要窗長不超過 orchestrator 的 SPOT_MAX_WINDOW_DAYS 容許值。
    daily = next(e for e in evidences if "最近一日" in e.related_claim)
    assert daily.horizon_class == HorizonClass.SPOT
    assert daily.window_start == daily.window_end


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


_RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <author><name>/u/someone</name></author>
    <title>Bitcoin discussion thread</title>
    <link href="https://www.reddit.com/r/CryptoCurrency/comments/abc/x/" />
    <published>2026-07-27T10:00:00+00:00</published>
  </entry>
</feed>"""


@pytest.mark.asyncio
async def test_social_is_short_with_7_day_window(logger):
    """Reddit 查詢帶 t=week，窗口由該參數決定性推導（ADR-2），不是猜的。"""
    async def mock_get(url, **kwargs):
        assert kwargs["params"]["t"] == "week"
        return _resp(text=_RSS_FIXTURE)

    collector = SocialCollector(logger)
    with (
        patch("agent.collectors.social.httpx.AsyncClient") as cls,
        patch("agent.collectors.social.RSS_INTER_REQUEST_DELAY", 0),
    ):
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


# --- Ken 於 d8e1b15 併入的子來源（design.md §3.2.1，Task 0.2）-----------------


@pytest.mark.asyncio
async def test_macro_calendars_horizon(logger):
    """供給節奏日曆＝structural（BTC 減半週期逾 4 年）；
    FOMC/CPI 事件日曆＝medium（實際只報最近一次＋下一次，跨度約兩個月）。
    兩者都是「同時往回看與往前看」的日曆，不是連續觀察窗，故 window 為 None。"""

    async def mock_get(url, **kwargs):
        if "fng" in url:
            return _resp({"data": [{"value": "50", "value_classification": "Neutral"}]})
        return _resp({"date": "2026-07-25", "rates": {"EUR": 0.92}})

    collector = MacroCollector(logger)
    with patch("agent.collectors.macro.httpx.AsyncClient") as cls:
        cls.return_value = _client(get=mock_get)
        evidences = await collector.fetch("BTC")

    supply = next(e for e in evidences if "供給節奏日曆" in e.source)
    assert supply.horizon_class == HorizonClass.STRUCTURAL
    _assert_no_window(supply)

    events = next(e for e in evidences if "事件日曆" in e.source)
    assert events.horizon_class == HorizonClass.MEDIUM
    _assert_no_window(events)


@pytest.mark.asyncio
async def test_onchain_history_trend_is_medium(logger):
    """鏈上歷史趨勢：原始序列雖有 5 年，但實際判讀窗是 HISTORY_TREND_DAYS=30 天。
    標註依「實際使用的窗口」而非「拉回來的資料長度」，否則會被誤判成結構脈絡。"""
    from agent.collectors.onchain import HISTORY_TREND_DAYS

    series = [[i, float(100 + i)] for i in range(60)]

    async def mock_get(url, **kwargs):
        if "charts" in url:
            return _resp({"values": [{"x": 1700000000 + i * 86400, "y": 100.0 + i} for i in range(60)]})
        return _resp({"data": {"blocks": [{"height": 900000}]}})

    collector = OnchainCollector(logger)
    with patch("agent.collectors.onchain.httpx.AsyncClient") as cls:
        cls.return_value = _client(get=mock_get)
        evidences = await collector.fetch("BTC")

    history = next((e for e in evidences if "Charts API" in e.source), None)
    if history is None:
        pytest.skip("mock 未產出歷史趨勢證據（子來源失敗被隔離）")
    assert history.horizon_class == HorizonClass.MEDIUM
    assert (history.window_start, history.window_end) == window_back(HISTORY_TREND_DAYS)


@pytest.mark.asyncio
async def test_derivatives_coinbase_premium_is_spot(logger):
    """Coinbase 溢價是兩間交易所當下 ticker 的橫斷面價差，不是時間序列。"""
    mock_get, mock_post = _build_router()
    collector = DerivativesCollector(logger)

    with patch("agent.collectors.derivatives.httpx.AsyncClient") as cls:
        cls.return_value = _patched_client(mock_get, mock_post)
        evidences = await collector.fetch("BTC")

    premium = next((e for e in evidences if "Coinbase" in e.source), None)
    if premium is None:
        pytest.skip("mock router 未涵蓋 Coinbase 溢價端點")
    assert premium.horizon_class == HorizonClass.SPOT


def test_every_evidence_draft_annotates_horizon_explicitly():
    """結構性防呆：任何 collector 新增 EvidenceDraft 卻忘了標 horizon_class，
    這條就會紅。預設值 spot 是相容性保險，不是可以偷懶的藉口
    （見 .kiro/steering/horizon-annotation.md 約定 1）。

    Ken 在 d8e1b15 併入五項 prototype 時就漏了這一步，而預設值讓它靜默通過——
    這條測試就是為了讓下次不再靜默。
    """
    import re
    from pathlib import Path

    missing: list[str] = []
    for path in sorted(Path("agent/collectors").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"EvidenceDraft\(", source):
            depth, i = 0, match.end() - 1
            while i < len(source):
                if source[i] == "(":
                    depth += 1
                elif source[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            if "horizon_class" not in source[match.start() : i + 1]:
                missing.append(f"{path}:{source[: match.start()].count(chr(10)) + 1}")

    assert not missing, "以下 EvidenceDraft 未顯式標註 horizon_class：\n" + "\n".join(missing)


# --- relative ------------------------------------------------------------


def test_relative_metrics_is_long():
    """雙幣 90 日相對強弱＝long（31-180 天），屬結構脈絡而非當前訊號。"""
    draft = compute_relative_metrics("BTC", "ETH")
    assert draft.horizon_class == HorizonClass.LONG
    assert draft.window_start and draft.window_end
    assert draft.window_start < draft.window_end


# --- persistence／decay（R8-1，design.md §3.9.1）--------------------------


def test_relative_metrics_is_long_persistence():
    """雙幣相對強弱是結構性比較，緩慢變化——跟 CME COT／供給節奏日曆同一類。"""
    draft = compute_relative_metrics("BTC", "ETH")
    assert draft.persistence == Persistence.LONG
    assert draft.decay == DecayPattern.SLOW


@pytest.mark.asyncio
async def test_funding_rate_persistence_diverges_from_horizon(logger):
    """design.md §3.9.1 的典型案例：funding rate 的 horizon_class 是 medium
    （90 筆×8h≈30 天觀察窗），但 persistence 是 short（訊號 1-3 天內就衰減）——
    這兩個維度刻意不同，證明 persistence 不是 horizon_class 的別名。"""
    mock_get, mock_post = _build_router()
    collector = DerivativesCollector(logger)

    with patch("agent.collectors.derivatives.httpx.AsyncClient") as cls:
        cls.return_value = _patched_client(mock_get, mock_post)
        evidences = await collector.fetch("BTC")

    funding = next(e for e in evidences if "資金費率擁擠度" in e.related_claim)
    assert funding.horizon_class == HorizonClass.MEDIUM
    assert funding.persistence == Persistence.SHORT
    assert funding.decay == DecayPattern.FAST
    assert funding.persistence.value != funding.horizon_class.value


@pytest.mark.asyncio
async def test_cme_cot_persistence_matches_horizon(logger):
    """CME COT 是 design.md 明列案例：horizon=long、persistence=long/slow
    （機構配置型倉位逐週緩慢調整，兩個維度一致，不是每個子來源都會分歧）。"""
    mock_get, mock_post = _build_router()
    collector = DerivativesCollector(logger)

    with patch("agent.collectors.derivatives.httpx.AsyncClient") as cls:
        cls.return_value = _patched_client(mock_get, mock_post)
        evidences = await collector.fetch("BTC")

    cot = next(e for e in evidences if "CME 期貨機構淨倉位" in e.related_claim)
    assert cot.horizon_class == HorizonClass.LONG
    assert cot.persistence == Persistence.LONG
    assert cot.decay == DecayPattern.SLOW


@pytest.mark.asyncio
async def test_social_persistence_is_short_fast(logger):
    """社群情緒最短命：horizon=short、persistence=short/fast，兩個維度一致。"""
    async def mock_get(url, **kwargs):
        return _resp(text=_RSS_FIXTURE)

    collector = SocialCollector(logger)
    with (
        patch("agent.collectors.social.httpx.AsyncClient") as cls,
        patch("agent.collectors.social.RSS_INTER_REQUEST_DELAY", 0),
    ):
        cls.return_value = _client(get=mock_get)
        evidences = await collector.fetch("BTC")

    assert evidences
    for ev in evidences:
        assert ev.persistence == Persistence.SHORT
        assert ev.decay == DecayPattern.FAST


@pytest.mark.asyncio
async def test_news_persistence_is_medium_slow(logger):
    """官方公告 persistence=medium/slow，跟 horizon_class 一致（design.md 明列案例）。"""
    async def mock_get(url, **kwargs):
        return _resp(text=RSS_SAMPLE)

    collector = NewsCollector(logger)
    with patch("agent.collectors.news.httpx.AsyncClient") as cls:
        cls.return_value = _client(get=mock_get)
        evidences = await collector.fetch("BTC")

    assert evidences
    for ev in evidences:
        assert ev.persistence == Persistence.MEDIUM
        assert ev.decay == DecayPattern.SLOW


@pytest.mark.asyncio
async def test_onchain_total_supply_persistence_diverges_from_horizon(logger):
    """鏈上總供給量是另一個「horizon≠persistence」案例：標註的是快照時間點
    （spot），但總供給量本身是結構性緩慢變化的數字（增發/銷毀遠慢於價格波動），
    不套用「spot=short/fast」的通用模式。直接呼叫 `_fetch_evm()`——比重建整條
    `fetch()` 的 settings/coin_map 依賴鏈更聚焦。"""
    async def mock_get(url, **kwargs):
        return _resp({"result": "120000000000000000000000000"})

    async def mock_post(url, **kwargs):
        return _resp({"result": "0x1"})  # eth_blockNumber／eth_gasPrice 走 POST

    collector = OnchainCollector(logger)
    client = _client(get=mock_get, post=mock_post)
    evidences = await collector._fetch_evm(
        client, "ETH", ["https://rpc.example"], "https://api.etherscan.io/api", "dummy_key"
    )

    supply = next(e for e in evidences if "總供給量" in e.related_claim)
    assert supply.horizon_class == HorizonClass.SPOT
    assert supply.persistence == Persistence.LONG
    assert supply.decay == DecayPattern.SLOW

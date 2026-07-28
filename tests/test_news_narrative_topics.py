"""測試併自 pipeline/fetch_news.py（Step 25）的特有題材關鍵字標記。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.collectors.news import (
    GENERIC_DESCRIPTION_FALLBACKS,
    NARRATIVE_KEYWORDS,
    NewsCollector,
    strip_html,
    tag_narrative_topics,
)
from agent.logging_utils import ExecutionLogger


@pytest.fixture
def mock_logger(tmp_path):
    return ExecutionLogger(tmp_path / "test.jsonl")


def test_tag_narrative_topics_matches_title_case_insensitive():
    topics = tag_narrative_topics("BTC", "Bitcoin ETF Inflows Hit Record High")
    assert "ETF 資金流" in topics


def test_tag_narrative_topics_checks_multiple_texts_combined():
    # 標題沒提到，摘要裡才有——驗證 title + summary 是合併比對，不是只看標題
    topics = tag_narrative_topics("BNB", "Bnb chain the web3 blueprint", "New opBNB and Greenfield features live")
    assert "BNB Chain 生態升級" in topics


def test_tag_narrative_topics_no_hit_returns_empty_list():
    topics = tag_narrative_topics("BTC", "A totally unrelated headline about nothing crypto")
    assert topics == []


def test_tag_narrative_topics_unknown_coin_returns_empty_list():
    assert tag_narrative_topics("DOGE", "anything") == []


def test_strip_html_removes_tags():
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_generic_description_fallback_is_registered():
    # Ripple Insights 罐頭文字踩坑記錄，防止之後被誤刪
    assert "ripple is the leading blockchain payments company." in GENERIC_DESCRIPTION_FALLBACKS


@pytest.mark.asyncio
async def test_fetch_rss_evidence_includes_narrative_topics_note(mock_logger):
    """RSS 分支：標題命中關鍵字時，content_reference 要帶出特有題材標記。"""
    rss_xml = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>Bitcoin ETF sees record inflows this week</title>
<link>https://example.com/a</link>
<summary>Institutional demand keeps rising.</summary>
<pubDate>Mon, 01 Jun 2026 00:00:00 GMT</pubDate>
</item>
</channel></rss>"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = rss_xml

    collector = NewsCollector(mock_logger)
    with patch("agent.collectors.news.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        evidences = await collector.fetch("BTC")

    assert len(evidences) == 1
    assert "特有題材：ETF 資金流" in evidences[0].content_reference


@pytest.mark.asyncio
async def test_fetch_rss_evidence_omits_topics_note_when_no_hit(mock_logger):
    rss_xml = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>A quiet week with nothing notable</title>
<link>https://example.com/b</link>
<pubDate>Mon, 01 Jun 2026 00:00:00 GMT</pubDate>
</item>
</channel></rss>"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = rss_xml

    collector = NewsCollector(mock_logger)
    with patch("agent.collectors.news.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        evidences = await collector.fetch("BTC")

    assert len(evidences) == 1
    assert "特有題材" not in evidences[0].content_reference

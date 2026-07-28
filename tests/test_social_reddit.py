"""Reddit social collector：RSS 降級路徑與 OAuth 優先路徑。

背景（2026-07-28 實測）：Reddit 已全面封鎖未認證的 `.json` 端點——
`www`／`old` 子網域、自訂 UA 與瀏覽器 UA 一律 403，這不是雲端 IP 封鎖，
本機直連同樣被擋。仍然開放的是 `.rss`（Atom），但限流極緊：
header 明示 `x-ratelimit-used=1, remaining=0, reset=10~20`，即每個窗口只准一次。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent.collectors.social import (
    RATE_LIMIT_MAX_WAIT,
    SocialCollector,
    _retry_after_seconds,
    parse_rss_entries,
)
from agent.logging_utils import ExecutionLogger
from agent.schemas import HorizonClass

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <author><name>/u/alice</name></author>
    <title>Bitcoin breaks below MA120</title>
    <link href="https://www.reddit.com/r/CryptoCurrency/comments/a1/x/" />
    <published>2026-07-27T10:00:00+00:00</published>
  </entry>
  <entry>
    <author><name>/u/bob</name></author>
    <title>Is the bottom in?</title>
    <link href="https://www.reddit.com/r/CryptoCurrency/comments/a2/y/" />
    <updated>2026-07-26T08:30:00+00:00</updated>
  </entry>
</feed>"""


@pytest.fixture
def logger(tmp_path):
    return ExecutionLogger(tmp_path / "t.jsonl")


def _resp(status=200, text="", json_data=None, headers=None):
    m = MagicMock()
    m.status_code = status
    m.text = text
    m.headers = headers or {}
    if json_data is not None:
        m.json.return_value = json_data
    if status >= 400:
        m.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("err", request=MagicMock(), response=MagicMock())
        )
    else:
        m.raise_for_status = MagicMock()
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


class TestRssParsing:
    def test_extracts_title_link_author_published(self):
        entries = parse_rss_entries(RSS_XML)
        assert len(entries) == 2
        assert entries[0]["title"] == "Bitcoin breaks below MA120"
        assert entries[0]["author"] == "/u/alice"
        assert entries[0]["published"].startswith("2026-07-27")
        assert entries[0]["link"].endswith("/x/")

    def test_falls_back_to_updated_when_no_published(self):
        assert parse_rss_entries(RSS_XML)[1]["published"].startswith("2026-07-26")

    def test_malformed_xml_returns_empty_not_raises(self):
        """社群是六類中最不關鍵的一類，不值得為它中斷 collector（R6-1）。"""
        assert parse_rss_entries("<not xml") == []
        assert parse_rss_entries("") == []

    def test_respects_limit(self):
        assert len(parse_rss_entries(RSS_XML, limit=1)) == 1


class TestRetryAfterSeconds:
    def test_reads_x_ratelimit_reset(self):
        assert _retry_after_seconds(_resp(429, headers={"x-ratelimit-reset": "17"})) == 17.0

    def test_falls_back_to_retry_after(self):
        assert _retry_after_seconds(_resp(429, headers={"retry-after": "5"})) == 5.0

    def test_clamped_to_max(self):
        assert _retry_after_seconds(_resp(429, headers={"x-ratelimit-reset": "999"})) == RATE_LIMIT_MAX_WAIT

    def test_missing_header_uses_max(self):
        assert _retry_after_seconds(_resp(429, headers={})) == RATE_LIMIT_MAX_WAIT


class TestFetchViaRss:
    @pytest.mark.asyncio
    async def test_produces_evidence_from_rss(self, logger, monkeypatch):
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)

        calls = []

        async def mock_get(url, **kwargs):
            calls.append(url)
            assert url.endswith(".rss"), "未認證路徑必須走 RSS，.json 已被 Reddit 全面 403"
            return _resp(200, text=RSS_XML)

        collector = SocialCollector(logger)
        with (
            patch("agent.collectors.social.httpx.AsyncClient") as cls,
            patch("agent.collectors.social.RSS_INTER_REQUEST_DELAY", 0),
        ):
            cls.return_value = _client(get=mock_get)
            evidences = await collector.fetch("BTC")

        assert evidences
        assert all(e.horizon_class == HorizonClass.SHORT for e in evidences)
        # RSS 沒有 score／留言數，必須在 source 誠實標示降級，不能讓讀者以為有熱度資料
        assert all("RSS" in e.source for e in evidences)
        # 沒有實際的 score= 數值（說明文字裡提到 score 這個詞是刻意的揭露，不算）
        assert all("score=" not in e.content_reference for e in evidences)
        assert all("不提供 score" in e.content_reference for e in evidences)

    @pytest.mark.asyncio
    async def test_retries_once_on_429_then_succeeds(self, logger, monkeypatch):
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)

        state = {"n": 0}

        async def mock_get(url, **kwargs):
            state["n"] += 1
            if state["n"] == 1:
                return _resp(429, headers={"x-ratelimit-reset": "1"})
            return _resp(200, text=RSS_XML)

        collector = SocialCollector(logger)
        with (
            patch("agent.collectors.social.httpx.AsyncClient") as cls,
            patch("agent.collectors.social.RSS_INTER_REQUEST_DELAY", 0),
            patch("agent.collectors.social.asyncio.sleep", new=AsyncMock()),
        ):
            cls.return_value = _client(get=mock_get)
            evidences = await collector.fetch("BTC")

        assert evidences, "429 後應等待重試而非直接放棄"

    @pytest.mark.asyncio
    async def test_persistent_429_degrades_without_raising(self, logger, monkeypatch):
        """限流沒退時整個 collector 仍須正常回空，不可讓例外往上拋（R6-1）。"""
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)

        async def mock_get(url, **kwargs):
            return _resp(429, headers={"x-ratelimit-reset": "1"})

        collector = SocialCollector(logger)
        with (
            patch("agent.collectors.social.httpx.AsyncClient") as cls,
            patch("agent.collectors.social.RSS_INTER_REQUEST_DELAY", 0),
            patch("agent.collectors.social.asyncio.sleep", new=AsyncMock()),
        ):
            cls.return_value = _client(get=mock_get)
            assert await collector.fetch("BTC") == []


class TestOauthPath:
    @pytest.mark.asyncio
    async def test_uses_oauth_when_credentials_present(self, logger, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")

        urls = []

        async def mock_post(url, **kwargs):
            return _resp(200, json_data={"access_token": "tok"})

        async def mock_get(url, **kwargs):
            urls.append(url)
            assert kwargs["headers"]["Authorization"] == "Bearer tok"
            return _resp(
                200,
                json_data={
                    "data": {
                        "children": [
                            {"data": {"title": "t", "score": 42, "num_comments": 7,
                                      "created_utc": 1.0, "permalink": "/p"}}
                        ]
                    }
                },
            )

        collector = SocialCollector(logger)
        with patch("agent.collectors.social.httpx.AsyncClient") as cls:
            cls.return_value = _client(get=mock_get, post=mock_post)
            evidences = await collector.fetch("BTC")

        assert evidences
        assert all("oauth.reddit.com" in u for u in urls)
        # OAuth 路徑拿得回熱度欄位，這正是設定憑證的價值
        assert any("score=42" in e.content_reference for e in evidences)
        assert all("RSS" not in e.source for e in evidences)

    @pytest.mark.asyncio
    async def test_token_failure_falls_back_to_rss(self, logger, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "bad")

        async def mock_post(url, **kwargs):
            return _resp(401)

        async def mock_get(url, **kwargs):
            assert url.endswith(".rss")
            return _resp(200, text=RSS_XML)

        collector = SocialCollector(logger)
        with (
            patch("agent.collectors.social.httpx.AsyncClient") as cls,
            patch("agent.collectors.social.RSS_INTER_REQUEST_DELAY", 0),
        ):
            cls.return_value = _client(get=mock_get, post=mock_post)
            evidences = await collector.fetch("BTC")

        assert evidences, "憑證失效時應退回 RSS 而非整類無資料"
        assert all("RSS" in e.source for e in evidences)

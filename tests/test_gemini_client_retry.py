"""驗證 Gemini client 的重試策略會區分「重試有用」與「重試無用」的錯誤。

額度耗盡與 rate limit 同樣是 429 RESOURCE_EXHAUSTED，但前者退避再久也不會成功，
一律重試只會讓每次呼叫白等指數退避的時間。
"""

from __future__ import annotations

import pytest

from agent.config import Settings
from agent.reasoning.gemini_client import GeminiClient, GeminiClientError


class _StubModels:
    """記錄呼叫次數並固定拋出指定例外。"""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        raise self.exc


class _StubGenaiClient:
    """genai.Client 的 models 是唯讀 property，因此整個換掉而不是只換 models。"""

    def __init__(self, models: _StubModels):
        self.models = models


def _client_raising(monkeypatch, exc: Exception) -> tuple[GeminiClient, _StubModels]:
    settings = Settings(llm_backend="gemini", gemini_api_key="fake-key-for-test")
    client = GeminiClient(settings, base_backoff_seconds=0.0)
    stub = _StubModels(exc)
    monkeypatch.setattr(client, "client", _StubGenaiClient(stub))
    return client, stub


QUOTA_DEPLETED = RuntimeError(
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
    "'Your prepayment credits are depleted. Please go to AI Studio...'}}"
)
RATE_LIMITED = RuntimeError(
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
    "'Quota exceeded for quota metric requests per minute'}}"
)


def test_quota_depleted_fails_immediately_without_retrying(monkeypatch):
    client, stub = _client_raising(monkeypatch, QUOTA_DEPLETED)

    with pytest.raises(GeminiClientError, match="重試無用"):
        client.converse("sys", "user")

    assert stub.calls == 1


def test_invalid_api_key_fails_immediately_without_retrying(monkeypatch):
    client, stub = _client_raising(monkeypatch, RuntimeError("400 API key not valid"))

    with pytest.raises(GeminiClientError, match="重試無用"):
        client.converse("sys", "user")

    assert stub.calls == 1


def test_rate_limit_still_retries(monkeypatch):
    """單純的 rate limit 屬於暫時性問題，退避重試仍然合理。"""
    client, stub = _client_raising(monkeypatch, RATE_LIMITED)

    with pytest.raises(GeminiClientError, match="已重試"):
        client.converse("sys", "user")

    assert stub.calls == 3


def test_transient_server_error_still_retries(monkeypatch):
    client, stub = _client_raising(monkeypatch, RuntimeError("503 Service Unavailable"))

    with pytest.raises(GeminiClientError, match="已重試"):
        client.converse("sys", "user")

    assert stub.calls == 3

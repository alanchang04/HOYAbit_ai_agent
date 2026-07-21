"""Tests for agent/reasoning/baseline.py — 可開關對照組。"""

from __future__ import annotations

from agent.reasoning.baseline import (
    BASELINE_SYSTEM_PROMPT,
    run_baseline,
    run_baseline_dry_run,
)
from agent.schemas import Evidence, SourceType


class FakeLLMClient:
    """測試用假 LLM client，回傳固定文字。"""

    def converse(self, system_prompt: str, user_prompt: str, max_tokens: int = 2048) -> str:
        return f"[FAKE] 回應：{user_prompt[:30]}"


class FailingLLMClient:
    """測試失敗隔離：呼叫即拋例外。"""

    def converse(self, system_prompt: str, user_prompt: str, max_tokens: int = 2048) -> str:
        raise RuntimeError("模擬 LLM 呼叫失敗")


def _make_evidence(ev_id: str, source: str, content: str) -> Evidence:
    return Evidence(
        id=ev_id,
        coin="BTC",
        source=source,
        fetched_at="2025-01-01T00:00:00Z",
        content_reference=content,
        related_claim="test claim",
        source_type=SourceType.NEWS,
    )


def test_run_baseline_dry_run_returns_expected_structure():
    result = run_baseline_dry_run("BTC 市場分析", coin="BTC")
    assert "analysis" in result
    assert "caveat" in result
    assert "BTC" in result["analysis"]
    assert "dry-run" in result["analysis"]
    assert "未過濾對照組" in result["caveat"]


def test_run_baseline_dry_run_with_coin2():
    result = run_baseline_dry_run("BTC vs ETH 比較", coin="BTC", coin2="ETH")
    assert "BTC vs ETH" in result["analysis"]
    assert "caveat" in result


def test_run_baseline_success_with_fake_client():
    evidences = [
        _make_evidence("ev-001", "CoinDesk", "BTC 上漲 5%"),
        _make_evidence("ev-002", "Glassnode", "活躍地址數增加"),
    ]
    client = FakeLLMClient()
    result = run_baseline(
        question="分析 BTC 市場表現",
        evidences=evidences,
        llm_client=client,
        coin="BTC",
    )
    assert "analysis" in result
    assert "error" not in result
    assert "caveat" in result
    assert "未過濾對照組" in result["caveat"]
    assert "[FAKE]" in result["analysis"]


def test_run_baseline_failure_isolation():
    evidences = [_make_evidence("ev-001", "CoinDesk", "BTC 上漲")]
    client = FailingLLMClient()
    result = run_baseline(
        question="分析 BTC",
        evidences=evidences,
        llm_client=client,
        coin="BTC",
    )
    assert "error" in result
    assert "analysis" not in result
    assert "baseline 執行失敗" in result["error"]


def test_baseline_system_prompt_forbids_investment_advice():
    forbidden_terms = ["buy", "sell", "hold", "進場價", "停損點", "停利"]
    # 確認 system prompt 有禁止投資建議的明文
    assert "嚴禁" in BASELINE_SYSTEM_PROMPT
    assert "投資建議" in BASELINE_SYSTEM_PROMPT

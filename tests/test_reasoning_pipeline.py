"""用假 LLM client 驗證推理鏈邏輯，不需要真的呼叫 Bedrock/Gemini。"""

import pytest

from agent.reasoning.pipeline import run_reasoning
from agent.schemas import Evidence, now_iso


class FakeLLMClient:
    """依序回放預先寫好的回應；放入 Exception 實例代表模擬該次呼叫失敗。"""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.call_count = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def converse(self, system_prompt: str, user_prompt: str, max_tokens: int = 2048) -> str:
        self.call_count += 1
        self.usage["calls"] += 1
        self.usage["input_tokens"] += 100  # 假 token 數
        self.usage["output_tokens"] += 200
        if not self._responses:
            raise AssertionError("FakeLLMClient 的回應腳本用完了，呼叫次數超出預期")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _evidences() -> list[Evidence]:
    return [
        Evidence(
            id="ev-001",
            coin="BTC",
            source="test-source",
            fetched_at=now_iso(),
            content_reference="ref",
            related_claim="claim",
            source_type="price",
        )
    ]


STEP_A_RESPONSE = '{"facts": [{"source_type": "price", "summary": "s", "evidence_ids": ["ev-001"]}]}'
STEP_B_RESPONSE = '{"consistent_signals": ["c1"], "contradictions": []}'
STEP_D_RESPONSE = (
    '{"market_judgment": "mj", "confidence": "中", "limitations": [], '
    '"invalidation_conditions": [], "evidence_ids": ["ev-001"], "follow_up_watchpoints": ["w1"]}'
)


def test_debate_happy_path_populates_bull_and_bear():
    responses = [
        STEP_A_RESPONSE,
        STEP_B_RESPONSE,
        '{"argument": "bull arg", "evidence_ids": ["ev-001"]}',  # Step C1 正方
        '{"critique": "crit", "argument": "bear arg", "evidence_ids": ["ev-001"]}',  # Step C2 反方
        STEP_D_RESPONSE,
    ]
    client = FakeLLMClient(responses)

    result = run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    assert result.debate["bull_argument"] == "bull arg"
    assert result.debate["bear_argument"] == "bear arg"
    assert result.debate["bear_critique"] == "crit"
    assert len(result.inference) == 2
    assert result.inference[0]["hypothesis"].startswith("[正方]")
    assert result.inference[1]["hypothesis"].startswith("[反方]")
    assert result.conclusion["market_judgment"] == "mj"
    assert client.call_count == 5


def test_debate_passes_bear_critique_to_the_judge():
    """反方對正方的批評必須進到 Step D 的 prompt。

    critique 不在 inference 裡（inference 只攤平了雙方的 argument），
    早期版本因此讓裁判在完全沒看到反駁的情況下下結論。
    """
    prompts: list[str] = []

    class RecordingClient(FakeLLMClient):
        def converse(self, system_prompt: str, user_prompt: str, max_tokens: int = 2048) -> str:
            prompts.append(user_prompt)
            return super().converse(system_prompt, user_prompt, max_tokens)

    client = RecordingClient(
        [
            STEP_A_RESPONSE,
            STEP_B_RESPONSE,
            '{"argument": "bull arg", "evidence_ids": ["ev-001"]}',
            '{"critique": "正方過度解讀了量能數據", "argument": "bear arg", "evidence_ids": ["ev-001"]}',
            STEP_D_RESPONSE,
        ]
    )

    run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    step_d_prompt = prompts[-1]
    assert "正方過度解讀了量能數據" in step_d_prompt
    assert "裁判守則" in step_d_prompt


def test_bull_failure_falls_back_to_single_model_inference():
    responses = [
        STEP_A_RESPONSE,
        STEP_B_RESPONSE,
        RuntimeError("simulated network failure on bull step"),  # Step C1 失敗
        '{"inference": [{"hypothesis": "h", "supporting_evidence_ids": ["ev-001"], "opposing_evidence_ids": []}]}',  # fallback Step C
        STEP_D_RESPONSE,
    ]
    client = FakeLLMClient(responses)

    result = run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    assert result.debate == {}
    assert len(result.inference) == 1
    assert result.inference[0]["hypothesis"] == "h"
    assert result.conclusion["market_judgment"] == "mj"
    assert client.call_count == 5


def test_bear_failure_keeps_the_bull_argument_instead_of_discarding_it():
    """C2 失敗時，C1 已經花掉一次呼叫產出的正方論證要保留，不能整段丟掉重跑。"""
    responses = [
        STEP_A_RESPONSE,
        STEP_B_RESPONSE,
        '{"argument": "bull arg", "evidence_ids": ["ev-001"]}',  # Step C1 成功
        RuntimeError("simulated network failure on bear step"),  # Step C2 失敗
        '{"inference": [{"hypothesis": "h", "supporting_evidence_ids": ["ev-001"], "opposing_evidence_ids": []}]}',  # fallback Step C
        STEP_D_RESPONSE,
    ]
    client = FakeLLMClient(responses)

    result = run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    # 單方面的辯論不成立，debate 維持空 dict，報告與四面板不會呈現成完整辯論
    assert result.debate == {}
    # 正方論證仍以假設的形式保留下來，並由單模型補上對立假設
    assert len(result.inference) == 2
    assert result.inference[0]["hypothesis"] == "[正方] bull arg"
    assert result.inference[0]["supporting_evidence_ids"] == ["ev-001"]
    assert result.inference[1]["hypothesis"] == "h"
    assert result.conclusion["market_judgment"] == "mj"
    assert client.call_count == 6


def test_comparison_mode_threads_coin2_through_result():
    responses = [
        STEP_A_RESPONSE,
        STEP_B_RESPONSE,
        '{"argument": "bull arg for BTC", "evidence_ids": ["ev-001"]}',
        '{"critique": "crit", "argument": "bear arg for ETH", "evidence_ids": ["ev-001"]}',
        STEP_D_RESPONSE,
    ]
    client = FakeLLMClient(responses)

    result = run_reasoning(
        "BTC", "比較 BTC 與 ETH 的市場位置", _evidences(), dry_run=False, llm_client=client, coin2="ETH"
    )

    assert result.coin2 == "ETH"
    assert result.question_type == "comparison"
    assert result.debate["bull_argument"] == "bull arg for BTC"


def test_dry_run_comparison_mentions_both_coins():
    result = run_reasoning("BTC", "比較 BTC 與 ETH", _evidences(), dry_run=True, coin2="ETH")

    assert result.coin2 == "ETH"
    assert "ETH" in result.conclusion["market_judgment"]


@pytest.mark.parametrize("coin", ["BTC", "ETH", "SOL", "BNB", "XRP"])
def test_debate_happy_path_works_for_every_supported_coin(coin):
    """離線驗證五個幣種都能跑完整個推理鏈，不需要消耗真實 LLM 額度。"""
    responses = [
        STEP_A_RESPONSE,
        STEP_B_RESPONSE,
        '{"argument": "bull arg", "evidence_ids": ["ev-001"]}',
        '{"critique": "crit", "argument": "bear arg", "evidence_ids": ["ev-001"]}',
        STEP_D_RESPONSE,
    ]
    client = FakeLLMClient(responses)
    evidences = [
        Evidence(
            id="ev-001",
            coin=coin,
            source="test-source",
            fetched_at=now_iso(),
            content_reference="ref",
            related_claim="claim",
            source_type="price",
        )
    ]

    result = run_reasoning(coin, f"分析 {coin} 市場狀態", evidences, dry_run=False, llm_client=client)

    assert result.conclusion["market_judgment"] == "mj"
    assert result.debate["bull_argument"] == "bull arg"
    assert client.call_count == 5


def test_fake_llm_client_accumulates_usage():
    """驗證 FakeLLMClient 累計 usage token 數（模擬真實 client 行為）。"""
    responses = [
        STEP_A_RESPONSE,
        STEP_B_RESPONSE,
        '{"argument": "bull arg", "evidence_ids": ["ev-001"]}',
        '{"critique": "crit", "argument": "bear arg", "evidence_ids": ["ev-001"]}',
        STEP_D_RESPONSE,
    ]
    client = FakeLLMClient(responses)

    run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    assert client.usage["calls"] == 5
    assert client.usage["input_tokens"] == 500  # 5 calls × 100
    assert client.usage["output_tokens"] == 1000  # 5 calls × 200
    assert client.usage["calls"] == client.call_count

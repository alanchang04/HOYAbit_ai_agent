"""用假 LLM client 驗證推理鏈邏輯，不需要真的呼叫 Bedrock/Gemini。"""

import json
import time

import pytest

from agent.reasoning.pipeline import _build_related_claims, run_reasoning
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


def _evidences(count: int = 1) -> list[Evidence]:
    return [
        Evidence(
            id=f"ev-{i:03d}",
            coin="BTC",
            source="test-source",
            fetched_at=now_iso(),
            content_reference="ref",
            related_claim="claim",
            source_type="price",
        )
        for i in range(1, count + 1)
    ]


STEP_A_RESPONSE = '{"facts": [{"source_type": "price", "summary": "s", "evidence_ids": ["ev-001"]}]}'
STEP_B_RESPONSE = '{"consistent_signals": ["c1"], "contradictions": []}'
STEP_D_RESPONSE = (
    '{"market_judgment": "mj", "confidence": "中", "limitations": [], '
    '"invalidation_conditions": [], "evidence_ids": ["ev-001"], "follow_up_watchpoints": ["w1"]}'
)
BULL_RESPONSE = '{"argument": "bull arg", "evidence_ids": ["ev-001"]}'
# 反方自報「已無新論點」→ 辯論在第一輪就收斂，整條鏈維持 5 次呼叫
BEAR_CONVERGED_RESPONSE = (
    '{"critique": "crit", "argument": "bear arg", "evidence_ids": ["ev-001"], "has_new_points": false}'
)


class RecordingClient(FakeLLMClient):
    """額外把送出的 user prompt 依序記下來，供 prompt 內容斷言使用。"""

    def __init__(self, responses: list):
        super().__init__(responses)
        self.prompts: list[str] = []

    def converse(self, system_prompt: str, user_prompt: str, max_tokens: int = 2048) -> str:
        self.prompts.append(user_prompt)
        return super().converse(system_prompt, user_prompt, max_tokens)


def test_debate_happy_path_populates_bull_and_bear():
    responses = [
        STEP_A_RESPONSE,
        STEP_B_RESPONSE,
        BULL_RESPONSE,  # Step C1 正方
        BEAR_CONVERGED_RESPONSE,  # Step C2 反方
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


def test_bear_reporting_no_new_points_stops_the_debate_early():
    """反方自報已無新論點時，辯論在第一輪收斂，不再進第二輪。"""
    client = FakeLLMClient(
        [STEP_A_RESPONSE, STEP_B_RESPONSE, BULL_RESPONSE, BEAR_CONVERGED_RESPONSE, STEP_D_RESPONSE]
    )

    result = run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    assert result.debate["round_count"] == 1
    assert result.debate["stopped_reason"] == "converged"
    assert result.debate["rounds"][0]["bear_has_new_points"] is False
    assert client.call_count == 5  # 沒有多花第二輪的兩次呼叫


def test_debate_runs_second_round_when_bear_still_has_new_points():
    """反方仍有新論點 → 進第二輪（正方反駁 → 反方再駁），並在輪數上限停下。"""
    client = FakeLLMClient(
        [
            STEP_A_RESPONSE,
            STEP_B_RESPONSE,
            '{"argument": "bull r1", "evidence_ids": ["ev-001"]}',
            '{"critique": "crit r1", "argument": "bear r1", "evidence_ids": ["ev-002"], "has_new_points": true}',
            '{"argument": "bull r2", "evidence_ids": ["ev-003"]}',
            '{"critique": "crit r2", "argument": "bear r2", "evidence_ids": ["ev-001"], "has_new_points": true}',
            STEP_D_RESPONSE,
        ]
    )

    result = run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(3), dry_run=False, llm_client=client)

    assert result.debate["round_count"] == 2
    assert result.debate["stopped_reason"] == "max_rounds"
    assert [r["round"] for r in result.debate["rounds"]] == [1, 2]
    # 相容層：論證取最後一輪（最精煉），evidence id 取全部輪次聯集
    assert result.debate["bull_argument"] == "bull r2"
    assert result.debate["bear_critique"] == "crit r2"
    assert result.debate["bull_evidence_ids"] == ["ev-001", "ev-003"]
    assert result.debate["bear_evidence_ids"] == ["ev-002", "ev-001"]
    assert client.call_count == 7  # 5 + 第二輪的 2 次


def test_second_round_bull_sees_the_previous_rounds_critique():
    """正方反駁時必須拿得到反方上一輪的批評，否則第二輪只是重講一次。"""
    client = RecordingClient(
        [
            STEP_A_RESPONSE,
            STEP_B_RESPONSE,
            '{"argument": "bull r1", "evidence_ids": ["ev-001"]}',
            '{"critique": "你把單日量能當成趨勢", "argument": "bear r1", "evidence_ids": ["ev-001"], "has_new_points": true}',
            '{"argument": "bull r2", "evidence_ids": ["ev-001"]}',
            BEAR_CONVERGED_RESPONSE,
            STEP_D_RESPONSE,
        ]
    )

    run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    second_round_bull_prompt = client.prompts[4]
    assert "你把單日量能當成趨勢" in second_round_bull_prompt
    assert "第 2 輪" in second_round_bull_prompt


@pytest.mark.parametrize(
    "raw_value, expected_rounds, expected_reason",
    [
        ("false", 1, "converged"),  # 字串而非 JSON boolean
        ('"false"', 1, "converged"),  # 帶引號的字串
        ("否", 1, "converged"),  # 中文
        ("0", 1, "converged"),  # 數字 0
    ],
)
def test_has_new_points_accepts_non_boolean_forms(raw_value, expected_rounds, expected_reason):
    """模型不一定回 JSON boolean，回字串/中文/數字時收斂機制仍要生效。"""
    bear = json.dumps(
        {
            "critique": "crit",
            "argument": "bear arg",
            "evidence_ids": ["ev-001"],
            "has_new_points": raw_value,
        },
        ensure_ascii=False,
    )
    client = FakeLLMClient([STEP_A_RESPONSE, STEP_B_RESPONSE, BULL_RESPONSE, bear, STEP_D_RESPONSE])

    result = run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    assert result.debate["round_count"] == expected_rounds
    assert result.debate["stopped_reason"] == expected_reason


def test_has_new_points_unparseable_value_keeps_debating():
    """無法判讀時要預設繼續辯論，不能因為模型亂填就把辯論悄悄砍成單輪。"""
    bear = (
        '{"critique": "crit", "argument": "bear arg", "evidence_ids": ["ev-001"], '
        '"has_new_points": "看情況"}'
    )
    client = FakeLLMClient(
        [
            STEP_A_RESPONSE,
            STEP_B_RESPONSE,
            BULL_RESPONSE,
            bear,
            '{"argument": "bull r2", "evidence_ids": ["ev-001"]}',
            BEAR_CONVERGED_RESPONSE,
            STEP_D_RESPONSE,
        ]
    )

    result = run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    assert result.debate["round_count"] == 2


def test_deadline_stops_the_debate_before_starting_another_round(monkeypatch):
    """剩餘時間不足時要收在當輪，把時間留給裁判。

    2026-08-01 契約變更：本測試原本用「已經超時」的 deadline，並期望裁判仍然跑完。
    那與 15 分鐘硬性上限不相容——超時之後再發 LLM 呼叫只會讓整跑更晚結束，
    而超時後的產出主辦方可以不採計。現在超時就完全不發呼叫（見
    `test_expired_deadline_makes_no_llm_call`），所以這裡改用「還有一輪份的預算、
    但不夠再開一輪」的情境來測輪與輪之間的 gate。
    """
    from agent.reasoning import pipeline as _pipeline

    # 「整段跳過辯論」的門檻另有專門測試，這裡壓到極小以免兩者互相干擾。
    monkeypatch.setattr(_pipeline, "STEP_D_RESERVE_SECONDS", 0.01)
    monkeypatch.setattr(_pipeline, "MIN_LLM_STEP_SECONDS", 0.01)

    class SlowFakeClient(FakeLLMClient):
        """每次呼叫睡一下。gate 的 needed 是「上一輪實測秒數 × 係數」，
        瞬間回應的假 client 會讓 needed≈0、gate 永遠不觸發，測不到東西。"""

        def converse(self, system_prompt, user_prompt, max_tokens=2048):
            time.sleep(0.05)
            return super().converse(system_prompt, user_prompt, max_tokens)

    client = SlowFakeClient(
        [
            STEP_A_RESPONSE,
            STEP_B_RESPONSE,
            BULL_RESPONSE,
            # 反方說還有新論點，正常情況下會進第二輪
            '{"critique": "crit", "argument": "bear arg", "evidence_ids": ["ev-001"], "has_new_points": true}',
            STEP_D_RESPONSE,
        ]
    )

    # 預算：A+B+第1輪約 0.2s，剩約 0.1s；再開一輪需要 0.1×2.2=0.22s → gate 觸發，
    # 但仍夠讓裁判跑完（MIN 已壓到 0.01）。
    result = run_reasoning(
        "BTC",
        "分析 BTC 市場狀態",
        _evidences(),
        dry_run=False,
        llm_client=client,
        deadline=time.monotonic() + 0.3,
    )

    assert result.debate["round_count"] == 1
    assert result.debate["stopped_reason"] == "deadline"
    assert result.conclusion["market_judgment"] == "mj"  # 裁判仍然跑完
    assert client.call_count == 5  # 沒有進第二輪


def test_expired_deadline_makes_no_llm_call():
    """deadline 已過時一次 LLM 呼叫都不發，讓 orchestrator 走降級報告。

    15 分鐘是硬性上限（命題文件執行限制第 1 條），超時後的產出主辦方可停止執行
    或不採計——「有產出但超時」比「誠實降級但準時」還糟。
    """
    from agent.reasoning.pipeline import ReasoningStepError

    client = FakeLLMClient([STEP_A_RESPONSE])
    with pytest.raises(ReasoningStepError) as exc:
        run_reasoning(
            "BTC", "分析 BTC 市場狀態", _evidences(),
            dry_run=False, llm_client=client, deadline=time.monotonic() - 1,
        )
    assert "時間預算不足" in str(exc.value)
    assert client.call_count == 0


def test_no_deadline_means_unlimited():
    """不傳 deadline 時維持原行為，不受時間影響。"""
    client = FakeLLMClient(
        [
            STEP_A_RESPONSE,
            STEP_B_RESPONSE,
            BULL_RESPONSE,
            '{"critique": "crit", "argument": "bear arg", "evidence_ids": ["ev-001"], "has_new_points": true}',
            '{"argument": "bull r2", "evidence_ids": ["ev-001"]}',
            BEAR_CONVERGED_RESPONSE,
            STEP_D_RESPONSE,
        ]
    )

    result = run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    assert result.debate["round_count"] == 2


def test_bull_rebuttal_failure_keeps_the_completed_rounds():
    """第二輪正方失敗時，第一輪的完整辯論要保留，不能整個作廢。"""
    client = FakeLLMClient(
        [
            STEP_A_RESPONSE,
            STEP_B_RESPONSE,
            '{"argument": "bull r1", "evidence_ids": ["ev-001"]}',
            '{"critique": "crit r1", "argument": "bear r1", "evidence_ids": ["ev-001"], "has_new_points": true}',
            RuntimeError("simulated failure on round 2 bull"),
            STEP_D_RESPONSE,
        ]
    )

    result = run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    assert result.debate["round_count"] == 1
    assert result.debate["stopped_reason"] == "bull_failed"
    assert result.debate["bull_argument"] == "bull r1"
    assert len(result.inference) == 2
    assert result.conclusion["market_judgment"] == "mj"
    assert client.call_count == 6


def test_debate_passes_bear_critique_to_the_judge():
    """反方對正方的批評必須進到 Step D 的 prompt。

    critique 不在 inference 裡（inference 只攤平了雙方的 argument），
    早期版本因此讓裁判在完全沒看到反駁的情況下下結論。
    """
    client = RecordingClient(
        [
            STEP_A_RESPONSE,
            STEP_B_RESPONSE,
            BULL_RESPONSE,
            '{"critique": "正方過度解讀了量能數據", "argument": "bear arg", '
            '"evidence_ids": ["ev-001"], "has_new_points": false}',
            STEP_D_RESPONSE,
        ]
    )

    run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    step_d_prompt = client.prompts[-1]
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
        '{"critique": "crit", "argument": "bear arg for ETH", "evidence_ids": ["ev-001"], '
        '"has_new_points": false}',
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
        BULL_RESPONSE,
        BEAR_CONVERGED_RESPONSE,
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
        BULL_RESPONSE,
        BEAR_CONVERGED_RESPONSE,
        STEP_D_RESPONSE,
    ]
    client = FakeLLMClient(responses)

    run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    assert client.usage["calls"] == 5
    assert client.usage["input_tokens"] == 500  # 5 calls × 100
    assert client.usage["output_tokens"] == 1000  # 5 calls × 200
    assert client.usage["calls"] == client.call_count


class TestSanitizeDebateSummary:
    """裁判整理的辯論重點摘要：格式錯誤的單一條目整條丟棄，不讓其他 3-4 點也作廢
    （R6-1 降級優先），且幻覺 evidence id 要被過濾掉。"""

    def _sanitize(self, raw, known_ids=frozenset({"ev-001", "ev-002"})):
        from agent.reasoning.pipeline import _sanitize_debate_summary

        return _sanitize_debate_summary(raw, set(known_ids))

    def test_valid_items_pass_through(self):
        raw = [{"point": "重點一", "evidence_ids": ["ev-001"], "verdict": "bear_valid"}]
        assert self._sanitize(raw) == [
            {"point": "重點一", "evidence_ids": ["ev-001"], "verdict": "bear_valid"}
        ]

    def test_hallucinated_evidence_id_is_stripped_not_whole_item(self):
        """幻覺 id 只濾掉那個 id，這個攻防重點本身仍保留（有 point 就有價值）。"""
        raw = [{"point": "重點一", "evidence_ids": ["ev-001", "ev-999"], "verdict": "draw"}]
        assert self._sanitize(raw) == [
            {"point": "重點一", "evidence_ids": ["ev-001"], "verdict": "draw"}
        ]

    def test_missing_point_drops_only_that_item(self):
        raw = [
            {"evidence_ids": ["ev-001"]},  # 缺 point，整條丟棄
            {"point": "重點二", "evidence_ids": ["ev-002"], "verdict": "bull_defended"},
        ]
        assert self._sanitize(raw) == [
            {"point": "重點二", "evidence_ids": ["ev-002"], "verdict": "bull_defended"}
        ]

    def test_empty_point_string_is_dropped(self):
        raw = [{"point": "   ", "evidence_ids": []}]
        assert self._sanitize(raw) == []

    def test_non_list_input_degrades_to_empty(self):
        assert self._sanitize("不是清單") == []
        assert self._sanitize(None) == []

    def test_non_dict_item_is_skipped(self):
        raw = ["純字串條目", {"point": "有效重點", "evidence_ids": [], "verdict": "draw"}]
        assert self._sanitize(raw) == [
            {"point": "有效重點", "evidence_ids": [], "verdict": "draw"}
        ]

    def test_missing_evidence_ids_defaults_to_empty_list(self):
        raw = [{"point": "沒引用證據的重點"}]
        assert self._sanitize(raw) == [
            {"point": "沒引用證據的重點", "evidence_ids": [], "verdict": "draw"}
        ]

    def test_unreadable_verdict_falls_back_to_draw(self):
        """verdict 判讀不出來時計為 draw（0 分），不丟棄整點——降級優先（R6-1）。"""
        raw = [{"point": "重點", "evidence_ids": [], "verdict": "很嚴重"}]
        assert self._sanitize(raw)[0]["verdict"] == "draw"

    def test_chinese_verdict_alias_is_accepted(self):
        """模型不保證回 ASCII enum，中文同義詞一併認。"""
        raw = [{"point": "重點", "evidence_ids": [], "verdict": "反方成立"}]
        assert self._sanitize(raw)[0]["verdict"] == "bear_valid"


class TestStepAGroundingRetry:
    """Step A 的 fact 若沒通過 grounding 稽核（見 agent/reasoning/grounding.py），
    要重試一次；重試乾淨就採用，重試後仍違規就直接捨棄，不讓它流進 Step B/C。
    """

    def _evidence_without_rsi(self) -> list[Evidence]:
        return [
            Evidence(
                id="ev-001",
                coin="BTC",
                source="test-source",
                fetched_at=now_iso(),
                content_reference="近 14 日收盤價與成交量摘要",
                related_claim="claim",
                source_type="price",
            )
        ]

    def test_violating_fact_is_dropped_and_retry_replaces_it(self):
        violating_step_a = (
            '{"facts": [{"source_type": "price", "summary": "RSI 指標顯示動能減弱", '
            '"evidence_ids": ["ev-001"]}]}'
        )
        clean_retry = (
            '{"facts": [{"source_type": "price", "summary": "收盤價與成交量已提供", '
            '"evidence_ids": ["ev-001"]}]}'
        )
        client = FakeLLMClient(
            [
                violating_step_a,
                clean_retry,
                STEP_B_RESPONSE,
                BULL_RESPONSE,
                BEAR_CONVERGED_RESPONSE,
                STEP_D_RESPONSE,
            ]
        )

        result = run_reasoning(
            "BTC", "分析 BTC 市場狀態", self._evidence_without_rsi(), dry_run=False, llm_client=client
        )

        assert len(result.facts) == 1
        assert result.facts[0]["summary"] == "收盤價與成交量已提供"
        assert client.call_count == 6  # 5 個既有步驟 + 1 次 grounding 重試

    def test_fact_still_violating_after_retry_is_dropped_not_propagated(self):
        violating_step_a = (
            '{"facts": [{"source_type": "price", "summary": "RSI 指標顯示動能減弱", '
            '"evidence_ids": ["ev-001"]}]}'
        )
        still_violating_retry = (
            '{"facts": [{"source_type": "price", "summary": "RSI 已降至超賣區", '
            '"evidence_ids": ["ev-001"]}]}'
        )
        client = FakeLLMClient(
            [
                violating_step_a,
                still_violating_retry,
                STEP_B_RESPONSE,
                BULL_RESPONSE,
                BEAR_CONVERGED_RESPONSE,
                STEP_D_RESPONSE,
            ]
        )

        result = run_reasoning(
            "BTC", "分析 BTC 市場狀態", self._evidence_without_rsi(), dry_run=False, llm_client=client
        )

        assert result.facts == []
        assert client.call_count == 6

    def test_clean_facts_do_not_trigger_a_retry_call(self):
        """既有測試的 STEP_A_RESPONSE（summary="s"）不含任何違規，不該多花一次呼叫——
        這條測試確保驗證器接入後沒有改變既有 happy path 的呼叫次數。"""
        client = FakeLLMClient(
            [STEP_A_RESPONSE, STEP_B_RESPONSE, BULL_RESPONSE, BEAR_CONVERGED_RESPONSE, STEP_D_RESPONSE]
        )

        result = run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

        assert len(result.facts) == 1
        assert client.call_count == 5


class TestBuildRelatedClaims:
    """v1.2 新增：把 facts 依 (coin, source_type) 分組成 topic → claims 附加結構，
    不動 `Evidence.related_claim`，也不呼叫新的 LLM（見 pipeline.py 的說明）。"""

    def test_groups_by_coin_and_source_type(self):
        facts = [
            {"source_type": "onchain", "coin": "BTC", "summary": "鏈上活躍地址數上升", "evidence_ids": ["ev-001"]},
            {"source_type": "onchain", "coin": "BTC", "summary": "交易量近兩週下降", "evidence_ids": ["ev-002"]},
            {"source_type": "price", "coin": "BTC", "summary": "收盤價持穩", "evidence_ids": ["ev-003"]},
        ]
        result = _build_related_claims(facts)

        by_topic = {item["topic"]: item["related_claims"] for item in result}
        assert by_topic["BTC 鏈上"] == ["鏈上活躍地址數上升", "交易量近兩週下降"]
        assert by_topic["BTC 價格"] == ["收盤價持穩"]

    def test_missing_coin_falls_back_to_label_only_topic(self):
        facts = [{"source_type": "macro", "summary": "美元走強", "evidence_ids": ["ev-001"]}]
        result = _build_related_claims(facts)
        assert result == [{"topic": "總經", "related_claims": ["美元走強"]}]

    def test_empty_or_blank_summary_is_skipped(self):
        facts = [
            {"source_type": "price", "coin": "BTC", "summary": "", "evidence_ids": []},
            {"source_type": "price", "coin": "BTC", "summary": "   ", "evidence_ids": []},
        ]
        assert _build_related_claims(facts) == []

    def test_unknown_source_type_falls_back_to_raw_value(self):
        facts = [{"source_type": "weird_type", "coin": "BTC", "summary": "x", "evidence_ids": []}]
        result = _build_related_claims(facts)
        assert result[0]["topic"] == "BTC weird_type"


def test_run_reasoning_populates_related_claims():
    """STEP_A_RESPONSE 沒有 coin 欄位（`_sanitize_facts` 只在模型有回傳時才保留），
    topic 落回純標籤——這正是 `_build_related_claims` 對缺 coin 的降級行為。"""
    client = FakeLLMClient([STEP_A_RESPONSE, STEP_B_RESPONSE, BULL_RESPONSE, BEAR_CONVERGED_RESPONSE, STEP_D_RESPONSE])

    result = run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(), dry_run=False, llm_client=client)

    assert result.related_claims == [{"topic": "價格", "related_claims": ["s"]}]


def test_dry_run_also_populates_related_claims():
    result = run_reasoning("BTC", "分析 BTC 市場狀態", _evidences(2), dry_run=True)

    assert len(result.related_claims) == 1
    assert result.related_claims[0]["topic"] == "價格"  # dry-run facts 沒有 coin 欄位

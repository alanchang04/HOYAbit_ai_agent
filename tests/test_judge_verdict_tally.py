"""裁判機制 2026-08-01 改版的單元測試。

背景見 `output/JUDGE_TEST_REPORT.md`（三題型真實 Bedrock 實測 + 敏感度探針）。
本檔涵蓋四件事：
1. 逐點判定加總取代裁判自報整數（原本在真實區間內是常數 −3，沒有鑑別力）
2. 信心等級改由決定性分數推得（原本與分數是兩套獨立系統、無一致性檢查）
3. Step D 補上權重索引（原本是四步裡唯一拿不到權重表、卻被要求依權重評斷的）
4. 辯論輪時間餘裕係數 1.5 → 2.2（原值三題實測全部低估）
"""

import pytest

from agent.reasoning.confidence import (
    CONFIDENCE_TIER_HIGH,
    CONFIDENCE_TIER_MEDIUM,
    DEBATE_ADJUSTMENT_MAX,
    DEBATE_ADJUSTMENT_MIN,
    VERDICT_SCORES,
    coerce_verdict,
    compute_confidence,
    confidence_label,
    tally_debate_verdicts,
)
from agent.reasoning.pipeline import DEBATE_ROUND_TIME_FACTOR
from agent.reasoning.prompts import DEBATE_REBUTTAL_STANDARD, build_step_d_prompt
from agent.schemas import Evidence


def _point(verdict):
    return {"point": "某個攻防結果", "evidence_ids": ["ev-001"], "verdict": verdict}


# --- 1. 逐點判定加總 ---


class TestVerdictTally:
    def test_scores_sum(self):
        summary = [_point("bear_valid"), _point("bear_valid"), _point("bull_defended")]
        total, counts = tally_debate_verdicts(summary)
        assert total == -3 + -3 + 1 == -5
        assert counts == {"bear_valid": 2, "bull_defended": 1}

    def test_five_bear_valid_hits_exactly_the_floor(self):
        """debate_summary 要求 3-5 點，5 × (-3) 剛好對齊既有的下限，不需另定夾值語意。"""
        total, _ = tally_debate_verdicts([_point("bear_valid")] * 5)
        assert total == DEBATE_ADJUSTMENT_MIN

    def test_five_bull_defended_hits_exactly_the_ceiling(self):
        total, _ = tally_debate_verdicts([_point("bull_defended")] * 5)
        assert total == DEBATE_ADJUSTMENT_MAX

    def test_empty_summary_returns_none_not_zero(self):
        """回 0 會讓報告寫成「裁判未提供有效的調整值」，但實際上是這次根本沒有辯論。"""
        assert tally_debate_verdicts([]) == (None, {})
        assert tally_debate_verdicts(None) == (None, {})
        assert tally_debate_verdicts("不是清單") == (None, {})

    def test_unreadable_verdict_counts_as_draw(self):
        total, counts = tally_debate_verdicts([{"point": "x", "verdict": "很嚴重"}])
        assert total == 0 and counts == {"draw": 1}

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("bear_valid", "bear_valid"),
            ("BULL_DEFENDED", "bull_defended"),
            ("反方成立", "bear_valid"),
            ("正方擋下", "bull_defended"),
            ("打平", "draw"),
            ("部分成立", "bear_partial"),
            (None, None),
            (3, None),
            ("很多", None),
        ],
    )
    def test_verdict_coercion(self, raw, expected):
        assert coerce_verdict(raw) == expected


class TestTallyDrivesConfidence:
    def test_tally_overrides_llm_scalar(self):
        """有逐點判定時，裁判自報的整數不再決定分數。"""
        _, bd = compute_confidence(
            [], {},
            debate_adjustment=-3, debate_adjustment_reason="裁判自報",
            debate_summary=[_point("bear_valid")] * 3,
        )
        assert bd["debate_adjustment"] == -9
        assert bd["debate_adjustment_source"] == "verdict_tally"

    def test_falls_back_to_scalar_without_verdicts(self):
        """fallback 路徑（無辯論、debate_summary 為 []）維持舊行為。"""
        _, bd = compute_confidence(
            [], {}, debate_adjustment=-8, debate_adjustment_reason="理由", debate_summary=[],
        )
        assert bd["debate_adjustment"] == -8
        assert bd["debate_adjustment_source"] == "llm_scalar"

    def test_tally_is_clamped(self):
        _, bd = compute_confidence([], {}, debate_summary=[_point("bear_valid")] * 8)
        assert bd["debate_adjustment"] == DEBATE_ADJUSTMENT_MIN
        assert bd["debate_adjustment_raw"] == -24
        assert "已夾值" in bd["debate_adjustment_note"]

    def test_tally_needs_no_reason_string(self):
        """逐點判定本身就是理由，不受 `_clamp_debate_adjustment` 的「無理由視為 0」限制。"""
        _, bd = compute_confidence([], {}, debate_adjustment_reason="", debate_summary=[_point("bear_valid")])
        assert bd["debate_adjustment"] == -3

    def test_detail_string_is_auditable(self):
        _, bd = compute_confidence(
            [], {}, debate_summary=[_point("bear_valid"), _point("bull_defended")],
        )
        assert "反方批評成立 1 點 × -3" in bd["debate_verdict_detail"]
        assert "正方擋下 1 點 × +1" in bd["debate_verdict_detail"]

    def test_discriminates_where_the_scalar_did_not(self):
        """2026-08-01 三題實跑的人工判定，套用本表後會散開；原機制三題都是 −3。

        Q1 反方成立2／正方擋下2／打平1、Q2 反方成立3／正方擋下2、
        Q3 反方成立3／正方擋下1／部分成立1（逐點歸類見 JUDGE_TEST_REPORT.md §6.4）。
        """
        q1 = [_point("bear_valid")] * 2 + [_point("bull_defended")] * 2 + [_point("draw")]
        q2 = [_point("bear_valid")] * 3 + [_point("bull_defended")] * 2
        q3 = [_point("bear_valid")] * 3 + [_point("bull_defended")] + [_point("bear_partial")]
        totals = [tally_debate_verdicts(q)[0] for q in (q1, q2, q3)]
        assert totals == [-4, -7, -9]
        assert len(set(totals)) == 3  # 原機制三題全是 −3，這裡三題各不相同


# --- 2. 信心等級由分數推得 ---


class TestConfidenceLabel:
    @pytest.mark.parametrize(
        "score,expected",
        [(95, "高"), (80, "高"), (79, "中"), (60, "中"), (59, "低"), (5, "低")],
    )
    def test_thresholds(self, score, expected):
        assert confidence_label(score) == expected

    def test_reproduces_the_2026_08_01_run_labels(self):
        """門檻取 80／60 的理由：三題實跑分數 79／78／74 的顯示等級必須與當時
        LLM 自報的「中／中／中」一致——這個改動把等級變成可複現的，不改變呈現。
        """
        assert [confidence_label(s) for s in (79, 78, 74)] == ["中", "中", "中"]

    def test_is_deterministic(self):
        assert confidence_label(77) == confidence_label(77)
        assert CONFIDENCE_TIER_HIGH > CONFIDENCE_TIER_MEDIUM


# --- 3. Step D 權重索引 ---


def _ev(id_="ev-001", weight=0.92):
    return Evidence(
        id=id_, coin="BTC", source="official_csv", fetched_at="2026-07-25T00:00:00Z",
        content_reference="x", related_claim="y", source_type="price",
        source_weight=weight, weight_reason=f"四因子 w={weight}", horizon_class="medium",
    )


class TestStepDWeightIndex:
    def test_weight_index_is_present_when_evidences_given(self):
        """裁判被要求依權重評斷，就必須拿得到權重表。

        改版前 Step D 是四步裡唯一沒有權重索引的，只能吃辯士自己在論證文字裡寫的
        `（weight=0.80）`——而那正是它要裁決的兩造。
        """
        prompt = build_step_d_prompt(
            "BTC", "分析 BTC", "multi_source", [], {}, [], evidences=[_ev(), _ev("ev-002", 0.31)],
        )
        assert "ev-001" in prompt and "ev-002" in prompt
        assert "權重" in prompt

    def test_degrades_without_evidences(self):
        """沒有證據可列時整段省略、不中斷（R6-1），既有呼叫端不傳也不會壞。"""
        prompt = build_step_d_prompt("BTC", "分析 BTC", "multi_source", [], {}, [])
        assert "請執行【結論層】分析" in prompt


class TestStepDInferenceIdsUseLastRound:
    def test_compact_block_drops_ids_abandoned_after_round_1(self):
        """`inference` 帶進來的是跨輪聯集，但 hypothesis 文字是最後一輪的。
        直接用聯集會讓第 1 輪引用過、第 2 輪已放棄的證據仍掛在最後一輪論證下。
        """
        debate = {
            "rounds": [
                {"round": 1, "bull_argument": "一", "bull_evidence_ids": ["ev-001", "ev-009"],
                 "bear_critique": "批", "bear_argument": "反一", "bear_evidence_ids": ["ev-002"]},
                {"round": 2, "bull_argument": "二", "bull_evidence_ids": ["ev-001"],
                 "bear_critique": "批2", "bear_argument": "反二", "bear_evidence_ids": ["ev-002"]},
            ],
            "stopped_reason": "max_rounds",
        }
        inference = [
            {"hypothesis": "[正方] 二", "supporting_evidence_ids": ["ev-001", "ev-009"],
             "opposing_evidence_ids": ["ev-002"]},
        ]
        prompt = build_step_d_prompt("BTC", "q", "multi_source", [], {}, inference, debate=debate)
        compact = prompt.split("辯論紀錄（")[0]
        assert "ev-009" not in compact  # 第 2 輪已放棄，不該掛在末輪論證下


# --- 4. 辯論輪時間餘裕係數 ---


def test_round_time_factor_covers_measured_ratios():
    """2026-08-01 三題實測 (第2輪+裁判)÷第1輪 = 1.68 / 1.91 / 2.09，舊值 1.5 全部低估。

    低估的後果不是「辯論被砍掉」而是「整跑超過 15 分鐘」——deadline 只在辯論輪之間
    檢查一次，Step D 之前不再檢查，gate 放行後剩下的路一定會走完。
    """
    measured = (1.68, 1.91, 2.09)
    assert DEBATE_ROUND_TIME_FACTOR >= max(measured)
    assert VERDICT_SCORES["draw"] == 0  # 判讀不出來時不影響分數


# --- 5. 被批評時的判定標準（2026-08-01，過度承認）---


class TestRebuttalStandard:
    """`DEBATE_REBUTTAL_STANDARD` 的掛載位置與 `DEBATE_ADVOCACY_RULE` 同一套邏輯：
    只有「真的面對前一輪批評」的位置才掛，且正反方共用同一份文字。
    """

    _ROUNDS = [{
        "round": 1, "bull_argument": "正方一", "bull_evidence_ids": ["ev-001"],
        "bear_critique": "批評", "bear_argument": "反方一", "bear_evidence_ids": ["ev-002"],
    }]

    def test_present_in_bull_rebuttal(self):
        from agent.reasoning.prompts import build_step_c1_bull_rebuttal_prompt

        prompt = build_step_c1_bull_rebuttal_prompt("BTC", "q", "multi_source", [], {}, self._ROUNDS)
        assert DEBATE_REBUTTAL_STANDARD in prompt

    def test_present_in_bear_from_round_2(self):
        from agent.reasoning.prompts import build_step_c2_bear_prompt

        prompt = build_step_c2_bear_prompt(
            "BTC", "q", "multi_source", [], {}, "正方論證", rounds=self._ROUNDS, round_no=2,
        )
        assert DEBATE_REBUTTAL_STANDARD in prompt

    def test_absent_where_there_is_nothing_to_judge(self):
        """第 1 輪沒有前輪批評可判定；單模型 fallback 沒有對手（同 DEBATE_ADVOCACY_RULE）。"""
        from agent.reasoning.prompts import (
            build_step_c1_bull_prompt,
            build_step_c2_bear_prompt,
            build_step_c_prompt,
        )

        assert DEBATE_REBUTTAL_STANDARD not in build_step_c1_bull_prompt("BTC", "q", "multi_source", [], {})
        assert DEBATE_REBUTTAL_STANDARD not in build_step_c2_bear_prompt("BTC", "q", "multi_source", [], {}, "正方")
        assert DEBATE_REBUTTAL_STANDARD not in build_step_c_prompt("BTC", "q", "multi_source", [], {})

    def test_rebuttal_task_no_longer_presumes_the_critique_is_valid(self):
        """原文「批評成立的部分要誠實承認…不要硬拗」把讓步當預設、把防守叫硬拗，
        是過度承認的直接來源。改為先判定成不成立、再三選一回應。
        """
        from agent.reasoning.prompts import build_step_c1_bull_rebuttal_prompt

        prompt = build_step_c1_bull_rebuttal_prompt("BTC", "q", "multi_source", [], {}, self._ROUNDS)
        assert "不要硬拗" not in prompt
        assert "先判定成不成立" in prompt
        assert "不要預設批評是對的" in prompt

    def test_standard_still_allows_conceding_valid_criticism(self):
        """要的是「先檢驗再決定」，不是「一律不認」——教模型拒絕有效批評比過度承認更糟。"""
        assert "承認只在批評通過上述檢驗時才給" in DEBATE_REBUTTAL_STANDARD
        assert "正面修正" in DEBATE_REBUTTAL_STANDARD

    def test_both_sides_share_the_same_text(self):
        """不對稱的讓步要求會讓裁判讀到語氣不對等的兩段論證（同 DEBATE_ADVOCACY_RULE）。"""
        from agent.reasoning.prompts import build_step_c1_bull_rebuttal_prompt, build_step_c2_bear_prompt

        bull = build_step_c1_bull_rebuttal_prompt("BTC", "q", "multi_source", [], {}, self._ROUNDS)
        bear = build_step_c2_bear_prompt(
            "BTC", "q", "multi_source", [], {}, "正方論證", rounds=self._ROUNDS, round_no=2,
        )
        assert DEBATE_REBUTTAL_STANDARD in bull and DEBATE_REBUTTAL_STANDARD in bear


# --- 6. 第 1 輪的計時起點（2026-08-01 實測發現）---


class TestFirstRoundTiming:
    """`last_round_seconds` 是下一輪 deadline gate 的分母，第 1 輪必須含正方呼叫。

    第 1 輪的正方呼叫發生在辯論迴圈外，原本 `round_started` 設在迴圈內，
    量到的只有反方那一段。2026-08-01 實跑對帳：gate 記的 `needed=70.3s`
    ÷ `DEBATE_ROUND_TIME_FACTOR` = 31.95s，正好等於反方單獨的 31.9s，
    而該輪實際是 bull 20.7 + bear 31.9 = 52.6s——低估四成。
    """

    @pytest.fixture(autouse=True)
    def _patch(self, monkeypatch):
        self._mp = monkeypatch

    def _run(self, bull_delay, bear_delay, budget, monkeypatch=None):
        import time as _time

        from agent.reasoning import pipeline as _pipeline

        from agent.reasoning.pipeline import run_reasoning
        from agent.schemas import Evidence, now_iso

        bull = '{"argument": "bull", "evidence_ids": ["ev-001"]}'
        bear = ('{"critique": "c", "argument": "b", "evidence_ids": ["ev-001"], '
                '"has_new_points": true}')
        step_a = '{"facts": [{"source_type": "price", "summary": "s", "evidence_ids": ["ev-001"]}]}'
        step_b = '{"consistent_signals": [], "contradictions": []}'
        step_d = ('{"market_judgment": "m", "confidence": "中", "limitations": [], '
                  '"invalidation_conditions": [], "evidence_ids": [], "follow_up_watchpoints": []}')

        class SlowClient:
            def __init__(self):
                self.script = [step_a, step_b, bull, bear, bull, bear, step_d]
                self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
                self.calls = 0

            def converse(self, system_prompt, user_prompt, max_tokens=2048):
                item = self.script.pop(0)
                self.calls += 1
                if item is bull:
                    _time.sleep(bull_delay)
                elif item is bear:
                    _time.sleep(bear_delay)
                return item

        ev = [Evidence(id="ev-001", coin="BTC", source="s", fetched_at=now_iso(),
                       content_reference="r", related_claim="c", source_type="price")]
        # 這兩個常數是「整段跳過辯論」的門檻（見 TestHardDeadline）；本組測的是
        # 輪與輪之間的 gate，把門檻壓到極小以免兩者互相干擾。
        self._mp.setattr(_pipeline, "STEP_D_RESERVE_SECONDS", 0.05)
        self._mp.setattr(_pipeline, "MIN_LLM_STEP_SECONDS", 0.01)
        client = SlowClient()
        return run_reasoning(
            "BTC", "分析 BTC 市場表現", ev, dry_run=False, llm_client=client,
            deadline=_time.monotonic() + budget,
        )

    def test_round_1_cost_includes_the_bull_call(self):
        """預算刻意落在「夠買舊算法的 needed、不夠買正確 needed」的區間。

        bull=bear=0.3s：正確計時 needed = 0.6 × 2.2 = 1.32s，
        漏算正方時 needed = 0.3 × 2.2 = 0.66s。gate 當下剩餘約 0.9s——
        正確計時會收在第 1 輪，舊算法會誤放行第 2 輪。
        """
        result = self._run(bull_delay=0.3, bear_delay=0.3, budget=1.5)
        assert result.debate["stopped_reason"] == "deadline"
        assert result.debate["round_count"] == 1

    def test_ample_budget_still_runs_two_rounds(self):
        """修正不能反過來把時間充裕的情況也砍掉。"""
        result = self._run(bull_delay=0.01, bear_delay=0.01, budget=30)
        assert result.debate["round_count"] == 2


# --- 7. Bedrock 呼叫的時間邊界（2026-08-01，1020s 卡頓事故）---


class TestBedrockTimeouts:
    """事故：一次 `step_a_facts` 卡了 1020s，把整跑推到 1189s（硬限 900s）。

    成因鏈（皆已查證）：boto3 預設 `read_timeout=60s`，但實測正常呼叫最慢的
    `step_d_conclusion` 是 56.5s（27 次樣本），只剩 6% 餘裕；botocore 預設
    `retries={'mode':'legacy'}` 的 `__default__.max_attempts=5`，且
    `general_socket_errors` 的 EXCEPTION_MAP 含 `ReadTimeoutError`；
    而 `ReadTimeoutError` 又是 `BotoCoreError` 子類、會被應用層再接住重試 3 次。
    兩層相乘最多 15 次 × 60s ≈ 900s＋backoff。
    """

    def _client(self, **env):
        import os
        from unittest import mock

        from agent.config import Settings

        with mock.patch.dict(os.environ, env, clear=False):
            settings = Settings()
        from agent.reasoning.bedrock_client import BedrockClient

        return BedrockClient(settings)

    def test_read_timeout_has_margin_over_observed_max_call(self):
        """實測最慢的正常呼叫是 56.5s；預設值必須明顯高於它，否則正常回應會被誤判逾時。"""
        from agent.config import Settings

        assert Settings().llm_read_timeout_seconds >= 120

    def test_botocore_retries_are_disabled(self):
        """重試政策只留應用層一份。兩層各自重試會相乘，且底層那層無法記錄、
        也感知不到整跑的時間預算。"""
        cfg = self._client().client.meta.config
        # botocore 把 `max_attempts`（重試次數）正規化成 `total_max_attempts`（總嘗試次數）。
        # 1 代表打一次就不再重試——這裡若變成 2 就是又被打開了。
        assert cfg.retries["total_max_attempts"] == 1
        assert cfg.read_timeout == 150
        assert cfg.connect_timeout == 10

    def test_gives_up_before_the_deadline_instead_of_overrunning(self):
        import time

        c = self._client()
        c.deadline = time.monotonic() - 1  # 已經超出預算
        with pytest.raises(Exception) as exc:
            c.converse("sys", "user")
        assert "時間預算" in str(exc.value)

    def test_retries_are_reported(self):
        """1020s 的卡頓全程沒有留下任何一行 log，事後只能靠側錄耗時反推。"""
        c = self._client()
        seen = []
        c.on_retry = seen.append
        assert c._sleep_before_retry(1, RuntimeError("boom")) is True
        assert seen and "1/3" in seen[0]

    def test_no_retry_when_budget_is_shorter_than_the_backoff(self):
        import time

        c = self._client()
        c.deadline = time.monotonic() + 0.5  # 短於第一次 backoff 的 1.5s
        seen = []
        c.on_retry = seen.append
        assert c._sleep_before_retry(1, RuntimeError("boom")) is False
        assert "放棄重試" in seen[0]


# --- 8. 15 分鐘硬性上限（禁止超時）---


class TestHardDeadline:
    """兩層保證，缺一不可：

    1. **不啟動**：剩餘時間不足以完成一次呼叫時，`_call_json_step` 直接放棄該步驟。
    2. **不超時**：已經發出的請求也不能跑過截止時間——`BedrockClient` 依剩餘預算
       收緊該次的 socket read timeout。

    只有第 1 層是不夠的：在截止前 1 秒發出的請求，照樣能跑滿 150 秒的 read timeout。
    """

    def test_effective_timeout_never_outlives_the_deadline(self):
        """任何在截止前發出的請求都必須在截止前結束。"""
        import time

        from agent.config import Settings
        from agent.reasoning.bedrock_client import BedrockClient

        c = BedrockClient(Settings())
        for remaining in (20, 40, 90, 200, 600, 900):
            c.deadline = time.monotonic() + remaining
            timeout = c._effective_timeout()
            assert timeout is not None
            # 連線逾時 + 讀取逾時 + 安全邊際 必須裝得進剩餘預算
            worst_case = timeout + c.settings.llm_connect_timeout_seconds + c.SAFETY_MARGIN_SECONDS
            assert worst_case <= remaining + 1, f"remaining={remaining} timeout={timeout}"

    def test_effective_timeout_is_capped_by_the_configured_value(self):
        """預算充裕時不能無限放大 timeout，仍以設定值為上限。"""
        import time

        from agent.config import Settings
        from agent.reasoning.bedrock_client import BedrockClient

        c = BedrockClient(Settings())
        c.deadline = time.monotonic() + 10_000
        assert c._effective_timeout() == Settings().llm_read_timeout_seconds

    def test_no_request_is_sent_when_budget_is_exhausted(self):
        import time

        from agent.config import Settings
        from agent.reasoning.bedrock_client import BedrockClient

        c = BedrockClient(Settings())
        c.deadline = time.monotonic() + 2  # 連 connect_timeout + margin 都不夠
        assert c._effective_timeout() is None

    def test_pipeline_stops_issuing_calls_and_stays_within_budget(self):
        """整條推理鏈在預算內收手：呼叫次數受限，且總耗時不超過預算太多。

        假 client 不會自己遵守 deadline（那是 BedrockClient 的責任，另有測試），
        所以這裡驗的是「不啟動」那一層：預算用完後不再發新呼叫。
        """
        import time as _time

        from agent.reasoning.pipeline import ReasoningStepError, run_reasoning
        from agent.schemas import Evidence, now_iso

        step_a = '{"facts": [{"source_type": "price", "summary": "s", "evidence_ids": ["ev-001"]}]}'
        step_b = '{"consistent_signals": [], "contradictions": []}'
        per_call = 0.2

        class SlowClient:
            def __init__(self):
                self.calls = 0
                self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

            def converse(self, system_prompt, user_prompt, max_tokens=2048):
                self.calls += 1
                _time.sleep(per_call)
                return step_a if self.calls == 1 else step_b

        ev = [Evidence(id="ev-001", coin="BTC", source="s", fetched_at=now_iso(),
                       content_reference="r", related_claim="c", source_type="price")]
        client = SlowClient()
        budget = 0.5
        started = _time.monotonic()
        with pytest.raises(ReasoningStepError):
            run_reasoning("BTC", "分析 BTC 市場表現", ev, dry_run=False, llm_client=client,
                          deadline=started + budget)
        elapsed = _time.monotonic() - started
        # 預算 0.5s、每次呼叫 0.2s：最多發 2 次就會因剩餘 < MIN 而放棄。
        assert client.calls <= 3
        assert elapsed <= budget + per_call + 0.3, f"elapsed={elapsed:.2f}s"

    def test_debate_is_skipped_entirely_when_only_the_judge_fits(self):
        """時間只夠給裁判時整段跳過辯論——沒有結論的辯論沒有價值。"""
        import time as _time

        from agent.reasoning import pipeline as _pipeline
        from agent.reasoning.pipeline import run_reasoning
        from agent.schemas import Evidence, now_iso

        step_a = '{"facts": [{"source_type": "price", "summary": "s", "evidence_ids": ["ev-001"]}]}'
        step_b = '{"consistent_signals": [], "contradictions": []}'
        step_d = ('{"market_judgment": "m", "confidence": "中", "limitations": [], '
                  '"invalidation_conditions": [], "evidence_ids": [], "follow_up_watchpoints": []}')

        class Client:
            def __init__(self):
                self.script = [step_a, step_b, step_d]
                self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
                self.calls = 0

            def converse(self, system_prompt, user_prompt, max_tokens=2048):
                self.calls += 1
                return self.script.pop(0)

        ev = [Evidence(id="ev-001", coin="BTC", source="s", fetched_at=now_iso(),
                       content_reference="r", related_claim="c", source_type="price")]
        client = Client()
        result = run_reasoning("BTC", "分析 BTC 市場表現", ev, dry_run=False, llm_client=client,
                               deadline=_time.monotonic() + _pipeline.STEP_D_RESERVE_SECONDS + 1)
        assert client.calls == 3          # A、B、裁判——沒有任何辯論呼叫
        assert result.debate == {}
        assert result.inference == []
        assert result.conclusion["market_judgment"] == "m"

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
        assert "反方成立 1 點 × -3" in bd["debate_verdict_detail"]
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


# --- 9. 題型分類：幣種數量覆寫（JUDGE_TEST_REPORT.md §13.2）---


class TestCoinCountOverridesKeywords:
    """題目提到 2 個以上幣種池成員時一律判 comparison。

    關鍵字比對是先比中先贏，而「SOL 與 XRP 何者風險敞口較高？」一個 comparison
    關鍵字都沒命中 → 落回 multi_source → orchestrator 的 coin2 偵測只在 comparison
    分支執行 → 拿單一幣種證據回答雙幣種題目。錯在蒐集階段，裁判救不回來。
    """

    def _c(self, q):
        from agent.reasoning.prompts import classify_question_type

        return classify_question_type(q)

    def test_two_coins_without_any_comparison_keyword(self):
        """本次修正的目標案例——原本判 multi_source。"""
        assert self._c("SOL 與 XRP 何者在當前宏觀環境下風險敞口較高？") == "comparison"

    def test_two_coins_beats_hypothesis_keywords(self):
        """雙幣種要勝過假設驗證的關鍵字：少收一個幣種的資料無法補救，
        多收一個只是報告多談一個幣種。判錯的代價不對稱。"""
        assert self._c("市場上有聲音認為 SOL 將超越 XRP，請蒐集支持與反對的證據。") == "comparison"

    def test_full_name_aliases_count(self):
        assert self._c("請評估 Bitcoin 與 Ethereum 在當前環境下的相對風險。") == "comparison"

    @pytest.mark.parametrize(
        "question,expected",
        [
            # 命題文件範例一／二／三逐字，三者的分類必須維持不變
            ("分析 BTC 過去兩週的市場表現，整合價格走勢、鏈上活躍度、主要新聞事件與"
             "社群討論熱度，給出整體市場狀態判斷，並說明各類資料之間的一致程度。", "multi_source"),
            ("市場上有聲音認為 ETH 短期內將維持盤整、缺乏明確方向，請蒐集支持與反對"
             "此觀點的證據，並說明你最終的判斷與理由。", "hypothesis_test"),
            ("比較 SOL 與 XRP 在當前宏觀環境下各自的市場位置與風險特徵。", "comparison"),
            # 命題文件的題目模板
            ("請針對 ETH，分析其當前市場狀況，並回答指定問題。", "multi_source"),
        ],
    )
    def test_official_examples_unchanged(self, question, expected):
        assert self._c(question) == expected

    def test_single_coin_is_not_forced_to_comparison(self):
        assert self._c("分析 BTC 過去兩週的市場表現與整體市場狀態。") == "multi_source"


# --- 10. 彈性化：分類只給骨架，維度交給 LLM（JUDGE_TEST_REPORT.md §17）---


class TestQuestionPrimacy:
    """framing 不得規定分析維度——維度一律以題目原文為準。

    改版前 comparison 的 framing 寫死「請比較 A 與 B 在流動性、市場關注度、
    風險敞口上的差異」，那三項是從命題文件範例三抄來的。題目若問「開發者活躍度
    與機構託管規模」，系統會照樣注入流動性那三項，framing 覆寫了題目的實際要求。
    """

    def _framing(self, qtype="comparison", coin="BTC", coin2="ETH", coins=None):
        from agent.reasoning.prompts import _resolve_framing

        return _resolve_framing(qtype, coin, coin2, coins=coins)

    def test_framing_no_longer_prescribes_dimensions(self):
        f = self._framing()
        for hardcoded in ("流動性", "市場關注度", "風險敞口"):
            assert hardcoded not in f, f"framing 仍寫死維度「{hardcoded}」"

    def test_primacy_rule_is_attached_to_every_type(self):
        from agent.reasoning.prompts import QUESTION_PRIMACY_RULE

        for qtype in ("multi_source", "hypothesis_test", "comparison"):
            assert QUESTION_PRIMACY_RULE in self._framing(qtype)

    def test_framing_lists_all_coins_with_evidence(self):
        """三個以上幣種時 `coin2` 裝不下，framing 要用完整清單。"""
        f = self._framing(coins=["BTC", "ETH", "SOL"])
        assert "BTC、ETH、SOL" in f

    def test_coin_header_covers_three_coins(self):
        from agent.reasoning.prompts import build_step_d_prompt

        p = build_step_d_prompt(
            "BTC", "比較 BTC、ETH 與 SOL", "comparison", [], {}, [],
            coin2="ETH", coins=["BTC", "ETH", "SOL"],
        )
        assert "幣種：BTC／ETH／SOL" in p


class TestRelationalQuestionsAreNotForcedToComparison:
    """題目提到別的幣種不一定是要比較——也可能只是拿它當參照。

    「分析 SOL 當前狀況，並說明其與 BTC 的相關性是否鬆動」的主體是 SOL，
    判成 comparison 會讓正反方去爭「SOL 還是 BTC 更值得關注」，那不是題目要問的。
    """

    def _c(self, q):
        from agent.reasoning.prompts import classify_question_type

        return classify_question_type(q)

    @pytest.mark.parametrize(
        "question",
        [
            "分析 SOL 當前市場狀況，並說明其與 BTC 的相關性是否鬆動。",
            "分析 ETH 近期表現，說明其與 BTC 的連動是否減弱。",
            "分析 SOL 當前市場狀況，說明其是否已與 BTC 脫鉤。",
        ],
    )
    def test_relational_phrasing_stays_single_subject(self, question):
        assert self._c(question) != "comparison"

    def test_explicit_comparison_verb_still_wins(self):
        """關係型措辭遇上明確的比較動詞時，仍判為 comparison。"""
        assert self._c("比較 SOL 與 BTC 的相關性強弱。") == "comparison"

    def test_plain_two_coin_question_is_still_comparison(self):
        """沒有關係型措辭的雙幣種題目，維持 comparison（86e3380 的核心案例）。"""
        assert self._c("SOL 與 XRP 何者在當前宏觀環境下風險敞口較高？") == "comparison"


class TestUncoveredCoinsAreDisclosed:
    """題目提到但沒蒐集到證據的幣種，必須在報告最上方揭露。

    `86e3380` 讓「≥2 個幣種」判 comparison，但 orchestrator 只取第一個非主幣當
    `coin2`，第三個幣直接被忽略。若不揭露，讀者會以為這份比較涵蓋了題目要求的
    全部對象——那是拿不存在的證據作答。
    """

    def _report(self, uncovered):
        from agent.reasoning.pipeline import ReasoningResult
        from agent.report.builder import build_report_markdown
        from agent.schemas import Evidence, now_iso

        ev = [Evidence(id="ev-001", coin="BTC", source="s", fetched_at=now_iso(),
                       content_reference="r", related_claim="c", source_type="price")]
        result = ReasoningResult(
            question_type="comparison",
            facts=[{"source_type": "price", "summary": "s", "evidence_ids": ["ev-001"]}],
            conclusion={"market_judgment": "m", "confidence": "中", "evidence_ids": ["ev-001"]},
        )
        return build_report_markdown(
            "BTC", "比較 BTC、ETH 與 SOL 三者的風險特徵。", result, ev,
            coin2="ETH", uncovered_coins=uncovered,
        )

    def test_uncovered_coin_is_flagged_before_any_conclusion(self):
        report = self._report(["SOL"])
        assert "SOL" in report and "未蒐集其證據" in report
        # 必須出現在結論之前，否則讀者已經讀完比較才知道少了誰
        assert report.index("未蒐集其證據") < report.index("## 1. 結論／市場判斷")

    def test_no_note_when_all_coins_covered(self):
        assert "未蒐集其證據" not in self._report(None)
        assert "未蒐集其證據" not in self._report([])


class TestHardWallClockCapPerCall:
    """`read_timeout` 不是總時長上限——實測一次呼叫跑了 6756s（read_timeout=150s）。

    原因是 `read_timeout` 量的是「兩次 socket 讀取之間的間隔」，Bedrock 的連線
    只要持續有資料進來，計時器就一直被重置。唯一可靠的總時長上限是呼叫端強制中斷。
    """

    def _client(self):
        from agent.config import Settings
        from agent.reasoning.bedrock_client import BedrockClient

        return BedrockClient(Settings(), max_retries=1)

    def test_slow_call_is_aborted_at_the_cap(self):
        import time

        from agent.reasoning.bedrock_client import BedrockClientError

        c = self._client()
        c.deadline = time.monotonic() + 20  # _effective_timeout ≈ 20-10-5 = 5s

        class HangingClient:
            def converse(self, **kwargs):
                time.sleep(30)  # 遠超過上限，但「連線正常」
                return {}

        c._clients = {}
        c._client_with_timeout = lambda t: HangingClient()

        started = time.monotonic()
        with pytest.raises(BedrockClientError) as exc:
            c.converse("sys", "user")
        elapsed = time.monotonic() - started
        assert "硬上限" in str(exc.value)
        assert elapsed < 15, f"沒有在上限附近中斷，實際等了 {elapsed:.1f}s"

    def test_fast_call_is_unaffected(self):
        import time

        c = self._client()
        c.deadline = time.monotonic() + 300

        class FastClient:
            def converse(self, **kwargs):
                return {
                    "usage": {"inputTokens": 1, "outputTokens": 1},
                    "output": {"message": {"content": [{"text": "ok"}]}},
                    "stopReason": "end_turn",
                }

        c._client_with_timeout = lambda t: FastClient()
        assert c.converse("sys", "user") == "ok"


# --- 11. 級距隨題型（JUDGE_TEST_REPORT.md §13.4／§15.3）---


class TestVerdictScaleByQuestionType:
    """不對稱級距預設「反方＝質疑者」，那個前提只有多源整合題成立。

    比較題兩邊都是倡議者；假設驗證題的正方被指派去論證一個可能為假的命題。
    在這兩種題型下沿用不對稱級距，分數會取決於「誰被指派站哪一邊」。
    """

    def _pts(self, **kw):
        out = []
        for verdict, n in kw.items():
            out += [{"point": "x", "evidence_ids": [], "verdict": verdict}] * n
        return out

    def test_comparison_is_perfectly_mirrored(self):
        """比較題把兩幣語序對調時，同一場辯論的分數必須鏡射。

        用 Q3／T2 的真實 verdict：Q3 主幣 SOL 得到 bear_valid×2 + bull_defended×1
        + bear_partial×2；主幣換成 XRP 時角色互換，各判定跟著鏡射。
        """
        sol_first = self._pts(bear_valid=2, bull_defended=1, bear_partial=2)
        xrp_first = self._pts(bull_defended=2, bear_valid=1, bull_partial=2)
        a, _ = tally_debate_verdicts(sol_first, "comparison")
        b, _ = tally_debate_verdicts(xrp_first, "comparison")
        assert a == -b, f"語序對調後分數未鏡射：{a} vs {b}"

    def test_bull_partial_exists_in_symmetric_scales(self):
        """粒度也必須對稱——只補幅度、不補等級的話，
        「XRP 方部分成立」表達得出、「SOL 方部分成立」表達不出。"""
        from agent.reasoning.confidence import scores_for_question_type

        for qtype in ("comparison", "hypothesis_test"):
            scores = scores_for_question_type(qtype)
            assert scores["bull_partial"] == -scores["bear_partial"]
            assert scores["bull_defended"] == -scores["bear_valid"]

    def test_multi_source_keeps_the_asymmetry(self):
        """多源整合的反方確實是質疑者，ADR-5 的防灌分理由在那裡仍然成立。"""
        from agent.reasoning.confidence import scores_for_question_type

        scores = scores_for_question_type("multi_source")
        assert scores["bear_valid"] == -3
        assert scores["bull_defended"] == 1
        assert abs(scores["bear_valid"]) > scores["bull_defended"]

    def test_false_hypothesis_is_penalised_less_than_before(self):
        """T4 實測：假設在證據上站不住時，系統給出最明確的否定卻拿到最大扣分。

        對稱級距把那個扣分收斂，但**不會歸零**——反方勝出仍然扣分。
        這條鎖住「有改善」，不宣稱問題完全消失。
        """
        t4 = self._pts(bear_valid=3, bear_partial=2)
        old, _ = tally_debate_verdicts(t4, "multi_source")
        new, _ = tally_debate_verdicts(t4, "hypothesis_test")
        assert new > old, f"對稱級距未減輕扣分：{old} → {new}"

    def test_unknown_type_falls_back_to_asymmetric(self):
        pts = self._pts(bear_valid=1)
        assert tally_debate_verdicts(pts, None)[0] == tally_debate_verdicts(pts, "multi_source")[0]

    def test_scale_is_selected_through_compute_confidence(self):
        """題型必須真的傳達到計分，不能只是函式支援但沒接線。"""
        pts = self._pts(bull_defended=3)
        _, sym = compute_confidence([], {}, debate_summary=pts, question_type="comparison")
        _, asym = compute_confidence([], {}, debate_summary=pts, question_type="multi_source")
        assert sym["debate_adjustment"] == 6 and asym["debate_adjustment"] == 3


class TestClampRangeFollowsTheScale:
    """夾值範圍必須跟著級距走，否則會把剛拆掉的不對稱從夾值那條路徑放回來。

    對稱題型下 5 點全給正方是 +10；若沿用全域的 +5 上限，「正方全勝」被砍成 +5、
    「反方全勝」的 −10 完整保留——語序對調的鏡射在夾值後就破了。
    """

    def _adj(self, verdict, n, qtype):
        pts = [{"point": "x", "evidence_ids": [], "verdict": verdict}] * n
        _, bd = compute_confidence([], {}, debate_summary=pts, question_type=qtype)
        return bd["debate_adjustment"]

    @pytest.mark.parametrize("qtype", ["comparison", "hypothesis_test"])
    def test_symmetric_extremes_mirror_after_clamping(self, qtype):
        assert self._adj("bull_defended", 5, qtype) == -self._adj("bear_valid", 5, qtype)

    def test_asymmetric_range_is_unchanged(self):
        from agent.reasoning.confidence import (
            DEBATE_ADJUSTMENT_MAX, DEBATE_ADJUSTMENT_MIN, adjustment_range_for,
        )

        assert adjustment_range_for("multi_source") == (
            DEBATE_ADJUSTMENT_MIN, DEBATE_ADJUSTMENT_MAX,
        )
        assert self._adj("bear_valid", 5, "multi_source") == DEBATE_ADJUSTMENT_MIN
        assert self._adj("bull_defended", 5, "multi_source") == DEBATE_ADJUSTMENT_MAX

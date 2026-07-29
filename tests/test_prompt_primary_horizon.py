"""Step A/B 的分帶說明必須隨主視野生成（horizon-aware-confidence R7-3、Task 8.4）。

修的是 prompt 層與計分層的**帶集合錯配**：`confidence.compute_signal_consensus()`
用 `is_current_signal(h, primary)` 決定誰能投票，而 prompt 層原本寫死
「spot/short/medium 是當前訊號」。兩者只在 primary=medium 時重合——
問「最近一年」時計分層收 long/structural 的票，prompt 卻叫模型別列；
問「今天」時模型照列 short/medium，計分層卻全丟。

因此本檔最核心的斷言是 `test_bands_match_scoring_layer`：prompt 講的界線
與 `is_current_signal()` 逐一比對，兩層再也不能各自漂移。
"""

import json

import pytest

from agent.reasoning.confidence import compute_signal_consensus
from agent.reasoning.pipeline import run_reasoning
from agent.reasoning.prompts import (
    EVIDENCE_LIST_LEGEND,
    SYSTEM_PROMPT,
    build_evidence_legend,
    build_step_a_prompt,
    build_step_b_prompt,
    current_signal_bands,
    structural_bands,
)
from agent.schemas import (
    _HORIZON_UPPER_BOUND_DAYS,
    DEFAULT_PRIMARY_HORIZON,
    HORIZON_ORDER,
    Evidence,
    HorizonClass,
    is_current_signal,
    now_iso,
)

from tests.test_reasoning_pipeline import (
    BEAR_CONVERGED_RESPONSE,
    BULL_RESPONSE,
    STEP_A_RESPONSE,
    STEP_B_RESPONSE,
    STEP_D_RESPONSE,
    RecordingClient,
)


def _ev(horizon: HorizonClass = HorizonClass.MEDIUM) -> Evidence:
    return Evidence(
        id="ev-001",
        coin="BTC",
        source="test-source",
        fetched_at=now_iso(),
        content_reference="ref",
        related_claim="claim",
        source_type="price",
        horizon_class=horizon,
    )


class TestBandDerivation:
    """帶集合的推導本身。"""

    @pytest.mark.parametrize("primary", HORIZON_ORDER)
    def test_bands_match_scoring_layer(self, primary: HorizonClass):
        """prompt 層的當前訊號帶必須與 `is_current_signal()` 完全一致。

        這是整個修正的重點：兩層各自維護一份「誰是當前訊號」是這個 bug 的成因，
        任何一邊之後再漂移，這條就會紅。
        """
        current = current_signal_bands(primary)
        structural = structural_bands(primary)
        for horizon in HORIZON_ORDER:
            expected = is_current_signal(horizon, primary)
            assert (horizon in current) is expected
            assert (horizon in structural) is not expected

    @pytest.mark.parametrize("primary", HORIZON_ORDER)
    def test_bands_partition_all_five(self, primary: HorizonClass):
        """兩組互斥且完整涵蓋五帶，沒有證據會落在兩者之外而被靜默忽略。"""
        current = current_signal_bands(primary)
        structural = structural_bands(primary)
        assert set(current) & set(structural) == set()
        assert set(current) | set(structural) == set(HORIZON_ORDER)

    def test_default_is_medium(self):
        """未指定主視野 → 沿用預設 medium，行為與動態主視野接線前完全相同。"""
        assert current_signal_bands(None) == current_signal_bands(DEFAULT_PRIMARY_HORIZON)
        assert build_evidence_legend(None) == build_evidence_legend(DEFAULT_PRIMARY_HORIZON)
        assert EVIDENCE_LIST_LEGEND == build_evidence_legend(None)


class TestSystemPromptDoesNotOverrideLegend:
    """`SYSTEM_PROMPT` 第 7 條不得寫死帶名，否則會蓋掉動態說明區塊。

    `_call_json_step()` 每一次呼叫都把 `SYSTEM_PROMPT` 當 system turn 送出，
    而 system turn 通常勝過 user turn。原本第 7 條寫死「短窗訊號與長窗結構之間的
    落差是位置關係」——主視野 = structural 時，Step B 的 user turn 說長窗反向訊號
    是真矛盾，兩者直接打架，模型很可能照 system turn 繼續把它導進 structural_context，
    等於這次修正在唯一要救的情境下完全無效。改成相對措辭並明指以說明區塊為準。
    """

    def test_rule_seven_is_relative_not_hardwired(self):
        assert "比本次主視野更長" in SYSTEM_PROMPT
        assert "以該處為準" in SYSTEM_PROMPT
        # 寫死的帶名不可再出現（"長窗結構" 隱含 long/structural 恆為脈絡）
        assert "短窗訊號與長窗結構之間的落差" not in SYSTEM_PROMPT

    def test_rule_seven_still_states_the_core_rule(self):
        """措辭改了，規則本身不能弱化（R2-5/R2-7 仍要成立）。"""
        assert "不等於矛盾" in SYSTEM_PROMPT
        assert "位置關係" in SYSTEM_PROMPT


class TestLegendText:
    """說明區塊的文字內容。"""

    def test_band_days_match_schema_boundaries(self):
        """分帶天數描述必須對得上 `_HORIZON_UPPER_BOUND_DAYS`。

        ADR-7 把 short 由 ≤7 天放寬成 ≤10 天以容納「10 日」標準粒度，
        但說明區塊仍寫著「≤7天」——等於對 LLM 謊報邊界，8-10 天的證據
        會被模型當成落在錯誤的帶。
        """
        bounds = dict((h, d) for d, h in _HORIZON_UPPER_BOUND_DAYS)
        assert bounds[HorizonClass.SHORT] == 10
        legend = build_evidence_legend()
        assert "short=≤10天" in legend
        assert "≤7天" not in legend
        assert "medium=11-30天" in legend

    @pytest.mark.parametrize("primary", HORIZON_ORDER)
    def test_legend_states_actual_primary(self, primary: HorizonClass):
        legend = build_evidence_legend(primary)
        assert f"本次主判斷視野為 {primary.value}" in legend
        # 五帶的天數對照一定要全列出來，模型才對得回每筆證據的 horizon 標籤
        for band in HORIZON_ORDER:
            assert band.value in legend

    @pytest.mark.parametrize("primary", HORIZON_ORDER)
    def test_weight_rule_survives_every_primary(self, primary: HorizonClass):
        """權重對抗規則（R4-2）與主視野無關，任何主視野下都不能掉。"""
        assert "低權重證據（<0.5）不足以單獨推翻" in build_evidence_legend(primary)

    def test_structural_primary_declares_no_context_band(self):
        """主視野 = structural 時沒有更長的尺度可當脈絡，必須明講。"""
        legend = build_evidence_legend(HorizonClass.STRUCTURAL)
        assert structural_bands(HorizonClass.STRUCTURAL) == []
        assert "本次無結構脈絡帶" in legend
        assert "結構脈絡帶＝" not in legend

    def test_spot_primary_pushes_short_into_context(self):
        """主視野 = spot 時只有 spot 是當前訊號，其餘四帶都是脈絡。"""
        legend = build_evidence_legend(HorizonClass.SPOT)
        assert "當前訊號帶＝spot（≤ 主視野）" in legend
        assert "結構脈絡帶＝short／medium／long／structural" in legend


class TestStepBInstructions:
    """Step B 的 direction_matrix 與 contradictions/structural_context 分流。"""

    @pytest.mark.parametrize("primary", HORIZON_ORDER)
    def test_direction_matrix_scope_follows_primary(self, primary: HorizonClass):
        """要模型表態的帶＝計分層會採計的帶。錯配就是共識分數失真的來源。"""
        prompt = build_step_b_prompt("BTC", "q", [_ev()], [], primary_horizon=primary)
        expected = "／".join(b.value for b in current_signal_bands(primary))
        assert f"只針對 horizon 為 {expected}（當前訊號帶）的證據表態" in prompt

    def test_structural_primary_asks_for_empty_context(self):
        """沒有脈絡帶時要求填 []，而不是逼模型捏造跨尺度落差。"""
        prompt = build_step_b_prompt("BTC", "q", [_ev()], [], primary_horizon=HorizonClass.STRUCTURAL)
        assert "請填空陣列 []" in prompt
        assert "長窗證據的反向訊號同樣算矛盾" in prompt
        # 欄位本身不能消失——下游 pipeline 與報告一律讀得到這個 key
        assert '"structural_context"' in prompt

    def test_medium_primary_keeps_original_context_wording(self):
        """預設主視野下的措辭與修正前等價（嚴格超集，不改變既有行為）。"""
        prompt = build_step_b_prompt("BTC", "q", [_ev()], [])
        assert "當前訊號（spot／short／medium）與結構脈絡（long／structural）之間的" in prompt
        assert "以「位置關係」措辭描述" in prompt

    def test_three_sections_always_present(self):
        """三段欄位在任何主視野下都要出現，避免下游拿不到 key（R6-1）。"""
        for primary in HORIZON_ORDER:
            prompt = build_step_b_prompt("BTC", "q", [_ev()], [], primary_horizon=primary)
            for key in ("consistent_signals", "contradictions", "structural_context", "direction_matrix"):
                assert f'"{key}"' in prompt


class TestStepAWiring:
    def test_step_a_legend_follows_primary(self):
        prompt = build_step_a_prompt("BTC", "q", [_ev()], primary_horizon=HorizonClass.LONG)
        assert "本次主判斷視野為 long" in prompt
        assert "當前訊號帶＝spot／short／medium／long" in prompt

    def test_step_a_defaults_without_primary(self):
        """不傳主視野仍可運作（R6-1 降級不中斷）。"""
        prompt = build_step_a_prompt("BTC", "q", [_ev()])
        assert "本次主判斷視野為 medium" in prompt


class TestScorerSideOfTheMismatch:
    """計分層實際會怎麼處理錯配產出的 direction_matrix。

    上面的測試全在斷言 prompt 字串，證明不了錯配的代價。這裡直接打
    `compute_signal_consensus()`，把「模型照舊指示產出、計分層用新主視野收票」
    的情境跑出來——順便釘死篩選的**粒度**：是 source_type 層級，不是逐列。
    """

    def _mixed(self) -> list[Evidence]:
        """price 同時有 spot 與 medium 證據；macro／onchain 只有 medium。"""
        def ev(i: int, stype: str, horizon: HorizonClass) -> Evidence:
            return Evidence(
                id=f"ev-{i:03d}",
                coin="BTC",
                source="s",
                fetched_at=now_iso(),
                content_reference="r",
                related_claim="c",
                source_type=stype,
                horizon_class=horizon,
            )

        return [
            ev(1, "price", HorizonClass.SPOT),
            ev(2, "price", HorizonClass.MEDIUM),
            ev(3, "macro", HorizonClass.MEDIUM),
            ev(4, "onchain", HorizonClass.MEDIUM),
        ]

    _MATRIX = [
        {"source_type": "price", "direction": 1, "basis": ["ev-002"]},
        {"source_type": "macro", "direction": -1, "basis": ["ev-003"]},
        {"source_type": "onchain", "direction": -1, "basis": ["ev-004"]},
    ]

    def test_filter_is_source_type_granular_not_row_granular(self):
        """`price` 因為**另有**一筆 spot 證據而整類保留，即使這票是依 medium 證據投的。

        所以「主視野=spot 時 short/medium 的票全被丟掉」是誇大的說法：
        真正被丟的只有「在當前訊號帶內一筆證據都沒有」的 source_type。
        """
        _, detail = compute_signal_consensus(self._MATRIX, self._mixed(), HorizonClass.SPOT)
        kept = [r["source_type"] for r in detail["directions"]]
        assert kept == ["price"]  # macro／onchain 整類消失，price 留下

    def test_mismatch_turns_real_disagreement_into_neutral(self):
        """3 個來源 2:1 分歧（33.33 分）→ 剩 1 個來源 → 降級成中性 50。

        分數不是小幅偏移而是反向：明明分歧嚴重，卻報成「談不上共識」的中性值，
        且 `degraded_reason` 會寫成表態來源不足，讀起來像模型沒給夠資料。
        """
        evidences = self._mixed()
        aligned, _ = compute_signal_consensus(self._MATRIX, evidences, HorizonClass.MEDIUM)
        mismatched, detail = compute_signal_consensus(self._MATRIX, evidences, HorizonClass.SPOT)
        assert aligned == pytest.approx(33.33, abs=0.01)
        assert mismatched == 50.0
        assert detail["degraded"] is True
        assert "表態來源不足" in detail["degraded_reason"]


class TestPipelineWiring:
    """`_real_reasoning` 是否真的把題目推導出的主視野送進 Step A/B。

    這兩個呼叫點漏傳參數正是 Task 8.4 沒做完的部分——函式支援參數但沒人傳，
    單看 prompts.py 的測試會全綠。
    """

    def _run(self, question: str) -> RecordingClient:
        client = RecordingClient(
            [
                STEP_A_RESPONSE,
                STEP_B_RESPONSE,
                BULL_RESPONSE,
                BEAR_CONVERGED_RESPONSE,
                STEP_D_RESPONSE,
            ]
        )
        run_reasoning("BTC", question, [_ev()], dry_run=False, llm_client=client)
        return client

    @pytest.mark.parametrize(
        "question,expected",
        [
            ("BTC 最近一年的市場狀態", "structural"),
            ("BTC 最近一季的市場狀態", "long"),
            ("BTC 最近兩週的市場狀態", "medium"),
            ("BTC 今天的市場狀態", "spot"),
            ("BTC 的市場狀態", "medium"),  # 未明示 → 預設
        ],
    )
    def test_primary_horizon_reaches_step_a_and_b(self, question: str, expected: str):
        client = self._run(question)
        step_a, step_b = client.prompts[0], client.prompts[1]
        assert f"本次主判斷視野為 {expected}" in step_a
        assert f"本次主判斷視野為 {expected}" in step_b

    def test_year_question_lets_long_bands_vote(self):
        """回歸：問「最近一年」時 long/structural 必須被列進 direction_matrix 範圍。

        修正前這裡會是 `spot／short／medium`，而 `compute_signal_consensus()`
        卻用 primary=structural 收票——模型被指示不要產出的列，計分層在等。
        """
        step_b = self._run("BTC 最近一年的市場狀態").prompts[1]
        assert "只針對 horizon 為 spot／short／medium／long／structural（當前訊號帶）" in step_b
        assert "只針對 horizon 為 spot／short／medium（當前訊號帶）" not in step_b

    def test_intraday_question_narrows_to_spot(self):
        """反向：問「今天」時只有 spot 該投票，否則計分層會把 short/medium 的票丟掉。"""
        step_b = self._run("BTC 今天盤中的市場狀態").prompts[1]
        assert "只針對 horizon 為 spot（當前訊號帶）" in step_b

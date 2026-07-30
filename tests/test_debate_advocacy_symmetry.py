"""辯論雙方的立場堅持規則必須對稱（vic 2026-07-29 拍板）。

原設計只有正方帶「你的論證必須誠實：若證據其實薄弱…要在論證中承認，不要誇大成
過度肯定的語氣」，反方沒有對等條款。後果是裁判讀到語氣不對等的兩段論證——正方
自帶但書、反方語氣篤定——而那是**修辭差異不是論據差異**，卻會被當成論據強弱來讀。

拍板的方向是「不要美化，但選定論述後不要自曝其短，讓對方反駁」：
  - 立場力度 → 雙方都拉滿，不預留退路（對抗式辯論的價值全在這裡）
  - 證據呈現 → 雙方都照實（信任提煉流水線不能在中間層注入雜訊）

因此本檔最核心的斷言是 `test_all_three_debaters_get_identical_text`：三個辯論
prompt 拿到的必須是**同一份文字**，任何一邊之後被單獨修改，這條就會紅。
"""

import pytest

from agent.reasoning.prompts import (
    DEBATE_ADVOCACY_RULE,
    DEBATE_WEIGHT_RULE,
    build_step_c_prompt,
    build_step_c1_bull_prompt,
    build_step_c1_bull_rebuttal_prompt,
    build_step_c2_bear_prompt,
    build_step_d_prompt,
)

_ROUNDS = [
    {
        "round": 1,
        "bull_argument": "正方第一輪",
        "bear_critique": "反方批評",
        "bear_argument": "反方第一輪",
        "bear_evidence_ids": ["ev-002"],
        "bull_evidence_ids": ["ev-001"],
    }
]


def _bull_r1() -> str:
    return build_step_c1_bull_prompt("BTC", "q", "multi_source", [], {})


def _bull_r2() -> str:
    return build_step_c1_bull_rebuttal_prompt("BTC", "q", "multi_source", [], {}, _ROUNDS)


def _bear() -> str:
    return build_step_c2_bear_prompt("BTC", "q", "multi_source", [], {}, "正方論證")


DEBATER_BUILDERS = {"bull_r1": _bull_r1, "bull_r2": _bull_r2, "bear": _bear}


class TestSymmetry:
    @pytest.mark.parametrize("role", sorted(DEBATER_BUILDERS))
    def test_all_three_debaters_get_identical_text(self, role: str):
        """正方兩輪與反方拿到逐字相同的規則。不對稱正是這次要修的缺陷。"""
        assert DEBATE_ADVOCACY_RULE in DEBATER_BUILDERS[role]()

    def test_no_side_specific_honesty_clause_remains(self):
        """舊的正方專屬條款必須完全消失，不能只在反方補一條了事。"""
        for build in DEBATER_BUILDERS.values():
            prompt = build()
            assert "你的論證必須誠實" not in prompt
            assert "不要誇大成過度肯定的語氣" not in prompt

    def test_weight_rule_still_symmetric_too(self):
        """既有的權重意識規則（R4-3）不因這次改動而失衡。"""
        for build in DEBATER_BUILDERS.values():
            assert DEBATE_WEIGHT_RULE in build()


class TestRuleContent:
    def test_forbids_volunteering_own_limitations(self):
        assert "不要替自己預留退路" in DEBATE_ADVOCACY_RULE
        assert "不要主動列出自己論證的限制或反例" in DEBATE_ADVOCACY_RULE
        assert "找漏洞是對手的工作" in DEBATE_ADVOCACY_RULE

    def test_still_forbids_embellishing_evidence(self):
        """「不自曝其短」不等於「可以美化證據」——這兩件事必須分開。"""
        assert "證據本身不得美化" in DEBATE_ADVOCACY_RULE
        assert "不可把證據講得比實際更硬" in DEBATE_ADVOCACY_RULE
        assert "宣稱某筆證據支持了它其實沒說的事" in DEBATE_ADVOCACY_RULE

    def test_separates_advocacy_strength_from_evidence_accuracy(self):
        """規則必須明講這兩個維度的分野，否則模型會把「誠實」誤讀成「別太肯定」。"""
        assert "要誠實的是「這筆證據寫了什麼」，不是「你的立場有多堅定」" in DEBATE_ADVOCACY_RULE


class TestFallbackExcluded:
    """單模型 fallback **不掛**這條規則。

    `build_step_c_prompt` 沒有對手，而且被要求為每個假設列出
    `opposing_evidence_ids`。叫它「別提自己的限制」會與該欄位直接打架——
    那條路徑要的是多假設並陳，不是辯護。
    """

    def _fallback(self) -> str:
        return build_step_c_prompt("BTC", "q", "multi_source", [], {})

    def test_advocacy_rule_absent(self):
        assert DEBATE_ADVOCACY_RULE not in self._fallback()

    def test_opposing_evidence_still_required(self):
        prompt = self._fallback()
        assert "反對/削弱它的 evidence id" in prompt
        assert "opposing_evidence_ids" in prompt

    def test_weight_rule_still_present(self):
        """權重意識與有沒有對手無關，fallback 仍要有（R4-3）。"""
        assert DEBATE_WEIGHT_RULE in self._fallback()


class TestJudgeCompensates:
    """辯士不再自曝其短之後，打折的工作全部落到裁判身上。

    而且回合順序是「每輪正方先、反方後」，所以**反方最後一輪沒有人反駁過**。
    正方的漏洞有反方會挖，反方最後那段只有裁判會看到——不補這兩條，
    拿掉正方的自我設限反而會把不對稱放大，與「雙方同等」的拍板方向相反。
    """

    def _judge(self) -> str:
        debate = {
            "rounds": _ROUNDS,
            "stopped_reason": "converged",
            "bull_argument": "正方第一輪",
            "bear_argument": "反方第一輪",
            "bear_critique": "反方批評",
        }
        return build_step_d_prompt("BTC", "q", "multi_source", [], {}, [], debate=debate)

    def test_judge_told_both_sides_lack_caveats(self):
        prompt = self._judge()
        assert "雙方都被要求只管建構己方論證、不主動交代自身弱點" in prompt
        assert "語氣篤定不等於論據紮實" in prompt
        assert "同等的檢視" in prompt

    def test_judge_told_bear_last_argument_is_unrebutted(self):
        prompt = self._judge()
        assert "反方的最後一輪論證沒有人反駁過" in prompt

    def test_judge_told_volume_gap_is_a_format_artifact(self):
        """待辦 12⑥ 的裁判側：報告已對**讀者**揭露版面音量 2:1（`TestDebateRenderingLabels`），
        但真正打分的是裁判，而裁判讀到的逐字稿同樣是反方兩段、正方一段。

        只擋語氣（守則 3 既有的「語氣篤定不等於論據紮實」）擋不住篇幅——
        反方的 critique/argument 分別計算長度上限，結構上就會比正方長。
        """
        prompt = self._judge()
        assert "不可因為某一方字數較多就認為它比較有份量" in prompt
        assert "版面格式造成的，不是論據比較多" in prompt

    def test_existing_critique_duty_survives(self):
        """既有守則不得被這次新增擠掉（防裁判偷懶直接採信正方）。"""
        prompt = self._judge()
        assert "你必須明確評估反方的批評是否成立" in prompt
        assert "不可略過批評直接採信正方" in prompt

    def test_no_judge_rules_without_debate(self):
        """沒有辯論紀錄時整段守則不出現——沒有辯論就沒有裁判可言（R6-1）。"""
        prompt = build_step_d_prompt("BTC", "q", "multi_source", [], {}, [], debate=None)
        assert "裁判守則" not in prompt
        assert "反方的最後一輪論證沒有人反駁過" not in prompt


class TestDebateLengthRuleIsUniversal:
    """待辦 11：長度上限原本只加在正方第 2 輪。

    那條是 Task 3.8 實測踩到「27 筆證據時輸出被 max_tokens 截斷、燒掉 360 秒且
    整輪作廢」才補的。第 1 輪面對同樣的證據量卻沒有任何約束，承擔同一個截斷風險，
    而且沒有前輪逐字稿在旁邊約束它。三個辯論位置必須共用同一份文字。
    """

    def _prompts(self):
        from agent.reasoning.prompts import (
            build_step_c1_bull_prompt,
            build_step_c1_bull_rebuttal_prompt,
            build_step_c2_bear_prompt,
        )

        facts, cv = [{"summary": "s", "evidence_ids": []}], {"consistent_signals": []}
        rounds = [{"round": 1, "bull_argument": "a", "bear_critique": "c", "bear_argument": "b"}]
        return {
            "C1 第1輪": build_step_c1_bull_prompt("BTC", "q", "multi_source", facts, cv),
            "C1 第2輪": build_step_c1_bull_rebuttal_prompt(
                "BTC", "q", "multi_source", facts, cv, rounds
            ),
            "C2": build_step_c2_bear_prompt("BTC", "q", "multi_source", facts, cv, "bull"),
        }

    def test_all_three_get_the_length_rule(self):
        from agent.reasoning.prompts import DEBATE_LENGTH_RULE

        for name, prompt in self._prompts().items():
            assert DEBATE_LENGTH_RULE in prompt, f"{name} 缺長度上限，承擔截斷風險"

    def test_round1_no_longer_invites_prose(self):
        """「可以是一段完整的話」在反向誘導模型寫成一坨散文，已移除。"""
        for name, prompt in self._prompts().items():
            assert "可以是一段完整的話" not in prompt, name


class TestJudgeRewardSymmetry:
    """待辦 12③：裁判守則原本只有「反方打中 → 下修」，沒有「正方擋住 → 上修」。

    實證：四次真實 Bedrock 執行的 debate_adjustment 分別是 -10／-12／-6／-10，
    **全部為負、一次都沒有正的**。再疊上 ADR-5 的 −15~+5 不對稱範圍，
    系統結構上幾乎不可能往上走——「辯論後信心」實際上只是「辯論後扣分」。
    """

    def _judge_prompt(self):
        from agent.reasoning.prompts import build_step_d_prompt

        return build_step_d_prompt(
            "BTC",
            "q",
            "multi_source",
            [{"summary": "s", "evidence_ids": []}],
            {"consistent_signals": []},
            [],
            debate={"rounds": [{"round": 1, "bull_argument": "a", "bear_critique": "c",
                                "bear_argument": "b"}]},
        )

    def test_judge_has_upward_trigger_not_only_downward(self):
        prompt = self._judge_prompt()
        assert "下修" in prompt, "前提：下修觸發條件仍在"
        assert "上調" in prompt, "缺少『正方擋住批評 → 上調』的觸發條件"

    def test_asymmetry_is_about_magnitude_not_direction(self):
        """範圍不對稱（−15~+5）是刻意的，但那限制的是幅度不是方向。"""
        prompt = self._judge_prompt()
        assert "不對稱指的是「幅度」不是「方向」" in prompt

    def test_zero_is_explicitly_wrong_when_critiques_fail(self):
        assert "0 分是錯的答案" in self._judge_prompt()


class TestDebateRenderingLabels:
    """待辦 12⑥：反方每輪兩段、正方一段，版面音量天然 2:1。

    那是輸出欄位的結構差異，不是論據強弱。不講明的話讀者容易把「講得多」
    讀成「比較有理」。
    """

    def _report(self):
        from agent.report.builder import build_report_markdown
        from agent.reasoning.pipeline import ReasoningResult
        from agent.schemas import Evidence, now_iso

        ev = Evidence(id="ev-001", coin="BTC", source="s", fetched_at=now_iso(),
                      content_reference="c", related_claim="r", source_type="price")
        result = ReasoningResult(
            question_type="multi_source",
            facts=[{"summary": "s", "evidence_ids": ["ev-001"]}],
            conclusion={"market_judgment": "m", "confidence": "中", "evidence_ids": ["ev-001"]},
            debate={
                "rounds": [
                    {"round": 1, "bull_argument": "正1", "bull_evidence_ids": ["ev-001"],
                     "bear_critique": "批1", "bear_argument": "反1", "bear_evidence_ids": []},
                    {"round": 2, "bull_argument": "正2", "bull_evidence_ids": ["ev-001"],
                     "bear_critique": "批2", "bear_argument": "反2", "bear_evidence_ids": []},
                ],
                "round_count": 2,
            },
        )
        return build_report_markdown("BTC", "q", result, [ev])

    def test_discloses_structural_volume_asymmetry(self):
        assert "篇幅差異來自輸出結構而非論據強弱" in self._report()

    def test_round2_bull_labelled_as_rebuttal_not_mere_restatement(self):
        """正方第 2 輪也在攻防，標成「正方論證」會讓它看起來只是重講一次。"""
        md = self._report()
        assert "*正方立論：*" in md
        assert "*正方回應反方批評並修正論證：*" in md

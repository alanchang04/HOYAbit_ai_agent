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

"""Task 3.9 / R4-3：辯論層 Step C1/C2 的 prompt 必須帶到權重意識。

規則本身不夠——C1/C2 只拿得到 facts／cross_validation 這兩份摘要，裡面只有
evidence id。若不同時附上權重索引，「不可把不同權重的證據當成勢均力敵」這條要求
模型只能靠猜，所以這裡同時驗規則文字與索引資料兩件事。
"""

import pytest

from agent.reasoning.prompts import (
    DEBATE_WEIGHT_RULE,
    build_step_c1_bull_prompt,
    build_step_c1_bull_rebuttal_prompt,
    build_step_c2_bear_prompt,
    build_step_c_prompt,
    format_evidence_weight_index,
)
from agent.schemas import Evidence


def _ev(**overrides):
    base = dict(
        id="ev-001",
        coin="BTC",
        source="official_csv",
        fetched_at="2026-07-25T00:00:00Z",
        content_reference="MA120 位置：現價位於 5 年分佈第 88 百分位",
        related_claim="x",
        source_type="price",
        source_weight=0.92,
        weight_reason="四因子 w=0.92｜新鮮度1.00×來源等級0.95(A+:官方基準資料)×覆蓋度1.00×dedup1.00",
        window_start="2021-06-01",
        window_end="2026-05-31",
        horizon_class="structural",
    )
    base.update(overrides)
    return Evidence(**base)


def _low_ev():
    return _ev(
        id="ev-009",
        source="reddit",
        source_type="social",
        source_weight=0.31,
        weight_reason="四因子 w=0.31｜新鮮度0.80×來源等級0.40(C:匿名論壇)×覆蓋度1.00×dedup0.97",
        window_start="2026-07-19",
        window_end="2026-07-25",
        horizon_class="short",
    )


def _debate_prompts(evidences):
    """四個推論層 prompt：正方首輪／正方反駁輪／反方／單模型降級。"""
    common = ("BTC", "分析 BTC 過去兩週", "multi_source", [], {})
    rounds = [{"round": 1, "bull_argument": "正方", "bear_critique": "批評", "bear_argument": "反方"}]
    return {
        "bull_r1": build_step_c1_bull_prompt(*common, evidences=evidences),
        "bull_r2": build_step_c1_bull_rebuttal_prompt(*common, rounds, round_no=2, evidences=evidences),
        "bear": build_step_c2_bear_prompt(*common, "正方論證", rounds=rounds, evidences=evidences),
        "fallback": build_step_c_prompt(*common, evidences=evidences),
    }


@pytest.mark.parametrize("name", ["bull_r1", "bull_r2", "bear", "fallback"])
def test_debate_prompts_state_weight_rule(name):
    """R4-3：四條推論路徑都要明講權重差距，不能只靠 SYSTEM_PROMPT 的全域規則。"""
    prompt = _debate_prompts([_ev(), _low_ev()])[name]
    assert DEBATE_WEIGHT_RULE in prompt
    assert "勢均力敵" in prompt


@pytest.mark.parametrize("name", ["bull_r1", "bull_r2", "bear", "fallback"])
def test_debate_prompts_carry_weight_index(name):
    """光有規則不夠：辯士得看得到每個 id 的權重與尺度才有辦法遵守。"""
    prompt = _debate_prompts([_ev(), _low_ev()])[name]
    assert "ev-001 | weight=0.92 [A+] | horizon=structural" in prompt
    assert "ev-009 | weight=0.31 [C] | horizon=short" in prompt


def test_bear_prompt_extends_rule_to_critique():
    """反方的攻擊面也適用：批評「證據薄弱」前要先看對方引用的權重高低。"""
    prompt = build_step_c2_bear_prompt(
        "BTC", "分析 BTC", "multi_source", [], {}, "正方論證", evidences=[_ev()]
    )
    assert "批評正方時同樣適用" in prompt


def test_weight_index_omits_content_reference():
    """索引只列可信度與尺度——內容已在事實層，重貼會讓多輪辯論的 prompt 無謂膨脹。"""
    index = format_evidence_weight_index([_ev()])
    assert "ev-001" in index and "weight=0.92" in index
    assert "MA120 位置" not in index
    assert "official_csv" not in index


def test_weight_index_degrades_without_grade():
    """weight_reason 解析不出分級時只省略標籤，權重數值仍要照給（優雅降級）。"""
    index = format_evidence_weight_index([_ev(weight_reason="legacy 舊制規則表 w=0.50", source_weight=0.50)])
    assert "weight=0.50" in index
    assert "[" not in index


def test_weight_index_empty_when_no_evidence():
    """無證據時整段索引省略，不留一個空標題在 prompt 裡。"""
    assert format_evidence_weight_index([]) == ""
    assert format_evidence_weight_index(None) == ""


@pytest.mark.parametrize("name", ["bull_r1", "bull_r2", "bear", "fallback"])
def test_debate_prompts_survive_without_evidences(name):
    """R6-1：拿不到證據清單時 prompt 仍要組得出來，只是少了索引，不得炸掉。"""
    prompt = _debate_prompts(None)[name]
    assert "證據權重與尺度索引" not in prompt
    assert DEBATE_WEIGHT_RULE in prompt          # 規則不隨索引一起消失
    assert "請只輸出以下 JSON 格式" in prompt

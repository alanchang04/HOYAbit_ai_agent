"""13_流程圖迭代定案v2.md Stage 6：辯論層 prompt 必須帶到證據關係圖。

同 test_debate_weight_awareness.py 的理由——規則文字不夠，C1/C2 只拿得到 facts／
cross_validation 這兩份摘要，裡面沒有證據彼此的 supports／conflicts／independent
關係。若不同時附上關係圖，「不可把 supports 的證據當獨立佐證疊加」這條規則
模型只能靠猜。
"""

import pytest

from agent.reasoning.prompts import (
    DEBATE_GRAPH_RULE,
    build_step_c1_bull_prompt,
    build_step_c1_bull_rebuttal_prompt,
    build_step_c2_bear_prompt,
    build_step_c_prompt,
    format_evidence_graph,
)
from agent.schemas import Evidence


def _ev(**overrides):
    base = dict(
        id="ev-001",
        coin="BTC",
        source="binance_funding",
        fetched_at="2026-07-25T00:00:00Z",
        content_reference="funding rate 97th percentile",
        related_claim="x",
        source_type="derivatives",
        source_weight=0.8,
    )
    base.update(overrides)
    return Evidence(**base)


def _linked_evidences():
    ev1 = _ev(id="ev-001", related_evidence={"confirms": ["ev-002"], "conflicts": ["ev-003"]})
    ev2 = _ev(id="ev-002", source_type="onchain", content_reference="active address 上升")
    ev3 = _ev(id="ev-003", source_type="news", content_reference="ETF Approval", related_claim="y")
    return [ev1, ev2, ev3]


def _debate_prompts(evidences):
    common = ("BTC", "分析 BTC 過去兩週", "multi_source", [], {})
    rounds = [{"round": 1, "bull_argument": "正方", "bear_critique": "批評", "bear_argument": "反方"}]
    return {
        "bull_r1": build_step_c1_bull_prompt(*common, evidences=evidences),
        "bull_r2": build_step_c1_bull_rebuttal_prompt(*common, rounds, round_no=2, evidences=evidences),
        "bear": build_step_c2_bear_prompt(*common, "正方論證", rounds=rounds, evidences=evidences),
        "fallback": build_step_c_prompt(*common, evidences=evidences),
    }


@pytest.mark.parametrize("name", ["bull_r1", "bull_r2", "bear", "fallback"])
def test_debate_prompts_state_graph_rule(name):
    prompt = _debate_prompts(_linked_evidences())[name]
    assert DEBATE_GRAPH_RULE in prompt
    assert "只能算一組訊號" in prompt


@pytest.mark.parametrize("name", ["bull_r1", "bull_r2", "bear", "fallback"])
def test_debate_prompts_carry_evidence_graph(name):
    prompt = _debate_prompts(_linked_evidences())[name]
    assert "ev-001 ── supports ──▶ ev-002" in prompt
    assert "ev-001 ── conflicts ──▶ ev-003" in prompt


def test_graph_omits_relations_to_unknown_or_quarantined_ids():
    """指到清單外的 id（資料沒同步齊全）不可出現在圖裡，避免辯士去引用一個查無此證的 id。"""
    ev1 = _ev(id="ev-001", related_evidence={"confirms": ["ev-999"]})
    graph = format_evidence_graph([ev1])
    assert graph == ""


def test_graph_empty_when_no_relations():
    """證據之間沒有宣告任何關係時，整段省略，不留空標題。"""
    assert format_evidence_graph([_ev()]) == ""
    assert format_evidence_graph([]) == ""
    assert format_evidence_graph(None) == ""


def test_graph_omits_content_reference():
    """跟權重索引同理：只列關係，不重貼內容，省 prompt 長度。"""
    graph = format_evidence_graph(_linked_evidences())
    assert "active address" not in graph
    assert "ETF Approval" not in graph

"""驗證 comparison 題型（雙幣種）的 prompt framing 與推理鏈是否正確帶入 coin2。"""

from agent.reasoning.prompts import (
    build_step_c1_bull_prompt,
    build_step_c2_bear_prompt,
    build_step_d_prompt,
)


def test_bull_prompt_frames_comparison_with_both_coins():
    prompt = build_step_c1_bull_prompt("BTC", "比較 BTC 與 ETH", "comparison", [], {}, coin2="ETH")
    assert "BTC" in prompt and "ETH" in prompt
    assert "相對於" in prompt  # 具體對抗框架用語


def test_bear_prompt_frames_opposite_side_of_comparison():
    prompt = build_step_c2_bear_prompt("BTC", "比較 BTC 與 ETH", "comparison", [], {}, "正方論證內容", coin2="ETH")
    assert "ETH 相對於 BTC" in prompt or "ETH" in prompt


def test_bull_prompt_without_coin2_uses_generic_single_coin_framing():
    prompt = build_step_c1_bull_prompt("BTC", "分析 BTC 市場狀態", "multi_source", [], {})
    assert "BTC" in prompt
    assert "相對於" not in prompt


def test_step_d_prompt_mentions_both_coins_when_comparison():
    prompt = build_step_d_prompt("BTC", "比較 BTC 與 ETH", "comparison", [], {}, [], coin2="ETH")
    assert "BTC" in prompt and "ETH" in prompt

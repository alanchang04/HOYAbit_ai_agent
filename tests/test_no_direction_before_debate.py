"""Ken v3 核心主張：**Debate 之前，系統中不存在任何方向性結論**（2026-07-31）。

Ken 的 v3 提案把這件事講成「移除 Claim」，但實測我們的 `related_claim` 裝的全是
主題標籤（「BTC 鏈上活躍度」「BTC 官方發布新聞事件」），沒有一筆是方向性結論——
診斷指錯了欄位。真正的錨定在 `direction_matrix`：Step B 讓模型對六類來源各投一次
1／0／−1，然後整包 `cross_validation` 餵進正方、反方、正方反駁、反方第二輪與裁判
五個 prompt，等於雙方開口前先看到六個預先算好的方向判決。

2026-07-31 那次真實執行的表是 price=−1（權重 0.92 全場最高）／macro=−1／
derivatives=+1／其餘 0，淨值偏空——正方要推翻的不只是反方的論證，還有一份
已登記在案的表態。這與「`debate_adjustment` 連續五次全負」的觀察互相呼應。

這裡鎖住的不變量：`direction_matrix` 在 Step B **產生**、只給計分層用，
**不進任何下游 LLM prompt**；而質性的交叉驗證內容全部保留。
"""

from agent.reasoning.prompts import (
    build_step_b_prompt,
    build_step_c1_bull_prompt,
    build_step_c1_bull_rebuttal_prompt,
    build_step_c2_bear_prompt,
    build_step_c_prompt,
    build_step_d_prompt,
)
from agent.schemas import Evidence

# Step B 的真實產出形狀（含方向表與三段質性內容）
CROSS_VALIDATION = {
    "consistent_signals": ["衍生品與鏈上同步走強（ev-009, ev-011）"],
    "contradictions": ["價格走弱但未平倉量上升（ev-001 vs ev-027）"],
    "structural_context": ["現價位於五年分佈第 88 百分位（ev-005）"],
    "direction_matrix": [
        {"source_type": "price", "direction": -1, "basis": ["ev-001"]},
        {"source_type": "derivatives", "direction": 1, "basis": ["ev-009"]},
        {"source_type": "macro", "direction": -1, "basis": ["ev-022"]},
    ],
}

ROUNDS = [{"round": 1, "bull_argument": "正方", "bear_critique": "批評", "bear_argument": "反方"}]


def _ev(**overrides):
    base = dict(
        id="ev-001",
        coin="BTC",
        source="official_csv",
        fetched_at="2026-07-25T00:00:00Z",
        content_reference="MA120 位置：現價位於 5 年分佈第 88 百分位",
        related_claim="BTC 長期結構位置",
        source_type="price",
        source_weight=0.92,
        weight_reason="四因子 w=0.92｜新鮮度1.00×來源等級0.95(A+:官方基準資料)×覆蓋度1.00×dedup1.00",
        horizon_class="structural",
    )
    base.update(overrides)
    return Evidence(**base)


def _downstream_prompts() -> dict[str, str]:
    """Step B 之後、會看到 cross_validation 的五個 prompt。"""
    common = ("BTC", "分析 BTC 過去兩週", "multi_source", [], CROSS_VALIDATION)
    return {
        "bull_r1": build_step_c1_bull_prompt(*common, evidences=[_ev()]),
        "bull_r2": build_step_c1_bull_rebuttal_prompt(*common, ROUNDS, round_no=2, evidences=[_ev()]),
        "bear": build_step_c2_bear_prompt(*common, "正方論證", rounds=ROUNDS, evidences=[_ev()]),
        "fallback": build_step_c_prompt(*common, evidences=[_ev()]),
        "judge": build_step_d_prompt("BTC", "分析 BTC", "multi_source", [], CROSS_VALIDATION, []),
    }


class TestNoDirectionMatrixDownstream:
    def test_no_prompt_after_step_b_contains_direction_matrix(self):
        """五個下游 prompt 一個都不准看到方向表——這是 Ken v3 主張的具體落地。"""
        for name, prompt in _downstream_prompts().items():
            assert "direction_matrix" not in prompt, f"{name} 仍帶有 direction_matrix"

    def test_no_prompt_after_step_b_contains_direction_verdicts(self):
        """不只欄位名，預先算好的表態值本身也不可外洩。"""
        for name, prompt in _downstream_prompts().items():
            assert '"direction": -1' not in prompt, f"{name} 洩漏了看空表態"
            assert '"direction": 1' not in prompt, f"{name} 洩漏了看多表態"

    def test_qualitative_cross_validation_is_preserved(self):
        """**只拿掉方向表，不拿掉質性內容**——那三段是辯論的原料，抽掉就沒得吵了。"""
        for name, prompt in _downstream_prompts().items():
            assert "衍生品與鏈上同步走強" in prompt, f"{name} 掉了 consistent_signals"
            assert "價格走弱但未平倉量上升" in prompt, f"{name} 掉了 contradictions"
            assert "現價位於五年分佈第 88 百分位" in prompt, f"{name} 掉了 structural_context"


class TestStepBStillProducesDirectionMatrix:
    """移除的是「傳下去」，不是「不再產生」——計分層仍然需要它。"""

    def test_step_b_still_asks_for_direction_matrix(self):
        prompt = build_step_b_prompt("BTC", "分析 BTC", [_ev()], facts=[])
        assert "direction_matrix" in prompt
        assert "1（看多）" in prompt and "-1（看空）" in prompt

    def test_signal_consensus_still_consumes_direction_matrix(self):
        """Signal Consensus 佔基底分 40%，仍由這份表決定性算出。"""
        from agent.reasoning.confidence import compute_signal_consensus

        evidences = [
            _ev(id="ev-001", source_type="price", horizon_class="short"),
            _ev(id="ev-009", source_type="derivatives", horizon_class="short"),
            _ev(id="ev-022", source_type="macro", horizon_class="short"),
        ]
        score, detail = compute_signal_consensus(CROSS_VALIDATION["direction_matrix"], evidences)
        assert detail["sample_size"] == 3
        assert 0 <= score <= 100

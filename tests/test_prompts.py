"""horizon-aware Phase 3：證據清單含 horizon/window/weight、Step B 三段＋direction_matrix、
Step D 裁判調整欄位、SYSTEM_PROMPT 權重與尺度規則。"""

from agent.reasoning.prompts import (
    SYSTEM_PROMPT,
    _format_evidence_list,
    build_step_a_prompt,
    build_step_b_prompt,
    build_step_d_prompt,
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


def test_evidence_list_includes_weight_grade_horizon_window():
    out = _format_evidence_list([_ev()])
    assert "weight=0.92" in out
    assert "[A+]" in out          # 分級標籤解析自 weight_reason
    assert "horizon=structural" in out
    assert "window=2021-06-01~2026-05-31" in out


def test_evidence_list_spot_has_na_window():
    ev = _ev(horizon_class="spot", window_start=None, window_end=None)
    out = _format_evidence_list([ev])
    assert "horizon=spot" in out
    assert "window=n/a" in out


def test_evidence_list_keeps_fetched_at():
    """spot 類沒有觀察窗，抽掉 fetched_at 模型就沒有任何時間參考可用。"""
    out = _format_evidence_list([_ev(horizon_class="spot", window_start=None, window_end=None)])
    assert "fetched_at=2026-07-25T00:00:00Z" in out


def test_evidence_list_omits_grade_when_unparseable():
    ev = _ev(source_weight=0.50, weight_reason="legacy 舊制規則表 w=0.50")
    out = _format_evidence_list([ev])
    assert "weight=0.50" in out
    assert "[" not in out.split("weight=0.50")[1].split("|")[0]  # 該欄位無分級中括號


def test_system_prompt_has_horizon_and_weight_rules():
    assert "horizon" in SYSTEM_PROMPT
    assert "低權重證據不足以單獨推翻高權重證據" in SYSTEM_PROMPT


class TestEvidenceListPrioritySorting:
    """R8-4：priority = source_weight × base_importance × horizon_match，高分排前面。"""

    def _ids_in_order(self, out: str) -> list[str]:
        # 清單被 EVIDENCE_BLOCK_START/END 包住（注入防護的界線標記），
        # 只取真正的證據列。
        return [
            line.split("id=")[1].split(" ")[0]
            for line in out.splitlines()
            if line.startswith("- id=")
        ]

    def test_higher_base_importance_source_type_sorts_first(self):
        # 同權重、同 horizon，只有 source_type 不同：price(1.0) 該排在 social(0.5) 前面。
        price_ev = _ev(id="ev-101", source_type="price", source_weight=0.8, horizon_class="short")
        social_ev = _ev(id="ev-102", source_type="social", source_weight=0.8, horizon_class="short")
        out = _format_evidence_list([social_ev, price_ev])
        assert self._ids_in_order(out) == ["ev-101", "ev-102"]

    def test_structural_context_still_present_but_ordered_later(self):
        # 同 source_type/weight，只有 horizon 落在結構脈絡帶（>主視野）者該排後面，但不能消失。
        current_ev = _ev(id="ev-201", source_type="price", source_weight=0.8, horizon_class="short")
        structural_ev = _ev(id="ev-202", source_type="price", source_weight=0.8, horizon_class="structural")
        out = _format_evidence_list([structural_ev, current_ev], primary_horizon="short")
        ids = self._ids_in_order(out)
        assert ids == ["ev-201", "ev-202"]

    def test_no_evidence_dropped(self):
        evs = [
            _ev(id=f"ev-{300 + i}", source_type=t, horizon_class=h)
            for i, (t, h) in enumerate(
                [("price", "spot"), ("social", "structural"), ("news", "medium"), ("macro", "long")]
            )
        ]
        out = _format_evidence_list(evs)
        assert out.count("- id=") == 4

    def test_comparison_question_type_demotes_social_below_price(self):
        # signal_importance.json 的 comparison 覆寫層把 social 壓到 0.3，price 仍是 1.0，
        # 差距應比未覆寫時更大，但排序方向（price 先）不變。
        price_ev = _ev(id="ev-401", source_type="price", source_weight=0.6, horizon_class="short")
        social_ev = _ev(id="ev-402", source_type="social", source_weight=0.6, horizon_class="short")
        out = _format_evidence_list([social_ev, price_ev], question_type="comparison")
        assert self._ids_in_order(out) == ["ev-401", "ev-402"]

    def test_empty_list_unaffected(self):
        # 界線標記照樣輸出——「本次無證據」也是要交代給模型的事實。
        assert "（本次無可用證據）" in _format_evidence_list([])


def test_step_a_prompt_has_legend():
    prompt = build_step_a_prompt("BTC", "分析 BTC 過去兩週", [_ev()])
    assert "【時間尺度說明】" in prompt
    assert "【權重說明】" in prompt


def test_step_b_prompt_has_three_sections_and_direction_matrix():
    prompt = build_step_b_prompt("BTC", "分析 BTC", [_ev()], facts=[])
    assert "consistent_signals" in prompt
    assert "contradictions" in prompt
    assert "structural_context" in prompt
    assert "direction_matrix" in prompt
    # 明確約束：跨尺度不算矛盾、direction 限三值
    # 措辭由「不同尺度」改為「比主視野更長的尺度」（Task 8.4）：分帶說明改成隨主視野
    # 生成後，「不同尺度」的講法在主視野=structural 時是錯的——那時五帶皆為當前訊號，
    # 長窗的反向訊號就是真矛盾。這裡斷言的仍是同一條規則，只是限定範圍。
    assert "比主視野更長的尺度落差不是矛盾" in prompt
    assert "1（看多）" in prompt and "-1（看空）" in prompt


def test_step_b_structural_context_has_length_cap():
    """2026-07-30：實測 structural_context 曾產出 6318 字（單題 5-6 點），
    比它要輔助的矛盾訊號節（417 字）長 15 倍。每點應是一句話，不是重新論證一次。"""
    prompt = build_step_b_prompt("BTC", "分析 BTC 最近兩週的整體市場狀態", [_ev()], facts=[])
    assert "100 字以內" in prompt
    assert "不需要重新論證為什麼" in prompt


def test_step_d_omits_duplicate_argument_text_when_debate_present():
    """HANDOFF 6.3：有辯論紀錄時，推論層不再重複貼上同一段論證全文。

    但辯論紀錄不印 evidence id，所以 id 對應必須保留——不能整段拿掉。
    """
    long_bull = "正方論證：" + "資金費率百分位偏低顯示槓桿不擁擠。" * 10
    inference = [
        {
            "hypothesis": f"[正方] {long_bull}",
            "supporting_evidence_ids": ["ev-001"],
            "opposing_evidence_ids": ["ev-002"],
        }
    ]
    debate = {
        "rounds": [{"round": 1, "bull_argument": long_bull, "bear_critique": "批評", "bear_argument": "反方"}],
        "stopped_reason": "converged",
    }
    prompt = build_step_d_prompt("BTC", "分析 BTC", "multi_source", [], {}, inference, debate=debate)

    assert prompt.count(long_bull) == 1          # 全文只出現在辯論紀錄那一份
    assert "ev-001" in prompt and "ev-002" in prompt  # id 對應仍在
    assert "論證全文見下方辯論紀錄" in prompt


def test_step_d_keeps_full_inference_without_debate():
    """沒有辯論紀錄（降級走單模型）時，推論層必須照舊完整帶上。"""
    inference = [{"hypothesis": "假設一的完整敘述", "supporting_evidence_ids": ["ev-001"], "opposing_evidence_ids": []}]
    prompt = build_step_d_prompt("BTC", "分析 BTC", "multi_source", [], {}, inference, debate=None)
    assert "假設一的完整敘述" in prompt
    assert "論證全文見下方辯論紀錄" not in prompt


def test_step_d_prompt_has_debate_adjustment_fields():
    prompt = build_step_d_prompt("BTC", "分析 BTC", "multi_source", [], {}, [])
    assert "debate_adjustment" in prompt
    assert "debate_adjustment_reason" in prompt
    assert "-15" in prompt and "+5" in prompt          # 不對稱範圍
    assert "權重分佈" in prompt                          # R4-4 裁判考量權重


def test_step_d_prompt_requires_debate_summary_when_debate_present():
    """有辯論紀錄時，裁判要先整理攻防重點再下結論——不是逐字稿的濃縮版。"""
    debate = {
        "rounds": [{"round": 1, "bull_argument": "正方", "bear_critique": "批評", "bear_argument": "反方"}],
        "stopped_reason": "converged",
    }
    prompt = build_step_d_prompt("BTC", "分析 BTC", "multi_source", [], {}, [], debate=debate)
    assert "debate_summary" in prompt
    assert "誰的哪個論點站得住腳" in prompt


def test_step_d_prompt_forbids_fabricated_summary_without_debate():
    """沒有辯論（fallback 路徑）時，明確禁止裁判虛構攻防內容。"""
    prompt = build_step_d_prompt("BTC", "分析 BTC", "multi_source", [], {}, [], debate=None)
    assert "debate_summary" in prompt
    assert "不要虛構攻防內容" in prompt
    assert "誰的哪個論點站得住腳" not in prompt


def test_step_d_fallback_schema_shows_empty_summary_not_an_example():
    """fallback 路徑的**格式範例**也必須是空陣列，不能秀一筆攻防範例。

    散文說「請輸出空陣列」而格式範例照樣秀「反方對…的批評成立」，等於一邊禁止
    虛構攻防、一邊示範怎麼虛構——模型抄格式範例的傾向強過讀散文。
    而 `_sanitize_debate_summary()` 只濾不存在的 evidence id，**編出來的 point
    字串會原樣留到報告裡**，這裡放行就沒有第二道防線。
    """
    for debate in (None, {}, {"rounds": [], "stopped_reason": "bull_failed"}):
        prompt = build_step_d_prompt(
            "BTC", "分析 BTC", "multi_source", [], {}, [], debate=debate
        )
        assert '"debate_summary": [],' in prompt, f"debate={debate!r} 的格式範例不是空陣列"
        assert "正方未能有效反駁" not in prompt, f"debate={debate!r} 仍在示範虛構攻防"


def test_step_d_schema_keeps_summary_example_when_debate_present():
    """有辯論時格式範例要保留 {point, evidence_ids} 示範，否則模型不知道該給什麼。"""
    debate = {
        "rounds": [{"round": 1, "bull_argument": "正方", "bear_critique": "批評", "bear_argument": "反方"}],
        "stopped_reason": "converged",
    }
    prompt = build_step_d_prompt("BTC", "分析 BTC", "multi_source", [], {}, [], debate=debate)
    assert '"point"' in prompt and '"evidence_ids"' in prompt
    assert '"debate_summary": [],' not in prompt

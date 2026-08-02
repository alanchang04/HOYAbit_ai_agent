"""驗證 Step A 事實層的決定性 grounding validator（見 agent/reasoning/grounding.py）。

涵蓋使用者實測回報的三類幻覺，以及本次額外找到的跨來源數字拼接案例。
"""

from agent.reasoning.grounding import check_fact_grounding
from agent.schemas import Evidence, now_iso


def _ev(id_: str, content_reference: str, source_type: str = "price") -> Evidence:
    return Evidence(
        id=id_,
        coin="BTC",
        source="test-source",
        fetched_at=now_iso(),
        content_reference=content_reference,
        related_claim="claim",
        source_type=source_type,
    )


def _by_id(*evidences: Evidence) -> dict[str, Evidence]:
    return {e.id: e for e in evidences}


def test_clean_fact_passes():
    ev = _ev("ev-001", "RSI14=45.2（中性區間），近14日日報酬波動率=1.49%")
    fact = {"summary": "RSI14 為 45.2，14 日波動率 1.49%", "evidence_ids": ["ev-001"]}
    assert check_fact_grounding(fact, _by_id(ev)) == []


def test_indicator_not_mentioned_in_source_is_flagged():
    """ev-001 完全沒提 RSI（連字都沒出現），fact 卻生成 RSI 敘述。"""
    ev = _ev("ev-001", "近 14 日收盤價與成交量摘要")
    fact = {"summary": "RSI 指標顯示動能減弱", "evidence_ids": ["ev-001"]}
    violations = check_fact_grounding(fact, _by_id(ev))
    assert any("RSI" in v for v in violations)


def test_indicator_explicitly_marked_unavailable_is_flagged_even_if_term_appears():
    """來源文字裡雖然出現「RSI」三個字，但是在「未提供」的否定語境裡，
    純字串比對若不處理否定詞會誤判成「有提供」。"""
    ev = _ev("ev-001", "本次未提供 RSI 指標，僅有收盤價")
    fact = {"summary": "RSI 指標顯示動能減弱", "evidence_ids": ["ev-001"]}
    violations = check_fact_grounding(fact, _by_id(ev))
    assert any("RSI" in v for v in violations)


def test_percentile_rewritten_as_percentage_is_flagged():
    """ev-002 原文是「第 15.6 百分位」（不帶 %），被改寫成「年化約 15.6%」——
    數值沒變但統計量被代換，用帶不帶 % 號來偵測這類代換。"""
    ev = _ev("ev-002", "近 90 筆（約 30 天）百分位 15.6（中性區間）")
    fact = {"summary": "過去 90 天有 30 天為正、年化約 15.6%", "evidence_ids": ["ev-002"]}
    violations = check_fact_grounding(fact, _by_id(ev))
    assert any("15.6" in v for v in violations)


def test_direction_reversed_is_flagged():
    """ev-003 明確寫 OI 下降，fact 卻改寫成穩定。"""
    ev = _ev("ev-003", "OI 持續下降，空頭主動離場", source_type="derivatives")
    fact = {"summary": "OI 維持穩定、未出現大幅減倉", "evidence_ids": ["ev-003"]}
    violations = check_fact_grounding(fact, _by_id(ev))
    assert any("方向" in v for v in violations)


def test_cross_source_number_blending_is_flagged():
    """算力案例：fact 只引用 ev-011，卻把 ev-010 的絕對值和 ev-011 的成長率拼在一起。"""
    ev011 = _ev("ev-011", "算力=985175354.00TH/s（近30天+3.53%）", source_type="onchain")
    fact = {
        "summary": "算力約 1042.6 EH/s，近 30 天增長 +3.53%",
        "evidence_ids": ["ev-011"],
    }
    violations = check_fact_grounding(fact, _by_id(ev011))
    assert any("1042.6" in v for v in violations)


def test_cross_source_number_not_flagged_when_both_ids_cited_and_kept_separate():
    """兩個來源都引用、且各自數字各自表述時（不拼接），不該被誤判。"""
    ev010 = _ev("ev-010", "hashrate_24h=1042615759256181050824", source_type="onchain")
    ev011 = _ev("ev-011", "算力=985175354.00TH/s（近30天+3.53%）", source_type="onchain")
    fact = {
        "summary": "近 30 天算力成長 +3.53%",
        "evidence_ids": ["ev-010", "ev-011"],
    }
    assert check_fact_grounding(fact, _by_id(ev010, ev011)) == []


def test_fabricated_number_with_no_source_at_all_is_flagged():
    ev = _ev("ev-001", "現價 63089 USD")
    fact = {"summary": "60,000 是關鍵支撐位", "evidence_ids": ["ev-001"]}
    violations = check_fact_grounding(fact, _by_id(ev))
    assert any("60000" in v for v in violations)


def test_fact_with_no_evidence_ids_and_a_number_is_flagged():
    fact = {"summary": "價格來到 63000", "evidence_ids": []}
    assert check_fact_grounding(fact, {}) != []


def test_small_integers_in_indicator_names_are_not_false_positives():
    """SMA7/MA20 這類指標名稱裡的小整數不該被當成需要獨立比對的數值。"""
    ev = _ev("ev-006", "SMA7=64088.88, SMA14=64646.48（現價跌破 SMA7）")
    fact = {"summary": "現價跌破 SMA7 與 SMA14", "evidence_ids": ["ev-006"]}
    assert check_fact_grounding(fact, _by_id(ev)) == []

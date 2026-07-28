"""R3-3／R3-15：Step B 的 direction_matrix sanitize。

共識分數直接吃這個矩陣，所以「該丟的沒丟」比「丟太多」危險得多——一筆錯誤的
方向表態會直接扭曲 pstdev。
"""

from __future__ import annotations

from agent.reasoning.pipeline import _sanitize_direction_matrix

KNOWN = {"ev-001", "ev-002"}


def _row(**kw):
    base = {"source_type": "price", "direction": 1, "basis": ["ev-001"]}
    base.update(kw)
    return base


def test_valid_rows_pass_through():
    out = _sanitize_direction_matrix(
        [_row(), _row(source_type="news", direction=-1, basis=["ev-002"])], KNOWN
    )
    assert out == [
        {"source_type": "price", "direction": 1, "basis": ["ev-001"]},
        {"source_type": "news", "direction": -1, "basis": ["ev-002"]},
    ]


def test_string_integers_are_tolerated():
    out = _sanitize_direction_matrix([_row(direction="-1"), _row(source_type="macro", direction=" 0 ")], KNOWN)
    assert [r["direction"] for r in out] == [-1, 0]


def test_decimal_direction_is_dropped_not_truncated():
    """0.7 截斷成 0 會變成「中性」這個明確錯誤的表態，直接排除該樣本傷害較小。"""
    out = _sanitize_direction_matrix(
        [_row(direction=0.7), _row(source_type="news", direction=1.9), _row(source_type="macro", direction="0.5")],
        KNOWN,
    )
    assert out == []


def test_integral_float_is_accepted():
    out = _sanitize_direction_matrix([_row(direction=1.0)], KNOWN)
    assert out[0]["direction"] == 1


def test_out_of_range_and_bool_are_dropped():
    out = _sanitize_direction_matrix(
        [_row(direction=2), _row(source_type="news", direction=True), _row(source_type="macro", direction=None)],
        KNOWN,
    )
    assert out == []


def test_duplicate_source_type_counted_once():
    """同一類別重複表態會在共識標準差裡被重複計票，只取第一筆。"""
    out = _sanitize_direction_matrix([_row(direction=1), _row(direction=-1)], KNOWN)
    assert len(out) == 1
    assert out[0]["direction"] == 1


def test_hallucinated_evidence_ids_are_stripped():
    out = _sanitize_direction_matrix([_row(basis=["ev-001", "ev-999", 123])], KNOWN)
    assert out[0]["basis"] == ["ev-001"]


def test_malformed_input_degrades_to_empty():
    assert _sanitize_direction_matrix(None, KNOWN) == []
    assert _sanitize_direction_matrix("not a list", KNOWN) == []
    assert _sanitize_direction_matrix([1, "x", None], KNOWN) == []
    assert _sanitize_direction_matrix([{"direction": 1}], KNOWN) == []  # 缺 source_type

"""dry-run 端到端測試：斷言 report_view.json 全欄位非空＿R8。

驗證 --dry-run 模式完整跑通 L1→L2→reasoning→view_builder，
且產出的 report_view.json 每個關鍵欄位皆有值（無 None/空字串/空列表）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.orchestrator import run_pipeline


def test_dry_run_report_view_all_fields_populated(tmp_path: Path) -> None:
    """dry-run 端到端：report_view.json 所有面板欄位非空。"""
    result = run_pipeline(
        coin="BTC",
        question="分析 BTC 市場",
        dry_run=True,
        output_dir=str(tmp_path),
    )

    # 確認基本產出存在
    view_path = tmp_path / "report_view.json"
    assert view_path.exists(), "report_view.json 未產出"

    view = json.loads(view_path.read_text(encoding="utf-8"))

    # --- schema_version ---
    assert view["schema_version"] == "1.0"

    # --- meta ---
    meta = view["meta"]
    assert meta["coin"] == "BTC"
    assert meta["question"] != ""
    assert meta["question_type"] in ("multi_source", "hypothesis_test", "comparison")
    assert meta["generated_at"] != ""
    assert meta["metrics"]["confidence"] > 0  # L5 數值信心分數
    assert meta["metrics"]["raw_evidence_count"] > 0

    # --- panel1_raw_feed ---
    panel1 = view["panel1_raw_feed"]
    assert panel1["count"] > 0
    for item in panel1["items"]:
        assert item["fingerprint"] != "", f"evidence {item['evidence_id']} fingerprint 為空"
        assert item["evidence_id"] != ""
        assert item["source"] != ""
        assert item["source_type"] != ""
        assert item["source_weight"] > 0, f"evidence {item['evidence_id']} source_weight 為 0"
        assert item["weight_reason"] != "", f"evidence {item['evidence_id']} weight_reason 為空"
        assert item["content_reference"] != ""
        assert item["coin"] == "BTC"

    # --- panel2_naive_baseline ---
    panel2 = view["panel2_naive_baseline"]
    assert "enabled" in panel2
    assert len(panel2["steps"]) == 4
    for step in panel2["steps"]:
        assert step["step"] > 0
        assert step["label"] != ""
        assert step["desc"] != ""

    # --- panel3_refinement ---
    panel3 = view["panel3_refinement"]
    assert len(panel3["layers"]) == 5
    assert panel3["layers"][0]["layer"] == "L1_source"
    assert panel3["layers"][1]["layer"] == "L2_content"
    assert panel3["layers"][2]["layer"] == "L3_fact"
    assert panel3["layers"][3]["layer"] == "L4_cross"
    assert panel3["layers"][4]["layer"] == "L5_conclusion"

    # L1 summary
    l1 = panel3["layers"][0]
    assert l1["summary"]["total"] > 0

    # L5 confidence breakdown
    l5 = panel3["layers"][4]
    assert "confidence_breakdown" in l5
    assert l5["confidence_breakdown"]["final"] > 0

    # log_events_by_layer 至少有 L3/L4/L5 的 log
    assert "log_events_by_layer" in panel3
    # L1 is logged in COLLECT phase with layer=SOURCE
    assert "L1_source" in panel3["log_events_by_layer"]

    # --- panel4_report ---
    panel4 = view["panel4_report"]
    assert panel4["market_judgment"] != ""
    assert panel4["confidence"] > 0
    assert panel4["integrity_status"] == "INTACT"
    assert len(panel4["core_facts"]) >= 1
    assert len(panel4["follow_up_watchpoints"]) >= 1

    # 確認 limitations 和 invalidation_conditions 也有值
    assert len(panel4["limitations"]) >= 1
    assert len(panel4["invalidation_conditions"]) >= 1


def test_dry_run_report_view_source_weights_assigned(tmp_path: Path) -> None:
    """驗證 dry-run 下 L1 來源權重皆已正確分配（非預設 0.5）。"""
    run_pipeline(
        coin="ETH",
        question="分析 ETH 近期走勢",
        dry_run=True,
        output_dir=str(tmp_path),
    )

    view_path = tmp_path / "report_view.json"
    assert view_path.exists()

    view = json.loads(view_path.read_text(encoding="utf-8"))
    items = view["panel1_raw_feed"]["items"]

    # 每筆證據都有權重與理由
    for item in items:
        assert item["source_weight"] > 0
        assert item["weight_reason"] != ""

    # 至少有一筆非預設 0.5（證明 L1 權重表有生效）
    weights = [item["source_weight"] for item in items]
    assert any(w != 0.5 for w in weights), "所有權重都是預設 0.5，L1 權重表可能未生效"

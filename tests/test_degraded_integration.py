"""test_degraded_integration：驗證任一層跳過 → integrity_status=DEGRADED＋view 註明。

Validates: Requirements R4-7
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.orchestrator import run_pipeline


def test_l2_failure_triggers_degraded_status(monkeypatch, tmp_path: Path) -> None:
    """L2 content filter 例外 → integrity_status=DEGRADED + view 說明原因。"""
    monkeypatch.setenv("DEGRADED_MODE_TRIGGER_SECONDS", "720")

    with patch(
        "agent.orchestrator.apply_content_filters",
        side_effect=RuntimeError("L2 模擬故障"),
    ):
        result = run_pipeline(
            coin="BTC",
            question="分析 BTC 過去兩週市場表現",
            dry_run=True,
            output_dir=str(tmp_path),
        )

    # pipeline 不中斷
    assert result.degraded_mode is False
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "evidence.json").exists()

    # report_view.json 存在且 integrity_status=DEGRADED
    view_path = tmp_path / "report_view.json"
    assert view_path.exists()
    view = json.loads(view_path.read_text(encoding="utf-8"))

    assert view["meta"]["metrics"]["integrity_status"] == "DEGRADED"
    assert view["panel4_report"]["integrity_status"] == "DEGRADED"

    # degraded_reasons 含 L2 相關描述
    reasons = view["panel4_report"]["degraded_reasons"]
    assert any("L2" in r for r in reasons)

    # panel3 skipped_layers 註明 L2_content 被跳過
    skipped = view["panel3_refinement"]["skipped_layers"]
    assert any(s["layer"] == "L2_content" for s in skipped)

    # execution_log 含 l2_content_failed
    log_text = (tmp_path / "execution_log.jsonl").read_text(encoding="utf-8")
    assert "l2_content_failed" in log_text


def test_degraded_mode_timeout_triggers_degraded_in_view(monkeypatch, tmp_path: Path) -> None:
    """degraded_mode（超時）→ integrity_status=DEGRADED + view 載明 collector timeout。"""
    monkeypatch.setenv("DEGRADED_MODE_TRIGGER_SECONDS", "0")

    result = run_pipeline(
        coin="BTC",
        question="分析 BTC 過去兩週市場表現",
        dry_run=True,
        output_dir=str(tmp_path),
    )

    assert result.degraded_mode is True

    view_path = tmp_path / "report_view.json"
    assert view_path.exists()
    view = json.loads(view_path.read_text(encoding="utf-8"))

    assert view["meta"]["metrics"]["integrity_status"] == "DEGRADED"
    assert view["panel4_report"]["integrity_status"] == "DEGRADED"

    # degraded_reasons 提及 timeout
    reasons = view["panel4_report"]["degraded_reasons"]
    assert any("timeout" in r or "collector" in r.lower() for r in reasons)


def test_intact_when_no_layers_skipped(monkeypatch, tmp_path: Path) -> None:
    """正常執行（無跳過）→ integrity_status=INTACT。"""
    monkeypatch.setenv("DEGRADED_MODE_TRIGGER_SECONDS", "720")

    result = run_pipeline(
        coin="BTC",
        question="分析 BTC 過去兩週市場表現",
        dry_run=True,
        output_dir=str(tmp_path),
    )

    assert result.degraded_mode is False

    view_path = tmp_path / "report_view.json"
    assert view_path.exists()
    view = json.loads(view_path.read_text(encoding="utf-8"))

    assert view["meta"]["metrics"]["integrity_status"] == "INTACT"
    assert view["panel4_report"]["integrity_status"] == "INTACT"
    assert view["panel4_report"]["degraded_reasons"] == []
    assert view["panel3_refinement"]["skipped_layers"] == []

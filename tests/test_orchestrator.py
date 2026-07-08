"""驗證 orchestrator 的 degraded mode 與時限控管邏輯（離線，不打真實 API/LLM）。"""

from agent.orchestrator import run_pipeline


def test_degraded_mode_triggers_and_skips_collection(monkeypatch, tmp_path):
    """DEGRADED_MODE_TRIGGER_SECONDS=0 模擬「已超時」，驗證會跳過蒐集但仍完整產出報告。"""
    monkeypatch.setenv("DEGRADED_MODE_TRIGGER_SECONDS", "0")

    result = run_pipeline(
        coin="BTC", question="分析 BTC 過去兩週市場表現", dry_run=True, output_dir=str(tmp_path)
    )

    assert result.degraded_mode is True
    assert len(result.evidences) == 0
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "evidence.json").exists()
    assert (tmp_path / "execution_log.jsonl").exists()

    log_text = (tmp_path / "execution_log.jsonl").read_text(encoding="utf-8")
    assert "degraded_mode" in log_text


def test_normal_mode_does_not_trigger_degraded_when_deadline_is_generous(monkeypatch, tmp_path):
    monkeypatch.setenv("DEGRADED_MODE_TRIGGER_SECONDS", "720")

    result = run_pipeline(
        coin="BTC", question="分析 BTC 過去兩週市場表現", dry_run=True, output_dir=str(tmp_path)
    )

    assert result.degraded_mode is False
    assert len(result.evidences) > 0

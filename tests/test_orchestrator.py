"""驗證 orchestrator 的 degraded mode 與時限控管邏輯（離線，不打真實 API/LLM）。"""

import asyncio

import pytest

from agent.orchestrator import assign_evidence_ids, collect_all, run_pipeline
from agent.schemas import EvidenceDraft, HorizonClass, LogStatus


class _RecordingLogger:
    def __init__(self):
        self.entries = []

    def log(self, **kwargs):
        self.entries.append(kwargs)


def _draft(**overrides):
    base = dict(
        coin="BTC",
        source="x",
        fetched_at="2026-07-25T00:00:00Z",
        content_reference="x",
        related_claim="x",
        source_type="price",
    )
    base.update(overrides)
    return EvidenceDraft(**base)


def test_assign_ids_warns_on_spot_with_long_window():
    """R2-3：horizon_class 是預設 spot 卻帶長觀察窗 → 記一筆 SKIPPED 警示，但證據不被丟棄。"""
    logger = _RecordingLogger()
    drafts = [_draft(window_start="2021-06-01", window_end="2026-05-31")]  # horizon_class 預設 spot

    evidences, quarantined = assign_evidence_ids(drafts, logger=logger)

    assert len(evidences) == 1  # 證據保留，未被過濾
    assert quarantined == []
    warnings = [e for e in logger.entries if e.get("action") == "horizon_annotation_warning"]
    assert len(warnings) == 1
    assert warnings[0]["status"] == LogStatus.SKIPPED


def test_assign_ids_allows_spot_with_intraday_window():
    """§3.2 的 OI 四象限／多空帳戶比是 30 小時趨勢，標 spot＋跨日窗口是合法的，不該警示。"""
    logger = _RecordingLogger()
    assign_evidence_ids([_draft(window_start="2026-07-24", window_end="2026-07-25")], logger=logger)
    assert not [e for e in logger.entries if e.get("action") == "horizon_annotation_warning"]


def test_assign_ids_warns_on_half_annotated_window():
    """只標了窗口一端＝標註不完整，不論分帶都該警示。"""
    logger = _RecordingLogger()
    assign_evidence_ids(
        [_draft(window_end="2026-07-25", horizon_class="medium")], logger=logger
    )
    warnings = [e for e in logger.entries if e.get("action") == "horizon_annotation_warning"]
    assert len(warnings) == 1
    assert "標註不完整" in warnings[0]["detail"]


def test_assign_ids_no_warning_when_horizon_labeled():
    """collector 已正確標非 spot 分帶時不觸發警示。"""
    logger = _RecordingLogger()
    drafts = [_draft(window_start="2021-06-01", window_end="2026-05-31", horizon_class="structural")]

    assign_evidence_ids(drafts, logger=logger)

    assert not [e for e in logger.entries if e.get("action") == "horizon_annotation_warning"]


def test_assign_ids_no_warning_for_plain_spot():
    """純快照（spot 且無觀察窗）是正常情況，不該警示。"""
    logger = _RecordingLogger()
    assign_evidence_ids([_draft()], logger=logger)
    assert not [e for e in logger.entries if e.get("action") == "horizon_annotation_warning"]


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
    assert (tmp_path / "validation_results.json").exists()
    assert (tmp_path / "research_context.json").exists()
    assert (tmp_path / "report.html").exists()
    assert (tmp_path / "evidence.html").exists()
    assert (tmp_path / "execution_log.html").exists()
    assert (tmp_path / "deliverables.html").exists()

    log_text = (tmp_path / "execution_log.jsonl").read_text(encoding="utf-8")
    assert "degraded_mode" in log_text
    assert "research_context_written" in log_text


def test_normal_mode_does_not_trigger_degraded_when_deadline_is_generous(monkeypatch, tmp_path):
    monkeypatch.setenv("DEGRADED_MODE_TRIGGER_SECONDS", "720")

    result = run_pipeline(
        coin="BTC", question="分析 BTC 過去兩週市場表現", dry_run=True, output_dir=str(tmp_path)
    )

    assert result.degraded_mode is False
    assert len(result.evidences) > 0


# --- R8-5：主視野傳進蒐集層 ---------------------------------------------


class _SpyCollector:
    """只記下 run() 收到什麼 kwargs，不實際蒐集。"""

    def __init__(self, source_type="price"):
        self.source_type = source_type
        self.calls: list[tuple[str, dict]] = []

    async def run(self, coin, **kwargs):
        self.calls.append((coin, kwargs))
        return []


def test_collect_all_forwards_primary_horizon_to_every_collector():
    price, macro = _SpyCollector("price"), _SpyCollector("macro")
    asyncio.run(
        collect_all([price, macro], ["BTC", "ETH"], 60.0, primary_horizon=HorizonClass.STRUCTURAL)
    )

    # 每幣一次的 price 兩次、幣種無關的 macro 一次，全都要收到主視野
    assert [c[0] for c in price.calls] == ["BTC", "ETH"]
    assert [c[0] for c in macro.calls] == ["BTC"]
    for _, kwargs in price.calls + macro.calls:
        assert kwargs["primary_horizon"] == HorizonClass.STRUCTURAL


def test_collect_all_passes_none_when_horizon_not_given():
    """未指定時傳 None，各 collector 依此退回既有查詢窗（R6-1）。"""
    price = _SpyCollector("price")
    asyncio.run(collect_all([price], ["BTC"], 60.0))
    assert price.calls[0][1]["primary_horizon"] is None


@pytest.mark.parametrize(
    "question, expected",
    [
        ("分析 BTC 過去一年的市場結構", "structural"),
        ("分析 BTC 過去兩週市場表現", "medium"),
    ],
)
def test_pipeline_logs_primary_horizon_used_for_collection(monkeypatch, tmp_path, question, expected):
    """蒐集階段解出的主視野要寫進 execution_log，讓人能查「當時是用哪個尺度抓資料」。"""
    monkeypatch.setenv("DEGRADED_MODE_TRIGGER_SECONDS", "720")

    run_pipeline(coin="BTC", question=question, dry_run=True, output_dir=str(tmp_path))

    log_text = (tmp_path / "execution_log.jsonl").read_text(encoding="utf-8")
    assert "primary_horizon_for_collection" in log_text
    assert f"primary_horizon={expected}" in log_text

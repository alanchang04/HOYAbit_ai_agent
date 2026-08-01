"""Standalone HTML 評審交付物回歸測試。"""

from agent.report.html_export import export_html_bundle
from agent.schemas import Evidence, LogEntry


def _evidence(**overrides) -> Evidence:
    values = {
        "id": "ev-001",
        "coin": "BTC",
        "source": "Coinbase <script>alert(1)</script>",
        "source_url": "https://example.com/price?coin=btc&currency=usd",
        "fetched_at": "2026-08-01T00:00:00Z",
        "content_reference": "BTC close=12345",
        "related_claim": "價格維持高檔",
        "source_type": "price",
        "window_start": "2026-07-01",
        "window_end": "2026-08-01",
        "horizon_class": "long",
    }
    values.update(overrides)
    return Evidence(**values)


def test_export_html_bundle_preserves_original_contract_and_escapes_content(tmp_path):
    entries = [
        LogEntry(
            ts="2026-08-01T00:01:00Z",
            phase="report",
            action="pipeline_end",
            detail="elapsed_seconds=42.0 <unsafe>",
            status="ok",
            metrics={"count": 1},
        )
    ]

    paths = export_html_bundle(
        out_dir=tmp_path,
        report_markdown="# 結論\n\n市場偏多 <script>alert(1)</script>\n\n[惡意連結](javascript:alert(1))",
        evidences=[_evidence()],
        log_entries=entries,
        metadata={"coin": "BTC", "question": "BTC 市場如何？", "integrity_status": "INTACT"},
    )

    assert {path.name for path in paths} == {
        "report.html",
        "evidence.html",
        "execution_log.html",
        "deliverables.html",
    }
    assert all(path.exists() for path in paths)

    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "<h1" in report and "結論" in report
    assert "<script>alert(1)</script>" not in report
    assert "javascript:alert(1)" not in report

    evidence = (tmp_path / "evidence.html").read_text(encoding="utf-8")
    assert "ev-001" in evidence and "Coinbase" in evidence
    assert "<script>alert(1)</script>" not in evidence
    assert "https://example.com/price?coin=btc&amp;currency=usd" in evidence

    log = (tmp_path / "execution_log.html").read_text(encoding="utf-8")
    assert "pipeline_end" in log and "elapsed_seconds=42.0 &lt;unsafe&gt;" in log

    index = (tmp_path / "deliverables.html").read_text(encoding="utf-8")
    for original in (
        "report.md",
        "evidence.json",
        "execution_log.jsonl",
        "report_view.json",
        "validation_results.json",
        "research_context.json",
        "run_manifest.json",
    ):
        assert original in index
    assert "GitHub repository" in index
    assert "提案簡報" in index
    assert "Live Demo / 影片" in index
    assert "數據與資源" in index


def test_non_http_evidence_url_is_not_clickable(tmp_path):
    export_html_bundle(tmp_path, "# report", [_evidence(source_url="javascript:alert(1)")], [], {})
    evidence = (tmp_path / "evidence.html").read_text(encoding="utf-8")
    assert 'href="javascript:' not in evidence
    assert "javascript:alert(1)" in evidence

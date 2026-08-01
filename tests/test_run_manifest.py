"""Reproducibility manifest contract tests."""

from __future__ import annotations

import json

import httpx
import pytest

from agent.collectors.base import BaseCollector
from agent.config import Settings
from agent.logging_utils import ExecutionLogger
from agent.run_manifest import _api_calls, write_run_manifest
from agent.schemas import LogEntry, LogPhase, LogStatus


class _AuditCollector(BaseCollector):
    name = "audit"

    async def fetch(self, coin: str, **kwargs) -> list:
        return []


def _entry(action: str, metrics: dict, status: LogStatus = LogStatus.OK) -> LogEntry:
    return LogEntry(
        ts="2026-08-02T01:02:03Z",
        phase=LogPhase.COLLECT,
        action=action,
        status=status,
        metrics=metrics,
    )


def test_api_call_pairs_status_latency_and_redacted_params() -> None:
    common = {
        "request_id": "req-1",
        "method": "GET",
        "endpoint": "https://example.com/data",
        "params": {"coin": "BTC", "api_key": "***"},
    }
    calls = _api_calls(
        [
            _entry("price.api_request_started", {**common, "completed": False}),
            _entry(
                "price.api_request_completed",
                {**common, "completed": True, "http_status": 200, "latency_ms": 12.5},
            ),
        ]
    )
    assert calls == [
        {
            "request_id": "req-1",
            "collector": "price",
            "started_at": "2026-08-02T01:02:03Z",
            "completed_at": "2026-08-02T01:02:03Z",
            "method": "GET",
            "endpoint": "https://example.com/data",
            "params": {"coin": "BTC", "api_key": "***"},
            "request_body_sha256": None,
            "http_status": 200,
            "latency_ms": 12.5,
            "result": "ok",
            "error": None,
        }
    ]


@pytest.mark.asyncio
async def test_http_hooks_capture_real_status_latency_and_redact_secrets(tmp_path) -> None:
    logger = ExecutionLogger(tmp_path / "execution_log.jsonl")
    collector = _AuditCollector(logger)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"ok": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        event_hooks=collector.http_event_hooks(),
    ) as client:
        response = await client.get(
            "https://example.com/data", params={"coin": "BTC", "api_key": "supersecret"}
        )

    assert response.status_code == 201
    [call] = _api_calls(logger.read_all())
    assert call["endpoint"] == "https://example.com/data"
    assert call["params"] == {"coin": "BTC", "api_key": "***"}
    assert call["http_status"] == 201
    assert call["latency_ms"] >= 0
    assert call["result"] == "ok"


def test_manifest_contains_identity_datasets_and_artifact_hashes(tmp_path) -> None:
    data_dir = tmp_path / "dataset"
    data_dir.mkdir()
    (data_dir / "BTC.csv").write_text("date,close\n2026-08-01,100\n", encoding="utf-8")
    (tmp_path / "report.md").write_text("# report\n", encoding="utf-8")
    settings = Settings(data_dir=str(data_dir), output_dir=str(tmp_path))

    path, manifest = write_run_manifest(
        tmp_path,
        run_id="run-123",
        coin="BTC",
        coin2=None,
        question="分析 BTC",
        question_type="multi_source",
        primary_horizon="medium",
        dry_run=True,
        settings=settings,
        started_at="2026-08-02T00:00:00Z",
        completed_at="2026-08-02T00:00:01Z",
        elapsed_seconds=1.0,
        log_entries=[],
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == manifest
    assert payload["run_id"] == "run-123"
    assert payload["prompt"]["version"]
    assert payload["prompt"]["sha256"]
    assert payload["datasets"][0]["files"][0]["sha256"]
    report = next(item for item in payload["artifacts"] if item["filename"] == "report.md")
    assert len(report["sha256"]) == 64
    assert "api_key" not in payload["settings"]

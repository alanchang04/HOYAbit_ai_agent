"""Build a reproducibility manifest for one completed pipeline run."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from agent.config import Settings
from agent.reasoning.prompts import PROMPT_VERSION
from agent.schemas import LogEntry

MANIFEST_SCHEMA_VERSION = "1.0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(args: list[str], repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def _software_identity(repo_root: Path) -> dict[str, Any]:
    commit = os.getenv("APP_GIT_SHA") or _git_value(["rev-parse", "HEAD"], repo_root)
    version = os.getenv("APP_VERSION") or _git_value(
        ["describe", "--tags", "--always", "--dirty"], repo_root
    )
    dirty = _git_value(["status", "--porcelain"], repo_root)
    return {
        "git_commit": commit or "unknown",
        "version_tag": version or "unknown",
        "worktree_dirty": bool(dirty),
    }


def _hash_tree(root: Path, repo_root: Path) -> dict[str, Any]:
    if not root.exists():
        return {"root": str(root), "exists": False, "file_count": 0, "sha256": None, "files": []}
    files = sorted(path for path in root.rglob("*") if path.is_file())
    records: list[dict[str, Any]] = []
    aggregate = hashlib.sha256()
    for path in files:
        digest = _sha256(path)
        try:
            relative = path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            relative = str(path.resolve())
        size = path.stat().st_size
        records.append({"path": relative, "bytes": size, "sha256": digest})
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\0")
    return {
        "root": str(root),
        "exists": True,
        "file_count": len(records),
        "sha256": aggregate.hexdigest(),
        "files": records,
    }


def _artifact_hashes(out_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in out_dir.iterdir() if item.is_file()):
        if path.name == "run_manifest.json" or path.name.startswith("."):
            continue
        records.append({"filename": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)})
    return records


def _api_calls(entries: Iterable[LogEntry]) -> list[dict[str, Any]]:
    calls: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for entry in entries:
        metrics = dict(entry.metrics or {})
        request_id = metrics.get("request_id")
        if not request_id or ".api_request_" not in entry.action:
            continue
        if request_id not in calls:
            order.append(request_id)
            calls[request_id] = {
                "request_id": request_id,
                "collector": entry.action.split(".api_request_", 1)[0],
                "started_at": entry.ts,
                "completed_at": None,
                "method": metrics.get("method"),
                "endpoint": metrics.get("endpoint"),
                "params": metrics.get("params", {}),
                "request_body_sha256": metrics.get("request_body_sha256"),
                "http_status": None,
                "latency_ms": None,
                "result": "no_response",
            }
        call = calls[request_id]
        if entry.action.endswith("api_request_completed") or entry.action.endswith("api_request_failed"):
            call.update(
                {
                    "completed_at": entry.ts,
                    "http_status": metrics.get("http_status"),
                    "latency_ms": metrics.get("latency_ms"),
                    "result": (
                        "ok"
                        if entry.status.value == "ok"
                        else "network_error"
                        if entry.action.endswith("api_request_failed")
                        else "http_error"
                    ),
                    "error": metrics.get("network_error"),
                }
            )
    return [calls[request_id] for request_id in order]


def _settings_snapshot(settings: Settings) -> dict[str, Any]:
    # Explicit whitelist: API keys and credentials can never enter the manifest.
    return {
        "llm_backend": settings.llm_backend,
        "aws_region": settings.aws_region,
        "hard_deadline_seconds": settings.hard_deadline_seconds,
        "degraded_mode_trigger_seconds": settings.degraded_mode_trigger_seconds,
        "collector_timeout_seconds": settings.collector_timeout_seconds,
        "llm_read_timeout_seconds": settings.llm_read_timeout_seconds,
        "llm_connect_timeout_seconds": settings.llm_connect_timeout_seconds,
        "data_dir": settings.data_dir,
        "optional_capabilities": {
            "etherscan_configured": bool(settings.etherscan_api_key),
            "bscscan_configured": bool(settings.bscscan_api_key),
            "fred_configured": bool(settings.fred_api_key),
        },
    }


def write_run_manifest(
    out_dir: str | Path,
    *,
    run_id: str,
    coin: str,
    coin2: str | None,
    question: str,
    question_type: str,
    primary_horizon: str,
    dry_run: bool,
    settings: Settings,
    started_at: str,
    completed_at: str,
    elapsed_seconds: float,
    log_entries: list[LogEntry],
) -> tuple[Path, dict[str, Any]]:
    directory = Path(out_dir)
    repo_root = Path(__file__).resolve().parents[1]
    prompt_path = repo_root / "agent" / "reasoning" / "prompts.py"
    model_id = settings.bedrock_model_id if settings.llm_backend == "bedrock" else settings.gemini_model_id
    candidate_roots = [Path(settings.data_dir), repo_root / "raw_data"]
    roots: list[Path] = []
    seen_roots: set[str] = set()
    for root in candidate_roots:
        resolved = root if root.is_absolute() else repo_root / root
        key = str(resolved.resolve()).casefold()
        if key not in seen_roots:
            seen_roots.add(key)
            roots.append(resolved)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "input": {
            "coin": coin,
            "coin2": coin2,
            "question": question,
            "question_type": question_type,
            "primary_horizon": primary_horizon,
            "dry_run": dry_run,
        },
        "software": _software_identity(repo_root),
        "model": {
            "backend": settings.llm_backend,
            "model_id": model_id,
            "region": settings.aws_region if settings.llm_backend == "bedrock" else None,
        },
        "prompt": {
            "version": PROMPT_VERSION,
            "source": "agent/reasoning/prompts.py",
            "sha256": _sha256(prompt_path),
        },
        "settings": _settings_snapshot(settings),
        "datasets": [_hash_tree(root, repo_root) for root in roots],
        "api_calls": _api_calls(log_entries),
        "timing": {
            "started_at": started_at,
            "completed_at": completed_at,
            "elapsed_seconds": round(elapsed_seconds, 3),
        },
        "artifacts": _artifact_hashes(directory),
        "hash_policy": {
            "algorithm": "SHA-256",
            "run_manifest_self_hash": "excluded to avoid recursive self-reference",
        },
    }
    path = directory / "run_manifest.json"
    temporary = directory / ".run_manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path, manifest

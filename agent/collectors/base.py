"""Collector 共用基底：統一 timeout、例外隔離、失敗記錄。"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from agent.logging_utils import ExecutionLogger
from agent.schemas import EvidenceDraft, LogPhase, LogStatus


def _exc_text(exc: BaseException) -> str:
    """例外的可讀描述。**永遠帶型別名**，因為 `str(exc)` 常常是空的。

    2026-08-01 賽場網路壅塞時實測：連線類例外（httpx.ConnectError、ReadTimeout
    等）多半 `str()` 為空字串，於是 log 只留下 `error=`——看得到哪個子來源掛了，
    卻完全看不出為什麼。網路不穩的當下這正是最需要資訊的時候。
    """
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


class BaseCollector(ABC):
    """所有 collector 的基底類別。

    子類別只需實作 `fetch()`，回傳 Evidence 清單；base 負責 timeout、
    例外捕捉與寫入 execution_log，任何單一 collector 失敗都不會讓
    整個 pipeline 中斷。
    """

    name: str = "base"
    source_type: str = "price"
    timeout_seconds: int = 75

    def __init__(self, logger: ExecutionLogger, timeout_seconds: int | None = None, settings=None):
        self.logger = logger
        self.settings = settings
        self._pending_http: dict[str, tuple[float, dict[str, Any]]] = {}
        if timeout_seconds is not None:
            self.timeout_seconds = timeout_seconds

    @abstractmethod
    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        """實際資料蒐集邏輯，回傳 EvidenceDraft 清單。子類別須實作。"""

    def log_subsource(self, sub_name: str, coin: str, status: LogStatus, detail: str) -> None:
        """記錄 collector 內部單一子來源（例如某個備援 API）的成功/失敗，
        不影響整個 collector 的 evidence 回傳（只要仍有其他子來源成功即可）。
        """
        self.logger.log(
            phase=LogPhase.COLLECT,
            action=f"{self.name}.{sub_name}",
            detail=f"coin={coin}, {detail}",
            status=status,
        )
        if status != LogStatus.OK:
            self._finalize_pending_http(detail)

    def _finalize_pending_http(self, error: str) -> None:
        """Close request-start records that failed before an HTTP response existed."""
        for request_id, (started, original) in list(self._pending_http.items()):
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            metrics = {
                **original,
                "request_id": request_id,
                "http_status": None,
                "latency_ms": latency_ms,
                "completed": True,
                "network_error": error,
            }
            self.logger.log(
                phase=LogPhase.COLLECT,
                action=f"{self.name}.api_request_failed",
                detail=f"{metrics.get('method')} {metrics.get('endpoint')} -> no response ({latency_ms} ms): {error}",
                status=LogStatus.ERROR,
                metrics=metrics,
            )
            self._pending_http.pop(request_id, None)

    @staticmethod
    def _redact_params(items: list[tuple[str, str]]) -> dict[str, Any]:
        """Return query parameters without ever persisting credentials."""
        redacted: dict[str, Any] = {}
        secret_markers = ("key", "token", "secret", "password", "authorization")
        for key, value in items:
            safe_value = "***" if any(marker in key.lower() for marker in secret_markers) else value
            if key in redacted:
                current = redacted[key]
                redacted[key] = current + [safe_value] if isinstance(current, list) else [current, safe_value]
            else:
                redacted[key] = safe_value
        return redacted

    def http_event_hooks(self) -> dict[str, list]:
        """Structured HTTP audit hooks used by every real collector client.

        A request-start record is retained even when DNS/socket failures mean no
        response exists.  The response record adds the exact HTTP status and
        measured latency.  Bodies and headers are never logged; only a body hash
        is kept so POST calls remain distinguishable without leaking tokens.
        """

        async def on_request(request: httpx.Request) -> None:
            request_id = uuid.uuid4().hex[:12]
            started = time.perf_counter()
            request.extensions["hoya_audit"] = (request_id, started)
            split = urlsplit(str(request.url))
            endpoint = urlunsplit((split.scheme, split.netloc, split.path, "", ""))
            try:
                body = request.content
                body_hash = hashlib.sha256(body).hexdigest() if body else None
            except Exception:  # streaming request bodies may not be materialized
                body_hash = None
            metrics = {
                "request_id": request_id,
                "method": request.method,
                "endpoint": endpoint,
                "params": self._redact_params(list(request.url.params.multi_items())),
                "request_body_sha256": body_hash,
                "http_status": None,
                "latency_ms": None,
                "completed": False,
            }
            self._pending_http[request_id] = (started, metrics)
            self.logger.log(
                phase=LogPhase.COLLECT,
                action=f"{self.name}.api_request_started",
                detail=f"{request.method} {endpoint}",
                status=LogStatus.OK,
                metrics=metrics,
            )

        async def on_response(response: httpx.Response) -> None:
            request_id, started = response.request.extensions.get(
                "hoya_audit", (uuid.uuid4().hex[:12], time.perf_counter())
            )
            split = urlsplit(str(response.request.url))
            endpoint = urlunsplit((split.scheme, split.netloc, split.path, "", ""))
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            metrics = {
                "request_id": request_id,
                "method": response.request.method,
                "endpoint": endpoint,
                "params": self._redact_params(list(response.request.url.params.multi_items())),
                "http_status": response.status_code,
                "latency_ms": latency_ms,
                "completed": True,
            }
            self._pending_http.pop(request_id, None)
            self.logger.log(
                phase=LogPhase.COLLECT,
                action=f"{self.name}.api_request_completed",
                detail=f"{response.request.method} {endpoint} -> HTTP {response.status_code} ({latency_ms} ms)",
                status=LogStatus.OK if response.status_code < 400 else LogStatus.ERROR,
                metrics=metrics,
            )

        return {"request": [on_request], "response": [on_response]}

    async def run(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        try:
            evidences = await asyncio.wait_for(self.fetch(coin, **kwargs), timeout=self.timeout_seconds)
            self.logger.log(
                phase=LogPhase.COLLECT,
                action=self.name,
                detail=f"coin={coin}, evidence_count={len(evidences)}",
                status=LogStatus.OK,
            )
            return evidences
        except asyncio.TimeoutError:
            self._finalize_pending_http(f"collector timeout after {self.timeout_seconds}s")
            self.logger.log(
                phase=LogPhase.COLLECT,
                action=self.name,
                detail=f"coin={coin}, timeout after {self.timeout_seconds}s",
                status=LogStatus.SKIPPED,
            )
            return []
        except Exception as exc:  # noqa: BLE001 - 任何來源失敗都必須被隔離，不可讓例外往上傳
            self._finalize_pending_http(_exc_text(exc))
            self.logger.log(
                phase=LogPhase.COLLECT,
                action=self.name,
                detail=f"coin={coin}, error={_exc_text(exc)}",
                status=LogStatus.ERROR,
            )
            return []

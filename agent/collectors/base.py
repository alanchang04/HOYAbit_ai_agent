"""Collector 共用基底：統一 timeout、例外隔離、失敗記錄。"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

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
            self.logger.log(
                phase=LogPhase.COLLECT,
                action=self.name,
                detail=f"coin={coin}, timeout after {self.timeout_seconds}s",
                status=LogStatus.SKIPPED,
            )
            return []
        except Exception as exc:  # noqa: BLE001 - 任何來源失敗都必須被隔離，不可讓例外往上傳
            self.logger.log(
                phase=LogPhase.COLLECT,
                action=self.name,
                detail=f"coin={coin}, error={_exc_text(exc)}",
                status=LogStatus.ERROR,
            )
            return []

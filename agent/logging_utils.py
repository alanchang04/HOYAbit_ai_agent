"""execution_log.jsonl 寫入工具。"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from agent.schemas import LogEntry, LogPhase, LogStatus, now_iso


class ExecutionLogger:
    """執行紀錄器，每次 log() 立即 append 一行 JSON，避免中途崩潰遺失紀錄。"""

    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # 每次執行覆寫舊檔，確保單次比賽執行的紀錄乾淨
        self.log_path.write_text("", encoding="utf-8")

    def log(self, phase: LogPhase | str, action: str, detail: str = "", status: LogStatus | str = LogStatus.OK) -> None:
        entry = LogEntry(
            ts=now_iso(),
            phase=LogPhase(phase),
            action=action,
            detail=detail,
            status=LogStatus(status),
        )
        line = entry.model_dump_json()
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def read_all(self) -> list[LogEntry]:
        entries = []
        if not self.log_path.exists():
            return entries
        with self.log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(LogEntry.model_validate_json(line))
        return entries

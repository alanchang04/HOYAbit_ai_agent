"""--dry-run 模式使用的假資料 collector：不打任何真實 API，僅讀取 fixtures。

用於賽前排練與 CI 測試，確保整體 pipeline（蒐集→證據化→推理→報告）
在完全沒有網路/API key/AWS 存取的情況下也能跑通。
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.collectors.base import BaseCollector
from agent.schemas import EvidenceDraft, now_iso

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "dry_run_evidence.json"


class DryRunCollector(BaseCollector):
    """依 source_type 讀取 fixtures/dry_run_evidence.json 中對應區塊。"""

    def __init__(self, source_type: str, logger, timeout_seconds: int | None = None):
        self.source_type = source_type
        self.name = f"dry_run_{source_type}_collector"
        super().__init__(logger, timeout_seconds=timeout_seconds)

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        templates = data.get(self.source_type, [])
        fetched_at = now_iso()
        evidences = []
        for tpl in templates:
            evidences.append(
                EvidenceDraft(
                    source=tpl["source"].format(coin=coin),
                    source_url=tpl.get("source_url"),
                    fetched_at=fetched_at,
                    content_reference=tpl["content_reference"].format(coin=coin),
                    related_claim=tpl["related_claim"].format(coin=coin),
                    source_type=self.source_type,
                )
            )
        return evidences

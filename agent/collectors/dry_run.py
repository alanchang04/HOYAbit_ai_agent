"""--dry-run 模式使用的假資料 collector：不打任何真實 API，僅讀取 fixtures。

用於賽前排練與 CI 測試，確保整體 pipeline（蒐集→證據化→推理→報告）
在完全沒有網路/API key/AWS 存取的情況下也能跑通。
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.collectors.base import BaseCollector
from agent.collectors.horizon import window_back
from agent.schemas import DecayPattern, EvidenceDraft, HorizonClass, Persistence, now_iso

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
            # horizon 標註跟著 fixture 走，讓 dry-run 排練也走到真實的分帶邏輯——
            # 若這裡全吃預設 spot，排練模式就驗不到假矛盾修復與信心計算的分帶行為，
            # 賽前排練會與正式執行產生不同結果（R2-2）。
            horizon = HorizonClass(tpl.get("horizon_class", HorizonClass.SPOT.value))
            window_days = tpl.get("window_days")
            window_start, window_end = window_back(window_days) if window_days else (None, None)
            # 同理（R8-1）：persistence/decay 沒在 fixture 裡指定就用 schema 預設值
            # （medium/slow），不強制每筆 fixture 都要補這兩個欄位。
            persistence = Persistence(tpl["persistence"]) if "persistence" in tpl else Persistence.MEDIUM
            decay = DecayPattern(tpl["decay"]) if "decay" in tpl else DecayPattern.SLOW
            evidences.append(
                EvidenceDraft(
                    coin=coin,
                    source=tpl["source"].format(coin=coin),
                    source_url=tpl.get("source_url"),
                    fetched_at=fetched_at,
                    content_reference=tpl["content_reference"].format(coin=coin),
                    related_claim=tpl["related_claim"].format(coin=coin),
                    source_type=self.source_type,
                    window_start=window_start,
                    window_end=window_end,
                    horizon_class=horizon,
                    persistence=persistence,
                    decay=decay,
                )
            )
        return evidences

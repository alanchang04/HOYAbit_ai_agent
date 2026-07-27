"""Collector 側的觀察窗計算工具（horizon-aware R2-2）。

`horizon_class` 由 collector 依「自己實際傳出去的查詢參數」決定性推導，不交給 LLM
推斷（design.md ADR-2）。這裡只提供把「回看 N 天」換算成 ISO 日期起訖的共用函式，
免得七個 collector 各寫一份日期算法而算出不一致的窗口。

分帶對照表在 `.kiro/specs/horizon-aware-confidence/design.md` §3.2，
權威來源為 `raw_data/_meta/window_policy.md`。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def window_back(days: int, end: date | None = None) -> tuple[str, str]:
    """回看 `days` 天（含當天）的觀察窗 → `(window_start, window_end)` ISO 日期字串。

    `days=30` 即對照表寫的 `today-29 ~ today`：窗口天數是「包含端點」的計數，
    而不是相減的天數差，避免 30 天窗口被算成 31 天。
    """
    end_date = end or utc_today()
    start_date = end_date - timedelta(days=max(days, 1) - 1)
    return start_date.isoformat(), end_date.isoformat()

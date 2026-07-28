"""Collector 側的觀察窗計算工具（horizon-aware R2-2）。

`horizon_class` 由 collector 依「自己實際傳出去的查詢參數」決定性推導，不交給 LLM
推斷（design.md ADR-2）。這裡只提供把「回看 N 天」換算成 ISO 日期起訖的共用函式，
免得七個 collector 各寫一份日期算法而算出不一致的窗口。

分帶對照表在 `.kiro/specs/horizon-aware-confidence/design.md` §3.2，
權威來源為 `raw_data/_meta/window_policy.md`。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from agent.schemas import DEFAULT_PRIMARY_HORIZON, HorizonClass, horizon_for_days


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


# --- 主視野判定（R7-2）---------------------------------------------------
# 從題目文字決定性推導本次分析的主判斷尺度。**規則式，不呼叫 LLM**——
# 可規則化的事不該花一次 LLM 呼叫，而且 LLM 推斷不可複現。
#
# 比對順序由長詞到短詞：「過去一年」必須排在「一年」之前，否則
# 「過去一年」會被較短的樣式先命中而算出錯誤的天數。
QUESTION_HORIZON_KEYWORDS: list[tuple[str, int]] = [
    (r"過去一年|近一年|最近一年|這一年|12\s*個月|一整年|年度", 365),
    (r"過去半年|近半年|最近半年|6\s*個月|半年", 180),
    (r"過去一季|近一季|最近一季|3\s*個月|一季|季度|90\s*天", 90),
    (r"過去(?:這)?一個?月|近一個?月|最近一個?月|30\s*天|一個月", 30),
    (r"過去兩週|近兩週|最近兩週|兩個?星期|兩週|14\s*天", 14),
    (r"過去一週|近一週|最近一週|一個?星期|一週|7\s*天", 7),
    # 只收「明確指當日」的詞。刻意**不收**「現在／目前／當前」——那些是語氣詞
    # 不是時間範圍（「BTC 現在的市場狀態如何」問的是近期盤勢，不是當日 K 棒），
    # 誤判成 spot 會把 short/medium 全部打成結構脈絡、排除在共識投票外，
    # 剛好與本規格要解決的問題相反。
    (r"今天|今日|當日|盤中|日內", 1),
]


def resolve_primary_horizon(question: str) -> tuple[HorizonClass, str]:
    """題目 → `(主視野, 觸發判定的題目片段)`（R7-2）。

    無命中時回 `(DEFAULT_PRIMARY_HORIZON, "")`——題目沒明講時間範圍就沿用
    命題常見的兩週尺度，行為與動態主視野導入前一致。

    回傳的片段供報告揭露「為什麼判成這個尺度」（R7-7），讓讀者能檢查系統
    有沒有誤解題目。
    """
    if not question:
        return DEFAULT_PRIMARY_HORIZON, ""
    for pattern, days in QUESTION_HORIZON_KEYWORDS:
        match = re.search(pattern, question)
        if match:
            return horizon_for_days(days), match.group(0)
    return DEFAULT_PRIMARY_HORIZON, ""

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
# 中文數字 → 阿拉伯數字。表格逐條列舉「詞」而不是解析「數字＋單位」，於是
# 「3個月」收得到、「三個月」收不到；「兩個月」「三週」這種區間表裡根本沒有。
# 先做一次正規化，讓下面的表只需要處理阿拉伯數字，不必為每個區間各寫一份中文版。
_CN_DIGITS = {
    "零": "0", "一": "1", "二": "2", "兩": "2", "三": "3", "四": "4",
    "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
}
# 「十」的處理：十→10、十五→15、二十→20、二十五→25。只到 99，超過的量級
# （百天以上）用「季／半年／年」表達更自然，不值得為它把這裡做成完整的數字剖析器。
_CN_TEN = re.compile(r"([一二兩三四五六七八九])?十([一二兩三四五六七八九])?")


def _normalize_cn_numerals(text: str) -> str:
    """把題目裡的中文數字換成阿拉伯數字，供 horizon 樣式比對用。

    **只用於比對，不改變回報給使用者的片段**——`resolve_primary_horizon()` 回傳的
    `basis` 仍取自題目原文，報告揭露的是使用者真正寫的字。
    """
    def _ten(m: re.Match) -> str:
        tens = _CN_DIGITS.get(m.group(1), "1") if m.group(1) else "1"
        ones = _CN_DIGITS.get(m.group(2), "0") if m.group(2) else "0"
        return f"{int(tens) * 10 + int(ones)}"

    text = _CN_TEN.sub(_ten, text)
    for cn, ar in _CN_DIGITS.items():
        text = text.replace(cn, ar)
    return text


# 可選的時間前綴。只影響**報告顯示的片段**（讓讀者看到「過去兩週」而不是「兩週」），
# 不影響判定結果——有沒有「過去」都是同一個尺度。
_P = r"(?:過去|近|最近|這)?"

# 比對順序由長詞到短詞：「過去一年」必須排在「一年」之前，否則
# 「過去一年」會被較短的樣式先命中而算出錯誤的天數。
#
# 樣式一律用阿拉伯數字寫（題目會先經 `_normalize_cn_numerals()`），
# 並改用「數字＋單位」的通式涵蓋任意區間，而不是逐條列舉。
QUESTION_HORIZON_KEYWORDS: list[tuple[str, int]] = [
    # 明確的量級詞優先——「一整年」「半年」「季度」不帶數字，通式抓不到。
    (_P + r"(?:1\s*整年|年度|1年)", 365),
    (_P + r"半年", 180),
    (_P + r"(?:1\s*季|季度)", 90),
    # 「數字＋單位」通式：任意 N 年／季／月／週／天，換算成天數後由
    # `horizon_for_days()` 落到對應分帶。這取代了原本逐條列舉區間的寫法——
    # 舊表只認它列過的字面，「3個月」有、「三個月」沒有（中文未正規化），
    # 「兩個月」「三週」則是任何寫法都沒有。
    (_P + r"(\d+)\s*年", 365),
    (_P + r"(\d+)\s*季", 90),
    (_P + r"(\d+)\s*個?月", 30),
    (_P + r"(\d+)\s*(?:週|周|個?星期)", 7),
    (_P + r"(\d+)\s*天", 1),
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
    normalized = _normalize_cn_numerals(question)
    for pattern, unit_days in QUESTION_HORIZON_KEYWORDS:
        match = re.search(pattern, normalized)
        if not match:
            continue
        # 通式樣式帶一個數字捕獲組，總天數 = 數字 × 單位天數；
        # 量級詞（半年／季度…）沒有捕獲組，`unit_days` 本身就是天數。
        multiplier = int(match.group(1)) if match.groups() and match.group(1) else 1
        days = unit_days * multiplier
        return horizon_for_days(days), _basis_from_original(question, normalized, match)
    return DEFAULT_PRIMARY_HORIZON, ""


def _basis_from_original(question: str, normalized: str, match: re.Match) -> str:
    """回報給報告的片段要取自**題目原文**，不是正規化後的字串。

    正規化只是為了比對；使用者寫「近三個月」，報告就該顯示「近三個月」而不是
    「近3個月」——那會讓讀者以為系統看到的跟自己寫的不一樣。
    正規化不改變字串長度以外的結構時位移一致；長度有變（如「三十」→「30」）
    時無法安全對位，退回顯示正規化片段，仍比顯示空字串誠實。
    """
    if len(normalized) == len(question):
        return question[match.start() : match.end()]
    return match.group(0)

"""事實層的決定性 grounding validator：純規則比對，不用 LLM 做二次判斷。

Step A 把「摘要」誤解成可以換算單位、代換統計量、甚至補全證據沒提供的指標——
百分位被改寫成年化報酬率、OI 下降被寫成穩定、沒有 RSI 的證據被生出 RSI 描述。
這些錯誤一旦寫進 facts，Step C1/C2/D 完全看不到原始證據內容
（見 `agent/reasoning/prompts.py` 的 `format_evidence_weight_index()`），
只能把 facts 當既定事實全盤接收，沒有機會發現或修正。

這裡驗證的不是「摘要得好不好」，是「這筆 fact 引用的 evidence id 裡，
是否真的出現了它宣稱的數字/指標」——只抓具體、可程式化驗證的錯誤，
驗證器本身刻意不用 LLM：驗證器若也是 LLM，就跟被驗證的東西犯同一種錯誤，
起不到稽核作用。
"""

from __future__ import annotations

import re

from agent.schemas import Evidence

_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*%?")

# 只比對「有辨識度」的數字：個位數/十位數整數（如 SMA7、MA20、RSI14 裡的 7/20/14）
# 出現在來源文本任何地方的機率太高，比對這些只會製造雜訊、抓不到真正的錯誤。
_MIN_ABS_VALUE_FOR_MATCH = 10.0

# 每個 evidence 數字最多容忍的相對誤差，抓四捨五入但不抓被換算/代換的數值。
_RELATIVE_TOLERANCE = 0.005
_ABSOLUTE_TOLERANCE = 0.01


def _extract_numbers(text: str) -> set[tuple[float, bool]]:
    """回傳 (數值, 是否帶百分號) 的集合。

    百分號視為值的一部分——「15.6」與「15.6%」代表不同統計量
    （百分位 vs 百分比/年化率），這正是「百分位被改寫成年化報酬率」
    這類案例會被抓到的關鍵：即使數字沒變，帶不帶 % 號變了就視為不同數值。
    """
    out: set[tuple[float, bool]] = set()
    for m in _NUMBER_RE.finditer(text):
        token = m.group(0)
        has_percent = token.endswith("%")
        cleaned = token.rstrip("%").replace(",", "")
        if cleaned in ("", "-", "+", "."):
            continue
        try:
            value = float(cleaned)
        except ValueError:
            continue
        if abs(value) < _MIN_ABS_VALUE_FOR_MATCH and not has_percent and "." not in cleaned:
            # 個位數整數且無小數、無百分號：多半是指標名稱裡的數字（如 SMA7 的
            # 「7」），跳過以免比對雜訊蓋過真訊號。雙位數以上的（MA20、RSI14）
            # 不跳過——它們通常在來源文本裡也以同樣的指標名稱形式出現，
            # 天然會找到匹配，跳過反而會放過真的被替換掉的數字。
            continue
        out.add((value, has_percent))
    return out


def _numbers_match(claim: tuple[float, bool], source_numbers: set[tuple[float, bool]]) -> bool:
    value, has_percent = claim
    for s_value, s_has_percent in source_numbers:
        if s_has_percent != has_percent:
            continue
        tolerance = max(_ABSOLUTE_TOLERANCE, abs(s_value) * _RELATIVE_TOLERANCE)
        if abs(value - s_value) <= tolerance:
            return True
    return False


# 常見指標詞彙表：summary 提到這些詞、但引用的 evidence 內容裡完全沒有這個詞
# （或這個詞出現在「未提供」之類的否定語境中），代表模型在補全證據沒提供的指標
# ——對應「ev-001 沒有 RSI 卻生成 RSI 敘述」案例。刻意保守、只收窄義技術詞彙，
# 避免「價格」「市場」這類泛用詞造成大量誤判。
_INDICATOR_VOCAB = [
    "RSI", "SMA", "MA20", "MA60", "MA120", "MACD", "布林",
    "OI", "未平倉", "資金費率", "funding rate", "skew", "Skew", "IV",
    "波動率百分位", "多空比", "long/short", "基差", "premium",
    "mempool", "hashrate", "算力",
]

_NEGATION_MARKERS = [
    "未提供", "無法取得", "沒有", "無資料", "n/a", "not available",
    "unavailable", "尚無", "缺少",
]
_NEGATION_WINDOW = 15


def _term_is_available(term: str, source_text: str) -> bool:
    """term 是否在 source_text 裡「確實可用」——存在字串但落在否定語境窗口內
    （例如「未提供 RSI」）仍視為不可用，避免純字串比對誤判成「有提供」。
    """
    lower_text = source_text.lower()
    lower_term = term.lower()
    idx = lower_text.find(lower_term)
    if idx == -1:
        return False
    window_start = max(0, idx - _NEGATION_WINDOW)
    window_end = min(len(lower_text), idx + len(lower_term) + _NEGATION_WINDOW)
    window = lower_text[window_start:window_end]
    return not any(marker in window for marker in _NEGATION_MARKERS)


def _mentions_missing_indicator(summary: str, source_text: str) -> str | None:
    lower_summary = summary.lower()
    for term in _INDICATOR_VOCAB:
        if term.lower() in lower_summary and not _term_is_available(term, source_text):
            return term
    return None


# 方向反轉偵測：小型反義詞對照表，只收最常見、最不易誤判的幾組。目的是抓
# 「來源說下降、fact 卻寫成穩定/上升」這類直接反轉（對應 ev-003 的 OI 案例），
# 不是通用情緒分析——刻意保守，寧可漏抓也不要誤殺正常的方向描述。
_DIRECTION_PAIRS: list[tuple[set[str], set[str]]] = [
    (
        {"下降", "走低", "減少", "下跌", "收縮", "萎縮"},
        {"上升", "走高", "增加", "上漲", "擴張", "穩定", "持平"},
    ),
    ({"偏多", "看多", "看漲"}, {"偏空", "看空", "看跌"}),
]


def _direction_conflict(summary: str, source_text: str) -> str | None:
    for down_words, up_words in _DIRECTION_PAIRS:
        source_down = any(w in source_text for w in down_words)
        source_up = any(w in source_text for w in up_words)
        summary_down = any(w in summary for w in down_words)
        summary_up = any(w in summary for w in up_words)
        if source_down and not source_up and summary_up and not summary_down:
            return "來源顯示下降/走低方向，fact 卻寫成上升/穩定方向"
        if source_up and not source_down and summary_down and not summary_up:
            return "來源顯示上升/穩定方向，fact 卻寫成下降/走低方向"
    return None


def check_fact_grounding(fact: dict, evidences_by_id: dict[str, Evidence]) -> list[str]:
    """回傳這筆 fact 的違規原因列表；空列表代表通過。

    只比對 fact 自己宣稱引用的 evidence_ids——引用範圍以外的證據不算數，
    否則會把「碰巧某處有這個數字」誤判成「有出處」，失去稽核意義。
    """
    summary = fact.get("summary", "")
    if not isinstance(summary, str) or not summary.strip():
        return []

    evidence_ids = fact.get("evidence_ids", []) or []
    source_evidences = [evidences_by_id[eid] for eid in evidence_ids if eid in evidences_by_id]

    if not source_evidences:
        if _extract_numbers(summary):
            return ["fact 未引用任何有效 evidence id，但 summary 含有數值"]
        return []

    source_text = "\n".join(e.content_reference for e in source_evidences)

    violations: list[str] = []

    for claim in _extract_numbers(summary):
        if not _numbers_match(claim, _extract_numbers(source_text)):
            value, has_percent = claim
            token = f"{value:g}%" if has_percent else f"{value:g}"
            violations.append(
                f"數值 {token} 未出現在引用的 evidence（{', '.join(evidence_ids)}）內容中"
            )

    missing_indicator = _mentions_missing_indicator(summary, source_text)
    if missing_indicator:
        violations.append(
            f"提到指標「{missing_indicator}」，但引用的 evidence 內容中未出現此指標（或標示未提供）"
        )

    direction_issue = _direction_conflict(summary, source_text)
    if direction_issue:
        violations.append(direction_issue)

    return violations

"""v1 推理結果的一致性護欄。

LLM 會在事實、辯論與結論多次轉述同一事件；Evidence ID 存在性檢查只能
防止捏造引用，不能阻止同一日期被換算成互相衝突的「距今 N 個月」。本模組
在報告組裝前，使用 Evidence 內可確定重算的事件日期校正這類跨段落矛盾。

刻意只處理能由結構化日期確定計算的內容，不嘗試用規則重寫市場方向或
LLM 推論。v2 若改採 Feature／Knowledge 結構，應在新結構層做同等驗證，
不應直接依賴本模組的文字正規化。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from agent.reasoning.pipeline import ReasoningResult
from agent.schemas import Evidence


_HALVING_EVIDENCE_RE = re.compile(
    r"上次\s*(?P<date>\d{4}-\d{2}-\d{2}).{0,40}?第\s*(?P<ordinal>\d+)\s*次減半"
)
_HALVING_AGE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"距\s*第\s*\d+\s*次減半(?:後|已)?\s*約?\s*"
            r"(?:\d+\s*年\s*(?:又\s*)?)?\d+\s*個月"
        ),
        "distance",
    ),
    (
        re.compile(
            r"第\s*\d+\s*次減半後\s*約?\s*"
            r"(?:\d+\s*年\s*(?:又\s*)?)?\d+\s*個月"
        ),
        "after_ordinal",
    ),
    (
        re.compile(
            r"減半後\s*約?\s*(?:\d+\s*年\s*(?:又\s*)?)?\d+\s*個月"
        ),
        "after",
    ),
)


@dataclass(frozen=True)
class ConsistencyCorrection:
    event: str
    before: str
    after: str
    evidence_id: str


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def _elapsed_months(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def _format_months(months: int) -> str:
    years, remainder = divmod(months, 12)
    if years and remainder:
        return f"{years}年{remainder}個月"
    if years:
        return f"{years}年"
    return f"{months}個月"


def _latest_evidence_date(evidences: list[Evidence]) -> date | None:
    dates: list[date] = []
    for evidence in evidences:
        for value in (evidence.window_end, evidence.fetched_at):
            parsed = _parse_date(value)
            if parsed is not None:
                dates.append(parsed)
    return max(dates) if dates else None


def _halving_anchor(evidences: list[Evidence]) -> tuple[date, int, str] | None:
    for evidence in evidences:
        match = _HALVING_EVIDENCE_RE.search(evidence.content_reference)
        if match:
            return date.fromisoformat(match.group("date")), int(match.group("ordinal")), evidence.id
    return None


def _normalize_text(
    text: str,
    *,
    ordinal: int,
    elapsed: str,
    evidence_id: str,
    corrections: list[ConsistencyCorrection],
) -> str:
    replacements = {
        "distance": f"距第{ordinal}次減半約{elapsed}",
        "after_ordinal": f"第{ordinal}次減半後約{elapsed}",
        "after": f"減半後約{elapsed}",
    }
    normalized = text
    for pattern, style in _HALVING_AGE_PATTERNS:
        replacement = replacements[style]

        def replace(match: re.Match[str]) -> str:
            before = match.group(0)
            if before.replace(" ", "") != replacement:
                corrections.append(
                    ConsistencyCorrection(
                        event="halving_age",
                        before=before,
                        after=replacement,
                        evidence_id=evidence_id,
                    )
                )
            return replacement

        normalized = pattern.sub(replace, normalized)
    return normalized


def _walk(value: Any, normalizer) -> Any:
    if isinstance(value, str):
        return normalizer(value)
    if isinstance(value, list):
        return [_walk(item, normalizer) for item in value]
    if isinstance(value, tuple):
        return tuple(_walk(item, normalizer) for item in value)
    if isinstance(value, dict):
        return {key: _walk(item, normalizer) for key, item in value.items()}
    return value


def enforce_reasoning_consistency(
    result: ReasoningResult,
    evidences: list[Evidence],
) -> list[ConsistencyCorrection]:
    """依 Evidence 校正可確定重算的跨段落事件時間，直接更新 result。"""
    anchor = _halving_anchor(evidences)
    as_of = _latest_evidence_date(evidences)
    if anchor is None or as_of is None:
        return []

    event_date, ordinal, evidence_id = anchor
    elapsed = _format_months(_elapsed_months(event_date, as_of))
    corrections: list[ConsistencyCorrection] = []

    def normalize(text: str) -> str:
        return _normalize_text(
            text,
            ordinal=ordinal,
            elapsed=elapsed,
            evidence_id=evidence_id,
            corrections=corrections,
        )

    result.facts = _walk(result.facts, normalize)
    result.cross_validation = _walk(result.cross_validation, normalize)
    result.inference = _walk(result.inference, normalize)
    result.conclusion = _walk(result.conclusion, normalize)
    result.follow_up_watchpoints = _walk(result.follow_up_watchpoints, normalize)
    result.debate = _walk(result.debate, normalize)
    return corrections


def normalize_nested_consistency(
    value: Any,
    evidences: list[Evidence],
) -> tuple[Any, list[ConsistencyCorrection]]:
    """替既有 v1 report_view.json 套用同一護欄，不修改歷史交付檔本身。

    這讓升級前已保存的 Demo 在新版 Web UI 顯示時也不會繼續呈現已知矛盾；
    新產出的 report.md／report_view.json 則已在 orchestrator 階段直接校正。
    """
    anchor = _halving_anchor(evidences)
    as_of = _latest_evidence_date(evidences)
    if anchor is None or as_of is None:
        return value, []

    event_date, ordinal, evidence_id = anchor
    elapsed = _format_months(_elapsed_months(event_date, as_of))
    corrections: list[ConsistencyCorrection] = []

    def normalize(text: str) -> str:
        return _normalize_text(
            text,
            ordinal=ordinal,
            elapsed=elapsed,
            evidence_id=evidence_id,
            corrections=corrections,
        )

    return _walk(value, normalize), corrections

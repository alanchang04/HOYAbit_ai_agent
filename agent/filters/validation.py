"""Versioned, per-record Evidence Validation Certificate.

The certificate intentionally stays separate from ``evidence.json`` so the v1
Evidence schema remains backwards compatible.  Unlike the original v1.2
summary, every check now carries an explicit state and reason; pre-schema
quarantine records and fact-grounding outcomes are part of the same audit.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

from agent.filters.source_weights import WeightBreakdown
from agent.reasoning.grounding import check_fact_grounding
from agent.schemas import Evidence, FilterDecision, HORIZON_ORDER, HorizonClass

CheckStatus = Literal["pass", "warn", "fail", "not_applicable"]
CertificateStatus = Literal["VALIDATED", "DEGRADED", "QUARANTINED", "INVALID"]

_NUMERIC_SOURCE_TYPES = {"price", "onchain", "macro", "derivatives"}
_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
_HORIZON_STALE_DAYS = {
    HorizonClass.SPOT.value: 2,
    HorizonClass.SHORT.value: 14,
    HorizonClass.MEDIUM.value: 45,
    HorizonClass.LONG.value: 120,
    HorizonClass.STRUCTURAL.value: 400,
}


@dataclass
class ValidationCheck:
    status: CheckStatus
    reason: str
    score: float | None = None
    fact_ids: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceValidationResult:
    evidence_id: str
    status: CertificateStatus
    checks: dict[str, ValidationCheck]
    reasons: list[str] = field(default_factory=list)
    source: str = ""
    source_type: str = ""
    coin: str = ""
    content_reference: str = ""
    pre_schema_quarantine: bool = False

    # Compatibility properties for the v1.2 research adapter and older tests.
    @property
    def source_reliability(self) -> float:
        return float(self.checks["source_reliability"].score or 0.0)

    @property
    def source_grade(self) -> str:
        return str(self.checks["source_reliability"].details.get("grade", ""))

    @property
    def timestamp_valid(self) -> bool:
        return self.checks["timestamp"].status == "pass"

    @property
    def data_integrity_ok(self) -> bool:
        return self.checks["data_integrity"].status == "pass"

    @property
    def injection_flag(self) -> str | None:
        return self.checks["prompt_injection"].details.get("flag")

    @property
    def dedup_verdict(self) -> str | None:
        return self.checks["deduplication"].details.get("verdict")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value or ""))


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp_check(
    evidence: Evidence,
    *,
    now: datetime,
    primary_horizon: HorizonClass | None,
) -> ValidationCheck:
    try:
        fetched = _aware_datetime(evidence.fetched_at)
    except (TypeError, ValueError) as exc:
        return ValidationCheck("fail", f"fetched_at 無法解析：{exc}")

    age_hours = (now - fetched).total_seconds() / 3600
    details: dict[str, Any] = {
        "fetched_at": evidence.fetched_at,
        "age_hours": round(age_hours, 2),
        "window_start": evidence.window_start,
        "window_end": evidence.window_end,
        "evidence_horizon": _enum_value(evidence.horizon_class),
        "question_horizon": _enum_value(primary_horizon),
    }
    if age_hours < -0.083:  # tolerate five minutes of clock skew
        return ValidationCheck("fail", "取得時間位於未來，超出 5 分鐘容許值", details=details)

    warnings: list[str] = []
    if primary_horizon is not None:
        evidence_horizon = evidence.horizon_class
        gap = abs(HORIZON_ORDER.index(evidence_horizon) - HORIZON_ORDER.index(primary_horizon))
        details["horizon_gap"] = gap
        details["horizon_alignment"] = "primary" if gap == 0 else "supplemental"
        if gap >= 3:
            warnings.append(
                f"Evidence horizon {evidence_horizon.value} is {gap} levels from "
                f"question horizon {primary_horizon.value}; use as background only"
            )
    if age_hours > 48:
        warnings.append(f"資料於 {age_hours / 24:.1f} 天前取得，並非本次即時抓取")

    if evidence.window_start and evidence.window_end:
        try:
            window_start = _aware_datetime(evidence.window_start)
            window_end = _aware_datetime(evidence.window_end)
        except (TypeError, ValueError) as exc:
            return ValidationCheck("fail", f"觀察窗口無法解析：{exc}", details=details)
        if window_start > window_end:
            return ValidationCheck("fail", "window_start 晚於 window_end", details=details)
        if window_end > now.replace(hour=23, minute=59, second=59):
            return ValidationCheck("fail", "window_end 位於未來", details=details)
        horizon = _enum_value(evidence.horizon_class)
        max_lag = _HORIZON_STALE_DAYS.get(horizon)
        lag_days = (now - window_end).total_seconds() / 86400
        details["window_end_age_days"] = round(lag_days, 2)
        if max_lag is not None and lag_days > max_lag:
            warnings.append(
                f"{horizon} 證據的觀察窗口已落後 {lag_days:.1f} 天（建議上限 {max_lag} 天）"
            )
    elif evidence.window_start or evidence.window_end:
        warnings.append("觀察窗口只有單邊界，無法完整驗證涵蓋範圍")

    if warnings:
        return ValidationCheck("warn", "；".join(warnings), details=details)
    horizon_note = (
        f"；題目主尺度為 {_enum_value(primary_horizon)}"
        if primary_horizon is not None
        else ""
    )
    return ValidationCheck(
        "pass",
        f"時間格式、未來值與觀察窗口檢查通過（資料取得距今 {max(age_hours, 0):.1f} 小時{horizon_note}）",
        details=details,
    )


def _data_integrity_check(evidence: Evidence) -> ValidationCheck:
    failures: list[str] = []
    warnings: list[str] = []
    if not evidence.coin.strip():
        failures.append("coin 為空")
    if not evidence.source.strip():
        failures.append("source 為空")
    content = evidence.content_reference.strip()
    if not content:
        failures.append("content_reference 為空")
    elif len(content) < 8:
        warnings.append("content_reference 過短，資訊量有限")

    if not math.isfinite(float(evidence.source_weight)) or not 0 <= evidence.source_weight <= 1:
        failures.append("source_weight 不在 0~1 的有限數值範圍")

    for label, value in (("source_url", evidence.source_url), ("reference_url", evidence.reference_url)):
        if value and urlparse(value).scheme not in {"http", "https"}:
            failures.append(f"{label} 不是 http(s) URL")

    source_type = _enum_value(evidence.source_type)
    is_fixture = "dry-run" in f"{evidence.source} {content}".lower()
    missing_marker = any(marker in content.lower() for marker in ("未提供", "無法取得", "n/a", "unavailable"))
    non_finite_marker = bool(
        re.search(r"(?i)(?:^|[^a-z])(nan|[+-]?inf(?:inity)?)(?:$|[^a-z])", content)
    )
    if (
        source_type in _NUMERIC_SOURCE_TYPES
        and content
        and not is_fixture
        and not missing_marker
        and not _NUMBER_RE.search(content)
    ):
        warnings.append(f"{source_type} 類證據未包含可核對的數值")
    if source_type in _NUMERIC_SOURCE_TYPES and non_finite_marker:
        failures.append(f"{source_type} 類證據含 NaN/Infinity 非有限數值")
    if source_type in {"news", "social"} and not is_fixture:
        if len(content) < 30:
            warnings.append(f"{source_type} 敘事證據過短，缺少足夠可核對上下文")
        if not (evidence.reference_url or evidence.source_url):
            warnings.append(f"{source_type} 敘事證據缺少可追溯 URL")
    if source_type in _NUMERIC_SOURCE_TYPES and not is_fixture:
        if evidence.horizon_class != HorizonClass.SPOT and not (
            evidence.window_start and evidence.window_end
        ):
            warnings.append(f"{source_type} 非即時證據缺少完整觀察窗起訖")

    details = {
        "source_type": source_type,
        "policy": "numeric" if source_type in _NUMERIC_SOURCE_TYPES else "narrative",
        "content_length": len(content),
        "has_numeric_value": bool(_NUMBER_RE.search(content)),
        "has_traceable_url": bool(evidence.reference_url or evidence.source_url),
        "window_complete": bool(evidence.window_start and evidence.window_end),
        "is_dry_run_fixture": is_fixture,
    }
    if failures:
        return ValidationCheck("fail", "；".join(failures), details=details)
    if warnings:
        return ValidationCheck("warn", "；".join(warnings), details=details)
    return ValidationCheck("pass", "必要欄位、URL、權重範圍與類型內容檢查通過", details=details)


def _grounding_index(
    facts: list[dict] | None,
    evidences: list[Evidence],
    grounding_audit: list[dict] | None,
) -> dict[str, ValidationCheck]:
    evidence_by_id = {item.id: item for item in evidences}
    fact_ids_by_evidence: dict[str, list[str]] = {}
    failures_by_evidence: dict[str, list[str]] = {}

    for index, fact in enumerate(facts or [], 1):
        fact_id = f"fact-{index:03d}"
        reasons = check_fact_grounding(fact, evidence_by_id)
        for evidence_id in fact.get("evidence_ids", []) or []:
            if evidence_id not in evidence_by_id:
                continue
            fact_ids_by_evidence.setdefault(evidence_id, []).append(fact_id)
            if reasons:
                failures_by_evidence.setdefault(evidence_id, []).extend(reasons)

    for audit in grounding_audit or []:
        if audit.get("outcome") not in {"dropped", "failed"}:
            continue
        for evidence_id in audit.get("evidence_ids", []) or []:
            if evidence_id in evidence_by_id:
                failures_by_evidence.setdefault(evidence_id, []).extend(audit.get("reasons", []))

    output: dict[str, ValidationCheck] = {}
    for evidence_id in evidence_by_id:
        fact_ids = sorted(set(fact_ids_by_evidence.get(evidence_id, [])))
        failures = list(dict.fromkeys(failures_by_evidence.get(evidence_id, [])))
        if failures:
            output[evidence_id] = ValidationCheck(
                "warn",
                "曾有未通過 grounding 的 Fact，已阻擋進入下游：" + "；".join(failures),
                fact_ids=fact_ids,
                details={"blocked": True},
            )
        elif fact_ids:
            output[evidence_id] = ValidationCheck(
                "pass",
                f"引用此 Evidence 的 {len(fact_ids)} 筆 Fact 均通過逐值 grounding",
                fact_ids=fact_ids,
            )
        else:
            output[evidence_id] = ValidationCheck(
                "not_applicable",
                "此 Evidence 未被 Step A Fact 引用，不宣稱已完成 Fact grounding",
            )
    return output


def _final_status(checks: dict[str, ValidationCheck]) -> CertificateStatus:
    injection = checks["prompt_injection"].details.get("flag")
    if injection == "high":
        return "QUARANTINED"
    if checks["timestamp"].status == "fail" or checks["data_integrity"].status == "fail":
        return "INVALID"
    if any(check.status in {"warn", "fail"} for check in checks.values()):
        return "DEGRADED"
    return "VALIDATED"


def build_validation_results(
    evidences: list[Evidence],
    breakdowns: dict[str, WeightBreakdown],
    filter_decisions: list[FilterDecision],
    *,
    facts: list[dict] | None = None,
    grounding_audit: list[dict] | None = None,
    quarantined_drafts: list[dict] | None = None,
    primary_horizon: HorizonClass | None = None,
    now: datetime | None = None,
) -> list[EvidenceValidationResult]:
    """Build a complete certificate for valid and pre-schema-invalid records."""

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    decisions_by_id: dict[str, list[FilterDecision]] = {}
    for decision in filter_decisions:
        decisions_by_id.setdefault(decision.evidence_id, []).append(decision)
    grounding = _grounding_index(facts, evidences, grounding_audit)

    results: list[EvidenceValidationResult] = []
    for evidence in evidences:
        breakdown = breakdowns.get(evidence.id)
        reliability = breakdown.final_weight if breakdown else evidence.source_weight
        grade = breakdown.level_name if breakdown else ""
        reliability_status: CheckStatus = "pass" if reliability >= 0.35 else "warn"
        reliability_reason = (
            f"來源權重 {reliability:.2f}（{grade or '未分級'}）"
            if reliability_status == "pass"
            else f"來源權重僅 {reliability:.2f}，低於 0.35 低信任門檻"
        )

        dedup_decisions = [
            item for item in decisions_by_id.get(evidence.id, []) if item.check_code == "DEDUP"
        ]
        dedup_verdict = dedup_decisions[-1].verdict.value if dedup_decisions else None
        duplicate = bool(evidence.duplicate_of) or dedup_verdict == "removed"
        dedup_check = ValidationCheck(
            "warn" if duplicate else "pass",
            (
                f"重複證據，canonical={evidence.duplicate_of or '見 FilterDecision'}；保留供稽核但不進事實層"
                if duplicate
                else "未被判定為重複剔除"
            ),
            details={"verdict": dedup_verdict, "duplicate_of": evidence.duplicate_of},
        )

        injection_flag = evidence.injection_flag
        injection_status: CheckStatus = (
            "fail" if injection_flag == "high" else "warn" if injection_flag else "pass"
        )
        injection_reason = (
            f"偵測到 {injection_flag} 等級 Prompt Injection：{evidence.injection_reason}"
            if injection_flag
            else "未偵測到 Prompt Injection 特徵"
        )
        checks = {
            "source_reliability": ValidationCheck(
                reliability_status,
                reliability_reason,
                score=round(float(reliability), 4),
                details={"grade": grade, "weight_reason": evidence.weight_reason},
            ),
            "timestamp": _timestamp_check(
                evidence, now=now, primary_horizon=primary_horizon
            ),
            "data_integrity": _data_integrity_check(evidence),
            "deduplication": dedup_check,
            "prompt_injection": ValidationCheck(
                injection_status,
                injection_reason,
                details={"flag": injection_flag},
            ),
            "fact_grounding": grounding[evidence.id],
        }
        status = _final_status(checks)
        reasons = [
            f"{name}: {check.reason}"
            for name, check in checks.items()
            if check.status in {"warn", "fail"}
        ]
        results.append(
            EvidenceValidationResult(
                evidence_id=evidence.id,
                status=status,
                checks=checks,
                reasons=reasons,
                source=evidence.source,
                source_type=_enum_value(evidence.source_type),
                coin=evidence.coin,
                content_reference=evidence.content_reference,
            )
        )

    for index, draft in enumerate(quarantined_drafts or [], 1):
        record_index = draft.get("index", index)
        reason = str(draft.get("reason", "Evidence schema construction failed"))
        na = ValidationCheck("not_applicable", "Schema 建構前已終止，無法執行此檢查")
        checks = {
            "source_reliability": na,
            "timestamp": na,
            "data_integrity": ValidationCheck("fail", reason),
            "deduplication": na,
            "prompt_injection": na,
            "fact_grounding": na,
            "schema": ValidationCheck("fail", reason),
        }
        results.append(
            EvidenceValidationResult(
                evidence_id=f"quarantine:draft:{int(record_index):03d}" if str(record_index).isdigit() else f"quarantine:draft:{record_index}",
                status="INVALID",
                checks=checks,
                reasons=[f"schema: {reason}"],
                source=str(draft.get("source", "")),
                source_type=str(draft.get("source_type", "")),
                coin=str(draft.get("coin", "")),
                content_reference=str(draft.get("content_reference", "")),
                pre_schema_quarantine=True,
            )
        )
    return results


def build_validation_certificate(results: list[EvidenceValidationResult]) -> dict[str, Any]:
    counts = {status: 0 for status in ("VALIDATED", "DEGRADED", "QUARANTINED", "INVALID")}
    for result in results:
        counts[result.status] += 1
    return {
        "schema_version": "2.0",
        "certificate_type": "Evidence Validation Certificate",
        "summary": {"total": len(results), **{key.lower(): value for key, value in counts.items()}},
        "results": [result.to_dict() for result in results],
    }

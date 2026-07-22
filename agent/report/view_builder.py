"""view_builder：組裝 report_view.json，純函式、無網路、失敗隔離。

於 pipeline 結束後由 execution_log＋evidence＋ReasoningResult 組裝
report_view.json（schema_version 1.0）。組裝失敗只記 log 不影響三個命題交付檔。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agent.reasoning.pipeline import ReasoningResult
from agent.schemas import (
    Evidence,
    FilterDecision,
    LogEntry,
    LogStatus,
    PipelineLayer,
    RunMetrics,
    SourceType,
    now_iso,
)

logger = logging.getLogger(__name__)


def build_report_view(
    out_dir: Path,
    evidences: list[Evidence],
    reasoning_result: ReasoningResult,
    run_metrics: RunMetrics,
    filter_decisions: list[FilterDecision],
    baseline_result: dict | None = None,
    coin: str = "",
    coin2: str | None = None,
    question: str = "",
) -> dict | None:
    """組裝 report_view.json 並寫入 out_dir。失敗回傳 None。"""
    try:
        # Read execution log
        log_path = out_dir / "execution_log.jsonl"
        log_entries: list[LogEntry] = []
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        log_entries.append(LogEntry.model_validate_json(line.strip()))

        # Detect skipped layers from log (ERROR status with layer tag)
        skipped_layers: list[dict] = []
        for entry in log_entries:
            if entry.status == LogStatus.ERROR and entry.layer is not None:
                layer_key = entry.layer.value if hasattr(entry.layer, "value") else str(entry.layer)
                skipped_layers.append({
                    "layer": layer_key,
                    "reason": entry.detail or entry.action,
                })

        # Build fingerprint mapping: F1..Fn (by evidence order)
        fingerprint_map: dict[str, str] = {}
        for i, ev in enumerate(evidences, 1):
            fingerprint_map[ev.id] = f"F{i}"

        # Panel 1: Raw feed
        panel1 = _build_panel1(evidences, fingerprint_map, filter_decisions)

        # Panel 2: Baseline
        panel2 = _build_panel2(baseline_result)

        # Panel 3: Refinement
        panel3 = _build_panel3(
            evidences, reasoning_result, run_metrics, filter_decisions, log_entries, fingerprint_map,
            skipped_layers,
        )

        # Panel 4: Report
        panel4 = _build_panel4(reasoning_result, run_metrics, fingerprint_map)

        view = {
            "schema_version": "1.0",
            "meta": {
                "coin": coin,
                "coin2": coin2,
                "question": question,
                "question_type": reasoning_result.question_type,
                "generated_at": now_iso(),
                "metrics": run_metrics.model_dump(),
            },
            "panel1_raw_feed": panel1,
            "panel2_naive_baseline": panel2,
            "panel3_refinement": panel3,
            "panel4_report": panel4,
        }

        view_path = out_dir / "report_view.json"
        view_path.write_text(
            json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return view
    except Exception as exc:
        logger.warning("view_builder 組裝失敗: %s", exc)
        return None


# --- Helper functions ---


def _build_panel1(
    evidences: list[Evidence],
    fingerprint_map: dict[str, str],
    filter_decisions: list[FilterDecision],
) -> dict:
    """panel1_raw_feed：原始證據流。"""
    # Group filter decisions by evidence_id
    decisions_by_ev: dict[str, list[dict]] = {}
    for fd in filter_decisions:
        decisions_by_ev.setdefault(fd.evidence_id, []).append(fd.model_dump())

    items: list[dict] = []
    for ev in evidences:
        items.append(
            {
                "fingerprint": fingerprint_map.get(ev.id, ""),
                "evidence_id": ev.id,
                "source": ev.source,
                "source_type": ev.source_type.value,
                "source_weight": ev.source_weight,
                "weight_reason": ev.weight_reason,
                "content_reference": ev.content_reference,
                "coin": ev.coin,
                "filter_decisions": decisions_by_ev.get(ev.id, []),
            }
        )

    return {"count": len(items), "items": items}


def _build_panel2(baseline_result: dict | None) -> dict:
    """panel2_naive_baseline：未過濾基準對照。"""
    # 固定四步驟文案
    steps = [
        {"step": 1, "label": "收集", "desc": "全量未過濾證據直接輸入"},
        {"step": 2, "label": "無信源加權", "desc": "未依來源可靠度調整權重"},
        {"step": 3, "label": "無雜訊過濾", "desc": "未做 PR 話術/模板相似度過濾"},
        {"step": 4, "label": "直接結論", "desc": "一次 LLM 呼叫產出分析結論"},
    ]

    if baseline_result is None:
        return {
            "enabled": False,
            "steps": steps,
            "naive_output": None,
        }

    # baseline_result 可能含 analysis/caveat/error
    output: dict = {}
    if "error" in baseline_result:
        return {
            "enabled": True,
            "steps": steps,
            "naive_output": None,
            "error": baseline_result["error"],
        }

    output = {
        "analysis": baseline_result.get("analysis", ""),
        "caveat": baseline_result.get(
            "caveat",
            "此為未過濾對照組輸出：未做信源加權/雜訊過濾/證據回溯",
        ),
    }
    return {
        "enabled": True,
        "steps": steps,
        "naive_output": output,
    }


def _build_panel3(
    evidences: list[Evidence],
    reasoning_result: ReasoningResult,
    run_metrics: RunMetrics,
    filter_decisions: list[FilterDecision],
    log_entries: list[LogEntry],
    fingerprint_map: dict[str, str],
    skipped_layers: list[dict] | None = None,
) -> dict:
    """panel3_refinement：信任提煉流水線 L1-L5。"""
    # L1 source summary
    auth_count = sum(1 for e in evidences if e.source_weight >= 0.7)
    low_count = sum(1 for e in evidences if e.source_weight < 0.35)
    normal_count = len(evidences) - auth_count - low_count

    l1_layer = {
        "layer": "L1_source",
        "summary": {
            "total": len(evidences),
            "authoritative": auth_count,
            "normal": normal_count,
            "low": low_count,
        },
        "note": f"共 {len(evidences)} 筆證據，{auth_count} 筆權威源（≥0.7），{low_count} 筆低信度（<0.35）",
    }

    # L2 content checks
    pr_hits = [fd for fd in filter_decisions if fd.check_code == "PR"]
    dedup_removed = [fd for fd in filter_decisions if fd.check_code == "DEDUP"]
    f10_pairs = [fd for fd in filter_decisions if fd.check_code == "F10"]

    def _fd_items(fds: list[FilterDecision]) -> list[dict]:
        return [
            {
                "fingerprint": fingerprint_map.get(fd.evidence_id, ""),
                "evidence_id": fd.evidence_id,
                "reason": fd.reason,
            }
            for fd in fds
        ]

    # DEDUP 群組統計與 F9 情緒分布：從 execution log 對帳（缺項時誠實顯示空/未啟用）
    dedup_summary = _find_log_metrics(log_entries, "l2_dedup_summary")
    f9_metrics = _find_log_metrics(log_entries, "l2_f9_sentiment")

    l2_layer = {
        "layer": "L2_content",
        "checks": [
            {"code": "PR", "hits": _fd_items(pr_hits)},
            {
                "code": "DEDUP",
                "removed": _fd_items(dedup_removed),
                "stats": dedup_summary.get("groups", []),
            },
            # F10 模板相似度已由 Phase 2 去重（DEDUP）取代，保留欄位相容
            {"code": "F10", "pairs": _fd_items(f10_pairs)},
            (
                {"code": "F9", **{k: v for k, v in f9_metrics.items()}}
                if f9_metrics.get("enabled")
                else {"code": "F9", "enabled": False}
            ),
        ],
    }

    # L3 fact extraction metrics (from log or reasoning)
    l3_metrics = _find_log_metrics(log_entries, "l3_fact_extraction")
    l3_input = l3_metrics.get("input", len(evidences))
    l3_kept = l3_metrics.get("kept", len(evidences))
    l3_removed = l3_metrics.get("removed", 0)
    l3_removal_rate = l3_metrics.get("removal_rate", run_metrics.noise_removal_rate)

    l3_layer = {
        "layer": "L3_fact",
        "input": l3_input,
        "kept": l3_kept,
        "removed": l3_removed,
        "removal_rate": l3_removal_rate,
        "removed_items": _compute_removed_items(
            evidences, reasoning_result, filter_decisions, fingerprint_map
        ),
    }

    # L4 cross validation
    l4_metrics = _find_log_metrics(log_entries, "l4_cross_validation")
    consistent_signals = reasoning_result.cross_validation.get("consistent_signals", [])
    contradictions = reasoning_result.cross_validation.get("contradictions", [])

    l4_layer = {
        "layer": "L4_cross",
        "consistent": consistent_signals,
        "contradictions": contradictions,
    }

    # L5 conclusion / confidence breakdown
    l5_metrics = _find_log_metrics(log_entries, "l5_confidence_score")
    debate = reasoning_result.debate or {}

    l5_layer = {
        "layer": "L5_conclusion",
        "debate": {
            "bull": debate.get("bull_argument", ""),
            "bear_critique": debate.get("bear_critique", ""),
            "bear": debate.get("bear_argument", ""),
        },
        "confidence_breakdown": {
            "base": l5_metrics.get("base", 35),
            "auth_bonus": l5_metrics.get("auth_bonus", 0),
            "contradiction_penalty": l5_metrics.get("contradiction_penalty", 0),
            "gap_penalty": l5_metrics.get("gap_penalty", 0),
            "final": l5_metrics.get("final", reasoning_result.confidence_score),
        },
    }

    layers = [l1_layer, l2_layer, l3_layer, l4_layer, l5_layer]

    # Annotate skipped layers
    if skipped_layers:
        skipped_layer_names = {s["layer"] for s in skipped_layers}
        for layer_dict in layers:
            if layer_dict["layer"] in skipped_layer_names:
                reasons = [s["reason"] for s in skipped_layers if s["layer"] == layer_dict["layer"]]
                layer_dict["skipped"] = True
                layer_dict["skipped_reason"] = "; ".join(reasons)

    # log_events_by_layer
    log_events_by_layer = _group_log_by_layer(log_entries)

    return {
        "noise_removal_rate": run_metrics.noise_removal_rate,
        "layers": layers,
        "skipped_layers": skipped_layers or [],
        "log_events_by_layer": log_events_by_layer,
    }


def _build_panel4(
    reasoning_result: ReasoningResult,
    run_metrics: RunMetrics,
    fingerprint_map: dict[str, str],
) -> dict:
    """panel4_report：分析報告面板。"""
    conclusion = reasoning_result.conclusion or {}
    debate = reasoning_result.debate or {}

    # core_facts from reasoning facts
    core_facts: list[dict] = []
    for fact in reasoning_result.facts:
        for eid in fact.get("evidence_ids", []):
            fp = fingerprint_map.get(eid, "")
            if fp:
                core_facts.append({"fingerprint": fp, "text": fact.get("summary", "")})
                break  # one fingerprint per fact

    # bullish/risk evidence from debate or inference
    bullish_evidence: list[dict] = []
    risk_evidence: list[dict] = []

    if debate:
        for eid in debate.get("bull_evidence_ids", []):
            fp = fingerprint_map.get(eid, "")
            if fp:
                bullish_evidence.append({"fingerprint": fp, "evidence_id": eid})
        for eid in debate.get("bear_evidence_ids", []):
            fp = fingerprint_map.get(eid, "")
            if fp:
                risk_evidence.append({"fingerprint": fp, "evidence_id": eid})
    else:
        # Fallback: from inference supporting/opposing
        for inf in reasoning_result.inference:
            for eid in inf.get("supporting_evidence_ids", []):
                fp = fingerprint_map.get(eid, "")
                if fp:
                    bullish_evidence.append({"fingerprint": fp, "evidence_id": eid})
            for eid in inf.get("opposing_evidence_ids", []):
                fp = fingerprint_map.get(eid, "")
                if fp:
                    risk_evidence.append({"fingerprint": fp, "evidence_id": eid})

    # 執行摘要：跟 report.md 的「執行摘要」同一套邏輯與資料來源（重組既有欄位，
    # 不多打一次 LLM），供面板④最上方的醒目摘要卡片使用
    invalidation_conditions = conclusion.get("invalidation_conditions", [])
    if invalidation_conditions:
        watchpoint = invalidation_conditions[0]
        watchpoint_label = "最需留意的推翻條件"
    elif reasoning_result.follow_up_watchpoints:
        watchpoint = reasoning_result.follow_up_watchpoints[0]
        watchpoint_label = "最需留意的後續觀察"
    else:
        watchpoint, watchpoint_label = "", ""

    summary = {
        "confidence_label": conclusion.get("confidence", "未知"),
        "bull_argument": debate.get("bull_argument", ""),
        "bull_evidence_ids": debate.get("bull_evidence_ids", []),
        "bear_argument": debate.get("bear_argument", ""),
        "bear_evidence_ids": debate.get("bear_evidence_ids", []),
        "has_debate": bool(debate),
        "watchpoint": watchpoint,
        "watchpoint_label": watchpoint_label,
    }

    return {
        "integrity_status": run_metrics.integrity_status,
        "degraded_reasons": run_metrics.degraded_reasons,
        "confidence": reasoning_result.confidence_score,
        "market_judgment": conclusion.get("market_judgment", ""),
        "summary": summary,
        "core_facts": core_facts,
        "bullish_evidence": bullish_evidence,
        "risk_evidence": risk_evidence,
        "limitations": conclusion.get("limitations", []),
        "invalidation_conditions": conclusion.get("invalidation_conditions", []),
        "follow_up_watchpoints": reasoning_result.follow_up_watchpoints,
    }


# --- Utility ---


def _compute_removed_items(
    evidences: list[Evidence],
    reasoning_result: ReasoningResult,
    filter_decisions: list[FilterDecision],
    fingerprint_map: dict[str, str],
) -> list[dict]:
    """反推 L3 事實提取層剔除的證據明細（fingerprint + reason）。

    「剔除」定義為：該證據未被事實層（Step A）任何一則 fact 引用。
    若該證據在 L2 已有過濾判定（PR/F10），優先沿用該理由；否則標記為
    「事實層未引用」——誠實反映我們只知道結果、不知道 LLM 內部篩選細節。
    """
    kept_ids: set[str] = set()
    for fact in reasoning_result.facts:
        kept_ids.update(fact.get("evidence_ids", []))

    decisions_by_ev: dict[str, FilterDecision] = {}
    for fd in filter_decisions:
        # 若同一筆有多個判定，保留第一個（PR 通常比 F10 更具體）
        decisions_by_ev.setdefault(fd.evidence_id, fd)

    removed_items: list[dict] = []
    for ev in evidences:
        if ev.id in kept_ids:
            continue
        fd = decisions_by_ev.get(ev.id)
        reason = fd.reason if fd else "事實層未引用（可能為次要或重複資訊，非可驗證事實）"
        removed_items.append(
            {
                "fingerprint": fingerprint_map.get(ev.id, ""),
                "evidence_id": ev.id,
                "reason": reason,
            }
        )
    return removed_items


def _find_log_metrics(log_entries: list[LogEntry], action: str) -> dict:
    """從 log entries 中找出指定 action 的最新 metrics。"""
    for entry in reversed(log_entries):
        if entry.action == action:
            return entry.metrics
    return {}


def _group_log_by_layer(log_entries: list[LogEntry]) -> dict[str, list[dict]]:
    """將 log entries 依 layer 分組。"""
    groups: dict[str, list[dict]] = {}
    for entry in log_entries:
        if entry.layer is not None:
            layer_key = entry.layer.value if hasattr(entry.layer, "value") else str(entry.layer)
            groups.setdefault(layer_key, []).append(entry.model_dump())
    return groups

"""L5 可解釋信心分數（horizon-aware-confidence R3）。

    Final = Base(0.4×資料品質 + 0.4×訊號一致性 + 0.2×證據強度) + 辯論調整(−15~+5)
            └────────────── 決定性、可複現 ──────────────┘   └── LLM 裁判，需附理由 ──┘

設計理由見 design.md ADR-5：需求方同時要「每次跑同一套分析得到一致結果」與
「透過辯論後才知道信心」，兩者有張力。分層讓兩者都成立且各自可稽核。

取代舊制 `compute_confidence_score()`（base 來自 LLM 自報的高/中/低，佔最終分數
70-80%，既非資料信心也非可複現）。舊函式已移除，其測試依 R6-4 改寫為新公式的
等價驗證而非刪除——對照關係見 `tests/test_confidence_score.py` 檔頭表格。

公式各項 SHALL 寫入 log metrics 可對帳（layer=L5_conclusion）。
"""

from __future__ import annotations

import itertools
from datetime import date

from agent.schemas import (
    DEFAULT_PRIMARY_HORIZON,
    Evidence,
    HorizonClass,
    SourceType,
    is_current_signal,
)

# 六類來源完整集合（含 derivatives——舊制漏了它，Ken 的衍生品資料再完整也不會
# 改善 gap_penalty，等於白做工。這是 requirements.md D7 記錄的既有 bug）。
SOURCE_TYPE_CATEGORIES: set[SourceType] = {
    SourceType.PRICE,
    SourceType.ONCHAIN,
    SourceType.NEWS,
    SourceType.SOCIAL,
    SourceType.MACRO,
    SourceType.DERIVATIVES,
}

# 三維權重（R3-7）
WEIGHT_DATA = 0.4
WEIGHT_CONSENSUS = 0.4
WEIGHT_STRENGTH = 0.2

# 辯論調整範圍（R3-8）。**不對稱是刻意的**：辯論若揭露實質漏洞應大幅下修，
# 若只是確認原有判斷最多小幅上調。允許大幅加分等於讓 LLM 的自我感覺良好
# 侵蝕分數公信力——那正是舊制的失敗模式，不能換個位置重演（ADR-5）。
DEBATE_ADJUSTMENT_MIN = -15
DEBATE_ADJUSTMENT_MAX = 5

# 最終分數夾值
SCORE_MIN = 5
SCORE_MAX = 95

# 樣本不足以談共識時的中性值（R3-15 也用這個值）
CONSENSUS_NEUTRAL = 50.0

# 各類「完整」的判定門檻：(最少筆數, 最短窗長天數)。窗長 0 代表快照類不要求窗長。
# 暫定值，待與 Ken 校準（requirements.md 待確認事項 #3）——集中在這張表，
# 校準時只改這裡不動邏輯。
DATA_COMPLETENESS_THRESHOLD: dict[SourceType, tuple[int, int]] = {
    SourceType.PRICE: (3, 14),
    SourceType.ONCHAIN: (2, 0),
    SourceType.NEWS: (5, 7),
    SourceType.SOCIAL: (3, 3),
    SourceType.MACRO: (2, 14),
    SourceType.DERIVATIVES: (4, 7),
}

# 三檔評分比例（R3-1）
TIER_COMPLETE = 1.0
TIER_PARTIAL = 0.6
TIER_MISSING = 0.0


def _window_span_days(ev: Evidence) -> int:
    """單筆證據的觀察窗天數（含端點）；無窗口資訊回 0。"""
    if not ev.window_start or not ev.window_end:
        return 0
    try:
        start = date.fromisoformat(ev.window_start)
        end = date.fromisoformat(ev.window_end)
    except ValueError:
        return 0
    return (end - start).days + 1


def compute_data_confidence(evidences: list[Evidence]) -> tuple[float, dict]:
    """資料品質（R3-1/R3-2）：六類各佔 100/6，依三檔評分。純統計，不呼叫 LLM。

    「部分」給 60% 而不是滿分，是為了讓「只有 2 篇新聞」這種情境誠實反映出來——
    價格資料再漂亮，來源涵蓋不足就不該說 High Confidence。
    """
    per_type_score = 100.0 / len(SOURCE_TYPE_CATEGORIES)
    detail: dict[str, dict] = {}
    total = 0.0

    for source_type in sorted(SOURCE_TYPE_CATEGORIES, key=lambda t: t.value):
        items = [e for e in evidences if e.source_type == source_type]
        min_count, min_window = DATA_COMPLETENESS_THRESHOLD[source_type]
        max_span = max((_window_span_days(e) for e in items), default=0)

        if not items:
            tier, reason = TIER_MISSING, "本次無可用證據"
        elif len(items) >= min_count and max_span >= min_window:
            tier, reason = TIER_COMPLETE, f"{len(items)} 筆，最長窗長 {max_span} 天"
        else:
            tier = TIER_PARTIAL
            gaps = []
            if len(items) < min_count:
                gaps.append(f"僅 {len(items)} 筆（需 {min_count} 筆）")
            if max_span < min_window:
                gaps.append(f"最長窗長 {max_span} 天（需 {min_window} 天）")
            reason = "；".join(gaps)

        score = per_type_score * tier
        total += score
        detail[source_type.value] = {
            "tier": tier,
            "score": round(score, 2),
            "count": len(items),
            "max_window_days": max_span,
            "required_count": min_count,
            "required_window_days": min_window,
            "reason": reason,
        }

    return round(total, 2), detail


def compute_signal_consensus(
    direction_matrix: list[dict],
    evidences: list[Evidence],
    primary_horizon: HorizonClass | None = None,
) -> tuple[float, dict]:
    """訊號一致性（R3-4/R3-5）：來源之間的兩兩一致度。

        Consensus = 100 × (1 − 所有來源配對的方向差異平均 / 2)

    白話：**隨便抓兩個來源出來，它們意見相同的機率有多高。**

    **只納入當前訊號**——結構脈絡（長於主視野的帶）不參與投票，否則本規格
    要修的假矛盾會從這條路徑復活（design.md §3.6.2）。

    公式選型（2026-07-28 alanchang 拍板，實算 729 種組合後定案）：
    原設計的線性 stdev 映射有兩個致命傷——6 個來源裡 5 個看多只給 25 分
    （實際上是相當強的共識），且 35.7% 的情境擠在 0-20 分區間、失去鑑別度。
    候選的 `100×|mean|` 更差（53.9% 擠在低分區），且「全部中性」會給 0 分，
    但那其實是完美一致、只是沒方向。兩兩一致度三個問題都沒有，分佈開展在
    整個區間（0-20 佔 0%），語意也最好解釋。逐案比較見 design.md §3.6.2。
    """
    current_types = {
        e.source_type.value
        for e in evidences
        if is_current_signal(e.horizon_class, primary_horizon)
    }

    used: list[dict] = []
    seen: set[str] = set()
    for row in direction_matrix:
        source_type = row.get("source_type")
        if source_type not in current_types or source_type in seen:
            continue
        seen.add(source_type)
        used.append(row)

    dirs = [int(row["direction"]) for row in used]
    if len(dirs) < 2:
        # 一個來源談不上「共識」，硬給高分或低分都是誤導，中性處理。
        return CONSENSUS_NEUTRAL, {
            "sample_size": len(dirs),
            "directions": used,
            "degraded": True,
            "degraded_reason": "當前訊號帶的表態來源不足 2 個，訊號共識以中性 50 計算",
        }

    # 方向值域是 {-1, 0, 1}，任兩者的差異最大為 2，故除以 2 正規化到 0-1。
    pair_diffs = [abs(a - b) for a, b in itertools.combinations(dirs, 2)]
    mean_diff = sum(pair_diffs) / len(pair_diffs)
    consensus = max(0.0, min(100.0, 100 * (1 - mean_diff / 2)))
    return round(consensus, 2), {
        "sample_size": len(dirs),
        "directions": used,
        "mean_pairwise_diff": round(mean_diff, 4),
        "degraded": False,
    }


def compute_evidence_strength(evidences: list[Evidence]) -> tuple[float, dict]:
    """證據強度（R3-6）：各類平均 `source_weight` × 類別覆蓋度折減。

    刻意**不**引入 LLM 主觀評分（ADR-4）——需求方的核心訴求是可解釋、可複現，
    若讓 LLM 給「Price=90, Social=60」這類分數，等於在剛拆掉的主觀基底旁邊
    裝一個新的。R12 四因子信譽（新鮮度×來源等級×覆蓋度×dedup_penalty）已經是
    「這個訊號有多強」的既有答案，重造輪子只會產生兩套打架的權威度定義。
    """
    per_type: dict[str, float] = {}
    for source_type in SOURCE_TYPE_CATEGORIES:
        weights = [e.source_weight for e in evidences if e.source_type == source_type]
        if weights:
            per_type[source_type.value] = round(sum(weights) / len(weights), 4)

    if not per_type:
        return 0.0, {"per_type_avg_weight": {}, "coverage": 0.0}

    avg_weight = sum(per_type.values()) / len(per_type)
    coverage = len(per_type) / len(SOURCE_TYPE_CATEGORIES)
    strength = avg_weight * coverage * 100
    return round(strength, 2), {
        "per_type_avg_weight": per_type,
        "coverage": round(coverage, 4),
        "avg_weight": round(avg_weight, 4),
    }


def _clamp_debate_adjustment(raw, reason: str) -> tuple[int, int | None, str]:
    """回傳 (採用值, 原始值, 夾值說明)。無理由一律視為 0（R3-10）。"""
    if not isinstance(reason, str) or not reason.strip():
        return 0, raw if isinstance(raw, (int, float)) else None, "未提供調整理由，視為 0"
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0, None, "裁判未提供有效的調整值，視為 0"
    clamped = max(DEBATE_ADJUSTMENT_MIN, min(DEBATE_ADJUSTMENT_MAX, int(raw)))
    if clamped != int(raw):
        return clamped, int(raw), f"原始值 {int(raw)} 超出 [{DEBATE_ADJUSTMENT_MIN}, {DEBATE_ADJUSTMENT_MAX}]，已夾值"
    return clamped, int(raw), ""


def compute_confidence(
    evidences: list[Evidence],
    cross_validation: dict,
    debate_adjustment=None,
    debate_adjustment_reason: str = "",
    primary_horizon: HorizonClass | None = None,
) -> tuple[int, dict]:
    """計算 L5 信心分數，回傳 (score, breakdown)。

    `cross_validation` 需含 `direction_matrix`（Step B 產出）；缺漏時 Signal
    Consensus 降級為中性 50 並在 breakdown 標記（R3-15）。

    `structural_context` **不進入任何扣分路徑**（R2-8）——跨尺度差異是位置關係
    不是矛盾，那正是本規格要修的核心問題。
    """
    data_conf, data_detail = compute_data_confidence(evidences)
    consensus, consensus_detail = compute_signal_consensus(
        cross_validation.get("direction_matrix", []) or [], evidences, primary_horizon
    )
    strength, strength_detail = compute_evidence_strength(evidences)

    base = WEIGHT_DATA * data_conf + WEIGHT_CONSENSUS * consensus + WEIGHT_STRENGTH * strength
    adjustment, raw_adjustment, clamp_note = _clamp_debate_adjustment(
        debate_adjustment, debate_adjustment_reason
    )
    final = max(SCORE_MIN, min(SCORE_MAX, round(base + adjustment)))

    breakdown = {
        "data_confidence": data_conf,
        "data_confidence_detail": data_detail,
        "signal_consensus": consensus,
        "signal_consensus_detail": consensus_detail,
        "evidence_strength": strength,
        "evidence_strength_detail": strength_detail,
        "weights": {
            "data_confidence": WEIGHT_DATA,
            "signal_consensus": WEIGHT_CONSENSUS,
            "evidence_strength": WEIGHT_STRENGTH,
        },
        "base": round(base, 2),
        "debate_adjustment": adjustment,
        "debate_adjustment_raw": raw_adjustment,
        "debate_adjustment_reason": debate_adjustment_reason or "",
        "debate_adjustment_note": clamp_note,
        "primary_horizon": (primary_horizon or DEFAULT_PRIMARY_HORIZON).value,
        "structural_context_count": len(cross_validation.get("structural_context", []) or []),
        "final": final,
    }
    breakdown["why"] = build_why_lines(breakdown)
    return final, breakdown


WHY_REASON_MAX_CHARS = 100


def _summarize_reason(reason: str) -> str:
    """把辯論理由壓成適合放進條列的一行。"""
    flat = " ".join(reason.split())
    if len(flat) <= WHY_REASON_MAX_CHARS:
        return flat
    return flat[:WHY_REASON_MAX_CHARS] + "…（完整理由見信心說明）"


def build_why_lines(breakdown: dict) -> list[str]:
    """「Why this confidence?」（R3-13）：由扣分項決定性反查生成，**不呼叫 LLM**。

    很多 AI 報告的問題是只有分數沒有解釋。這裡讓每個未滿分項自動產生一行說明，
    使用者不只知道分數，還知道分數是怎麼算出來的、哪些因素拉高或拉低。
    決定性生成比讓 LLM 寫更可靠（同輸入必同輸出）也更省 token。
    """
    lines: list[str] = []

    for source_type, item in breakdown.get("data_confidence_detail", {}).items():
        if item["tier"] == TIER_MISSING:
            lines.append(f"⚠ {source_type} 本次無可用證據，資料完整度該項得 0 分")
        elif item["tier"] == TIER_PARTIAL:
            lines.append(f"⚠ {source_type} {item['reason']}，未達完整門檻，該項得 60%")
        else:
            lines.append(f"✅ {source_type} 資料完整（{item['reason']}）")

    consensus = breakdown.get("signal_consensus", CONSENSUS_NEUTRAL)
    detail = breakdown.get("signal_consensus_detail", {})
    if detail.get("degraded"):
        lines.append(f"ℹ️ {detail.get('degraded_reason', '訊號共識降級為中性')}")
    else:
        summary = "、".join(
            f"{row['source_type']}{'看多' if int(row['direction']) > 0 else '看空' if int(row['direction']) < 0 else '中性'}"
            for row in detail.get("directions", [])
        )
        if consensus >= 80:
            lines.append(f"✅ {detail.get('sample_size', 0)} 類來源方向一致（{summary}），訊號共識高")
        elif consensus < 50:
            lines.append(f"⚠ 來源方向分歧（{summary}），市場缺乏共識")

    adjustment = breakdown.get("debate_adjustment", 0)
    # why 是條列摘要，理由過長會把整份清單淹掉（實測 LLM 回過 700+ 字的評析）。
    # 這裡截短，完整理由由報告層另外整段呈現。
    reason = _summarize_reason(breakdown.get("debate_adjustment_reason", ""))
    if adjustment < 0:
        lines.append(f"⚠ 辯論後下修 {abs(adjustment)} 分：{reason}")
    elif adjustment > 0:
        lines.append(f"✅ 辯論後上修 {adjustment} 分：{reason}")

    structural_count = breakdown.get("structural_context_count", 0)
    if structural_count:
        lines.append(
            f"ℹ️ 另有 {structural_count} 項結構脈絡（跨時間尺度的位置關係，"
            "不計入矛盾也不扣分），詳見報告第 3 節"
        )

    return lines

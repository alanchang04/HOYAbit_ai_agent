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
    HORIZON_ORDER,
    Evidence,
    HorizonClass,
    Persistence,
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

# `debate_summary` 的點數上限（prompt 要求 3-5 點）。夾值範圍由它與級距推出。
MAX_SUMMARY_POINTS = 5

# 逐點判定 → 分數（2026-08-01 新增）。
#
# 背景：讓裁判直接吐一個 -15~+5 的整數，實測在真實區間內幾乎沒有鑑別力。同一份輸入
# 重打 5 次全是 −3；換三種題型、四種幣種全是 −3；把「反方打中兩項」削成「打中一項」
# 還是 −3。只有把反方整段換成無證據的空話才會翻成 +3。也就是說模型輸出的不是
# 「這場辯論值多少分」，而是「要調一點點」這個念頭，方向對、幅度沒有解析度。
#
# 改法：裁判本來就已經逐點判定攻防結果（debate_summary），改成每點附一個 verdict，
# 由程式加總。分數來自可稽核的逐項判定，讀者能自己驗算。
#
# ── 為什麼要分題型（2026-08-01 第二次修正）─────────────────────────
# 原本只有一套不對稱級距（bear_valid −3／bull_defended +1，且反方有兩個得分等級、
# 正方只有一個）。那個不對稱繼承自 ADR-5 的防灌分設計，而它預設了
# **「反方＝質疑者、正方＝被質疑的原判斷」**。這個前提只有多源整合題成立：
#
#   多源整合  正方「市場比表面更好」 vs 反方「更脆弱」  → 反方確實在挑毛病 ✅
#   比較分析  正方「SOL 更值得關注」 vs 反方「XRP 更值得」→ 兩邊都是倡議者 ❌
#   假設驗證  正方「題目陳述為真」   vs 反方「為假」      → 正方被指派論證一個
#                                                        可能為假的命題 ❌
#
# 實測後果：
# - 比較題：Q3 與 T2 是同一題、只把兩幣語序對調，兩次得到**相同的實質判斷**
#   （都判 SOL 風險較高），但 XRP 站反方時扣 7 分、站正方時只扣 3 分。
#   分數取決於主辦方先寫哪個幣。
# - 假設驗證題：T4 的假設在證據上站不住，系統用最高權重證據給出九次跑裡
#   **最明確的否定**，卻拿到**最大扣分 −11**。因為正方被指定去論證一個假命題，
#   它必然出現推理瑕疵——那些瑕疵是「假設為假」的結果，不是報告品質的訊號。
#   激勵方向是反的：假設越明顯為假，信心扣得越多。
#
# 解法：級距隨題型走。「質疑者 vs 被質疑者」的題型維持不對稱（防灌分的原始理由
# 在那裡仍然成立）；「兩個對等立場」的題型改用對稱級距，並補上 `bull_partial`
# ——粒度也必須對稱，否則「XRP 方部分成立」表達得出、「SOL 方部分成立」表達不出。

# 對稱級距：正反方是對等立場時用。任一方勝出只反映「這一點誰的證據較強」，
# 不代表報告本身可靠或不可靠，所以幅度小且兩側相同。
_SYMMETRIC_VERDICT_SCORES: dict[str, int] = {
    "bear_valid": -2,
    "bear_partial": -1,
    "draw": 0,
    "bull_partial": 1,
    "bull_defended": 2,
}

# 不對稱級距：反方是質疑者時用（多源整合）。反方打中＝揭露了實質漏洞，該重扣；
# 正方守住＝原判斷通過壓力測試，小幅加分即可（ADR-5 的防灌分原意）。
_ASYMMETRIC_VERDICT_SCORES: dict[str, int] = {
    "bear_valid": -3,
    "bear_partial": -1,
    "draw": 0,
    "bull_partial": 1,
    "bull_defended": 1,
}

# 題型 → 級距。比較分析與假設驗證的正反方是對等立場（理由見上方長註解）。
_SCORES_BY_QUESTION_TYPE: dict[str, dict[str, int]] = {
    "multi_source": _ASYMMETRIC_VERDICT_SCORES,
    "comparison": _SYMMETRIC_VERDICT_SCORES,
    "hypothesis_test": _SYMMETRIC_VERDICT_SCORES,
}

# 相容別名：未指定題型時的預設級距（既有呼叫端與測試沿用）。
VERDICT_SCORES: dict[str, int] = _ASYMMETRIC_VERDICT_SCORES


def scores_for_question_type(question_type: str | None) -> dict[str, int]:
    """取得該題型的 verdict 級距；未知題型退回不對稱版（既有行為）。"""
    return _SCORES_BY_QUESTION_TYPE.get(question_type or "", _ASYMMETRIC_VERDICT_SCORES)


def adjustment_range_for(question_type: str | None) -> tuple[int, int]:
    """該題型的辯論調整夾值範圍。

    **夾值範圍必須跟著級距走，否則會把剛拆掉的不對稱從夾值那條路徑放回來。**
    對稱題型下 5 點全給正方是 5×(+2)=+10，若沿用全域的 +5 上限，
    「正方全勝」會被砍成 +5、而「反方全勝」的 −10 完整保留——語序對調的鏡射
    在夾值後就破了。上下限取級距的實際極值（3-5 點 × 最大等級）。
    """
    scores = scores_for_question_type(question_type)
    if scores is _ASYMMETRIC_VERDICT_SCORES:
        return DEBATE_ADJUSTMENT_MIN, DEBATE_ADJUSTMENT_MAX
    span = max(abs(v) for v in scores.values()) * MAX_SUMMARY_POINTS
    return -span, span


# 模型不保證回 ASCII enum，中文同義詞一併認（寬鬆度與 `_coerce_adjustment()`、
# `pipeline._coerce_bool()` 對齊，避免同一條推理鏈上兩套標準）。
_VERDICT_ALIASES: dict[str, str] = {
    "反方成立": "bear_valid", "反方勝": "bear_valid", "反方得點": "bear_valid",
    "反方部分成立": "bear_partial", "部分成立": "bear_partial",
    "打平": "draw", "平手": "draw", "未分勝負": "draw",
    "正方部分成立": "bull_partial", "正方部分站得住": "bull_partial",
    "正方擋下": "bull_defended", "正方勝": "bull_defended",
    "正方得點": "bull_defended", "通過壓力測試": "bull_defended",
}

_ALL_VERDICTS = frozenset(_SYMMETRIC_VERDICT_SCORES) | frozenset(_ASYMMETRIC_VERDICT_SCORES)


def coerce_verdict(raw) -> str | None:
    """把裁判回報的逐點判定收斂成合法的 verdict 鍵；無法判讀時回 None。"""
    if not isinstance(raw, str):
        return None
    token = raw.strip().strip("\"'").lower()
    if token in _ALL_VERDICTS:
        return token
    return _VERDICT_ALIASES.get(raw.strip())


def tally_debate_verdicts(
    debate_summary, question_type: str | None = None
) -> tuple[int | None, dict[str, int]]:
    """把 debate_summary 的逐點判定加總成調整值，級距依題型選取。

    回傳 `(未夾值的加總, 各判定計數)`。**一點有效判定都沒有時回 `(None, {})`**，
    讓上層退回舊的「裁判自報整數」路徑——而不是回 0。這個區別很重要：
    fallback 路徑（無辯論）的 debate_summary 本來就是空陣列，回 0 會讓報告寫成
    「裁判未提供有效的調整值」，讀起來像模型沒答，但實際上是這次根本沒有辯論。
    """
    scores = scores_for_question_type(question_type)
    counts: dict[str, int] = {}
    if not isinstance(debate_summary, list):
        return None, counts
    for item in debate_summary:
        if not isinstance(item, dict):
            continue
        verdict = coerce_verdict(item.get("verdict"))
        if verdict is None or verdict not in scores:
            # 判讀不出來、或該級距沒有這個等級時計為 draw（0 分，不影響分數），
            # 不丟棄整點——與本檔其他地方一致的降級優先（R6-1）。
            verdict = "draw"
        counts[verdict] = counts.get(verdict, 0) + 1
    if not counts:
        return None, counts
    return sum(scores[v] * n for v, n in counts.items()), counts


_VERDICT_LABELS: dict[str, str] = {
    "bear_valid": "反方成立",
    "bear_partial": "反方部分成立",
    "draw": "打平",
    "bull_partial": "正方部分成立",
    "bull_defended": "正方擋下",
}
_VERDICT_ORDER = ("bear_valid", "bear_partial", "draw", "bull_partial", "bull_defended")


def format_verdict_tally(counts: dict[str, int], question_type: str | None = None) -> str:
    """把計數攤成一行可讀說明，放進報告的信心分項表格。"""
    scores = scores_for_question_type(question_type)
    parts = [
        f"{_VERDICT_LABELS[v]} {counts[v]} 點 × {scores[v]:+d}"
        for v in _VERDICT_ORDER
        if counts.get(v) and v in scores
    ]
    return "；".join(parts)

# 最終分數夾值
SCORE_MIN = 5
SCORE_MAX = 95

# 信心等級門檻（2026-08-01 新增）。在此之前「79%」來自本檔的決定性公式、「（中）」
# 來自 LLM 在 Step D 自報的 confidence 欄位，兩者掛在報告同一行卻沒有任何一致性檢查——
# 理論上可以印出「信心：92%（低）」而無人示警。實測也證明兩者脫鉤：把辯論的反方換成
# 無證據的空話後，debate_adjustment 從 −3 翻到 +3，LLM 自報的等級仍是「中」，一動也沒動。
#
# 門檻取 80／60 的理由：這組值讓 2026-08-01 三題實跑（79／78／74）的顯示等級與 LLM
# 當時自報的「中／中／中」完全一致——也就是說，這個改動不改變既有輸出的呈現，
# 只是把它變成可複現的。與 ADR-5「拿掉 LLM 自報信心」的方向一致；
# LLM 的 confidence 欄位仍保留在 JSON 中，只是不再作為顯示來源，兩者分歧時另行揭露。
CONFIDENCE_TIER_HIGH = 80
CONFIDENCE_TIER_MEDIUM = 60


def confidence_label(score: int | float) -> str:
    """由決定性分數推等級。同分數必同等級，不呼叫 LLM。"""
    if score >= CONFIDENCE_TIER_HIGH:
        return "高"
    if score >= CONFIDENCE_TIER_MEDIUM:
        return "中"
    return "低"

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

# R8-2：有效期覆蓋檢查。Persistence 只有三檔，借用 HorizonClass 五帶的順序來比較
# 「這個訊號能撐多遠」跟「主視野要多遠」──long 視為能覆蓋到最長帶（structural）。
_PERSISTENCE_EQUIVALENT_HORIZON: dict[Persistence, HorizonClass] = {
    Persistence.SHORT: HorizonClass.SHORT,
    Persistence.MEDIUM: HorizonClass.MEDIUM,
    Persistence.LONG: HorizonClass.STRUCTURAL,
}

# 差距門檻：**刻意不是「只要短於主視野就扣分」**。social／多數 derivatives 子來源
# persistence=short，在預設主視野 medium 下差距只有 1 帶（short→medium）——那正是
# 今天已通過三題型真實 Bedrock 驗證的最常見情境，若字面照抄 design.md「明顯短於」
# 就扣分，會讓這個已驗證情境系統性卡在 60 分，是不該有的回歸。
# 差距 ≥2 帶才觸發，只抓 design.md §3.9.2 真正要修的案例：問「過去一年」
# （primary=structural, idx4）但證據全是 short-persistence（idx1，差距3）。
_SEVERE_PERSISTENCE_MISMATCH_GAP = 2


def _persistence_severely_short(items: list[Evidence], primary: HorizonClass) -> bool:
    """該類證據裡，有效期最長的一筆是否仍嚴重覆蓋不到主視野。"""
    if not items:
        return False
    best_idx = max(
        HORIZON_ORDER.index(_PERSISTENCE_EQUIVALENT_HORIZON[e.persistence]) for e in items
    )
    return HORIZON_ORDER.index(primary) - best_idx >= _SEVERE_PERSISTENCE_MISMATCH_GAP


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


def compute_data_confidence(
    evidences: list[Evidence], primary_horizon: HorizonClass | None = None
) -> tuple[float, dict]:
    """資料品質（R3-1/R3-2）：六類各佔 100/6，依三檔評分。純統計，不呼叫 LLM。

    「部分」給 60% 而不是滿分，是為了讓「只有 2 篇新聞」這種情境誠實反映出來——
    價格資料再漂亮，來源涵蓋不足就不該說 High Confidence。

    R8-2：另外檢查「有效期是否嚴重覆蓋不到主視野」。修的是實測發現的自相矛盾——
    問「過去一年」時，19 筆全 17 天窗的證據仍判六類「完整」拿 100 分，但報告
    開頭同時寫著「⚠ 主視野無可用證據」。原函式完全不讀 horizon_class／persistence，
    看不出這種錯配。
    """
    primary = primary_horizon or DEFAULT_PRIMARY_HORIZON
    per_type_score = 100.0 / len(SOURCE_TYPE_CATEGORIES)
    detail: dict[str, dict] = {}
    total = 0.0

    for source_type in sorted(SOURCE_TYPE_CATEGORIES, key=lambda t: t.value):
        items = [e for e in evidences if e.source_type == source_type]
        min_count, min_window = DATA_COMPLETENESS_THRESHOLD[source_type]
        max_span = max((_window_span_days(e) for e in items), default=0)
        severely_short = _persistence_severely_short(items, primary)

        if not items:
            tier, reason = TIER_MISSING, "本次無可用證據"
        elif len(items) >= min_count and max_span >= min_window and not severely_short:
            tier, reason = TIER_COMPLETE, f"{len(items)} 筆，最長窗長 {max_span} 天"
        else:
            tier = TIER_PARTIAL
            gaps = []
            if len(items) < min_count:
                gaps.append(f"僅 {len(items)} 筆（需 {min_count} 筆）")
            if max_span < min_window:
                gaps.append(f"最長窗長 {max_span} 天（需 {min_window} 天）")
            if severely_short:
                gaps.append(f"訊號有效期覆蓋不到主視野（{primary.value}）")
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
            "persistence_covers_primary": not severely_short,
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


def _coerce_adjustment(raw) -> int | None:
    """把裁判回報的調整值收斂成整數；無法解讀時回 None。

    **容忍字串數字（"-8"／"-8.0"）**：把數值包成字串是 JSON 輸出常見的模型偏差，
    而這裡漏接的代價是整段辯論調整靜默歸零——辯論調整是 ADR-5 裡讓辯論真正影響
    分數的唯一機制，等於整場辯論白跑，且 note 會寫成「裁判未提供有效的調整值」，
    讀起來像模型沒答。寬鬆度刻意與 `pipeline._coerce_direction()` 對齊，
    避免同一條推理鏈上兩套標準。「很多」這類非數值仍然回 None。
    """
    if isinstance(raw, bool):  # bool 是 int 的子類，必須先擋掉
        return None
    if isinstance(raw, str):
        try:
            raw = float(raw.strip())
        except ValueError:
            return None
    if not isinstance(raw, (int, float)):
        return None
    try:
        return int(raw)  # inf/nan 在此拋出，不讓它污染分數
    except (ValueError, OverflowError):
        return None


def _clamp_debate_adjustment(raw, reason: str) -> tuple[int, int | None, str]:
    """回傳 (採用值, 原始值, 夾值說明)。無理由一律視為 0（R3-10）。"""
    value = _coerce_adjustment(raw)
    if not isinstance(reason, str) or not reason.strip():
        return 0, value, "未提供調整理由，視為 0"
    if value is None:
        return 0, None, "裁判未提供有效的調整值，視為 0"
    clamped = max(DEBATE_ADJUSTMENT_MIN, min(DEBATE_ADJUSTMENT_MAX, value))
    if clamped != value:
        return clamped, value, f"原始值 {value} 超出 [{DEBATE_ADJUSTMENT_MIN}, {DEBATE_ADJUSTMENT_MAX}]，已夾值"
    return clamped, value, ""


def compute_confidence(
    evidences: list[Evidence],
    cross_validation: dict,
    debate_adjustment=None,
    debate_adjustment_reason: str = "",
    primary_horizon: HorizonClass | None = None,
    debate_summary: list[dict] | None = None,
    question_type: str | None = None,
) -> tuple[int, dict]:
    """計算 L5 信心分數，回傳 (score, breakdown)。

    `cross_validation` 需含 `direction_matrix`（Step B 產出）；缺漏時 Signal
    Consensus 降級為中性 50 並在 breakdown 標記（R3-15）。

    `structural_context` **不進入任何扣分路徑**（R2-8）——跨尺度差異是位置關係
    不是矛盾，那正是本規格要修的核心問題。
    """
    data_conf, data_detail = compute_data_confidence(evidences, primary_horizon)
    consensus, consensus_detail = compute_signal_consensus(
        cross_validation.get("direction_matrix", []) or [], evidences, primary_horizon
    )
    strength, strength_detail = compute_evidence_strength(evidences)

    base = WEIGHT_DATA * data_conf + WEIGHT_CONSENSUS * consensus + WEIGHT_STRENGTH * strength

    # 優先用裁判的逐點判定加總；一點有效判定都沒有（fallback 路徑／舊格式）才退回
    # 「裁判自報一個整數」的舊路徑。
    tally, verdict_counts = tally_debate_verdicts(debate_summary, question_type)
    if tally is None:
        adjustment, raw_adjustment, clamp_note = _clamp_debate_adjustment(
            debate_adjustment, debate_adjustment_reason
        )
        adjustment_source = "llm_scalar"
    else:
        raw_adjustment = tally
        low, high = adjustment_range_for(question_type)
        adjustment = max(low, min(high, tally))
        clamp_note = (
            f"原始加總 {tally} 超出 [{low}, {high}]，已夾值" if adjustment != tally else ""
        )
        adjustment_source = "verdict_tally"

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
        "debate_adjustment_source": adjustment_source,
        "debate_verdict_counts": verdict_counts,
        "debate_verdict_detail": format_verdict_tally(verdict_counts, question_type),
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
    # 逐點判定加總時，分數怎麼來的比裁判的散文理由更有稽核價值——讀者可以自己驗算。
    detail = breakdown.get("debate_verdict_detail", "")
    basis = f"{detail}（{reason}）" if detail else reason
    if adjustment < 0:
        lines.append(f"⚠ 辯論後下修 {abs(adjustment)} 分：{basis}")
    elif adjustment > 0:
        lines.append(f"✅ 辯論後上修 {adjustment} 分：{basis}")

    structural_count = breakdown.get("structural_context_count", 0)
    if structural_count:
        lines.append(
            f"ℹ️ 另有 {structural_count} 項結構脈絡（跨時間尺度的位置關係，"
            "不計入矛盾也不扣分），詳見報告第 3 節"
        )

    return lines

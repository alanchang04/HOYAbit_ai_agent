"""四步推理鏈的 prompt 模板、題型分支與 JSON 解析輔助函式。"""

from __future__ import annotations

import json
import re

from agent.filters.signal_importance import get_base_importance, load_signal_importance_config
from agent.schemas import (
    DEFAULT_PRIMARY_HORIZON,
    HORIZON_ORDER,
    Evidence,
    HorizonClass,
    QuestionType,
    is_current_signal,
)

QUESTION_TYPE_KEYWORDS: dict[QuestionType, list[str]] = {
    "comparison": ["比較", "相較", "對比", "vs", "與.*相比"],
    "hypothesis_test": ["市場上有聲音認為", "是否", "驗證", "支持與反對", "正確嗎"],
    "multi_source": ["整體市場", "整合", "市場狀態", "市場表現"],
}

QUESTION_TYPE_FRAMING: dict[QuestionType, str] = {
    "multi_source": "本題屬於「多源整合」題型：請綜合各類來源給出整體市場狀態判斷，並說明各類資料之間的一致程度。",
    "hypothesis_test": "本題屬於「假設驗證」題型：請針對題目中的陳述，明確蒐集支持與反對的證據，並給出最終判斷與理由。",
    "comparison": "本題屬於「比較分析」題型：若證據僅涵蓋單一幣種，請在限制中明確指出比較對象的資料不足，避免憑空比較。",
}
# comparison 題型且已知第二幣種時，覆寫上面的通用 framing，改用具體幣種名稱
COMPARISON_FRAMING_WITH_COIN2 = (
    "本題屬於「比較分析」題型：請比較 {coin} 與 {coin2} 在流動性、市場關注度、風險敞口上的差異，"
    "並說明在什麼條件下各自更值得優先關注。"
)

BULL_FRAMING: dict[QuestionType, str] = {
    "multi_source": "你要建構「市場狀態比表面看起來更正面/更有支撐」的論證。",
    "hypothesis_test": "你要建構「題目中的陳述為真」的論證。",
    "comparison": "你要建構「當前市場位置對本幣種相對有利」的論證。",
}
BEAR_FRAMING: dict[QuestionType, str] = {
    "multi_source": "你要建構「市場狀態比表面看起來更脆弱/風險更高」的論證。",
    "hypothesis_test": "你要建構「題目中的陳述為假或站不住腳」的論證。",
    "comparison": "你要建構「當前市場位置對本幣種相對不利/風險較高」的論證。",
}
# comparison 題型且已知第二幣種時，覆寫成「正方挺 coin、反方挺 coin2」的具體對抗框架
BULL_FRAMING_COMPARISON_WITH_COIN2 = "你要建構「{coin} 相對於 {coin2} 更值得優先關注」的論證。"
BEAR_FRAMING_COMPARISON_WITH_COIN2 = "你要建構「{coin2} 相對於 {coin} 更值得優先關注」的論證（也就是反對正方對 {coin} 的偏好）。"


def _resolve_framing(question_type: QuestionType, coin: str, coin2: str | None) -> str:
    if question_type == "comparison" and coin2:
        return COMPARISON_FRAMING_WITH_COIN2.format(coin=coin, coin2=coin2)
    return QUESTION_TYPE_FRAMING.get(question_type, QUESTION_TYPE_FRAMING["multi_source"])


def _resolve_bull_framing(question_type: QuestionType, coin: str, coin2: str | None) -> str:
    if question_type == "comparison" and coin2:
        return BULL_FRAMING_COMPARISON_WITH_COIN2.format(coin=coin, coin2=coin2)
    return BULL_FRAMING.get(question_type, BULL_FRAMING["multi_source"])


def _resolve_bear_framing(question_type: QuestionType, coin: str, coin2: str | None) -> str:
    if question_type == "comparison" and coin2:
        return BEAR_FRAMING_COMPARISON_WITH_COIN2.format(coin=coin, coin2=coin2)
    return BEAR_FRAMING.get(question_type, BEAR_FRAMING["multi_source"])


def classify_question_type(question: str) -> QuestionType:
    """依關鍵字粗略判斷題型；三種題型的推理骨架皆為事實→交叉驗證→推論→結論，
    差異主要在 Step C/D 的框架（比較兩幣種 / 驗證特定陳述 / 綜合市場狀態）。
    """
    for qtype, keywords in QUESTION_TYPE_KEYWORDS.items():
        for kw in keywords:
            if re.search(kw, question):
                return qtype
    return "multi_source"


SYSTEM_PROMPT = """你是 HOYA BIT 加密市場分析 AI Agent 的推理引擎。
你的任務是根據提供的多來源證據，進行有層次的分析：
事實層 → 交叉驗證層 → 推論層 → 結論層。
規則：
1. 每個事實陳述、假設、結論都必須標註對應的 evidence id（格式如 ev-001），且該 id 必須是使用者提供清單中真實存在的 id。
2. 明確指出來源之間一致或矛盾的訊號，不可為了讓論述好看而隱藏矛盾證據。
3. 結論必須包含信心等級（高/中/低）、已知限制、可能推翻結論的條件。
4. 不得捏造證據中不存在的數據、事件或 evidence id。
5. 這不是價格預測系統，避免給出具體買賣建議（進場價、停損點等）。
6. 只能輸出使用者要求的 JSON，不要輸出任何 JSON 以外的文字或 markdown code fence。
7. 時間尺度（horizon）差異不等於矛盾：**比本次主視野更長**的尺度與當前訊號之間的落差是「位置關係」，應描述為脈絡而非衝突。本次主視野與當前訊號帶的實際界線見使用者訊息中的【時間尺度說明】，一律以該處為準。
8. 證據權重（weight）代表來源可信度。低權重證據不足以單獨推翻高權重證據，除非你能具體說明該高權重來源在此情境下為何不適用。
"""

# 分帶的天數描述。與 `schemas._HORIZON_UPPER_BOUND_DAYS` 一一對應——ADR-7 把 short
# 由「≤7 天」放寬成「≤10 天」以容納「10 日」標準粒度，這裡的文字必須跟著改，
# 否則等於對 LLM 謊報邊界。
_HORIZON_BAND_DESC: dict[HorizonClass, str] = {
    HorizonClass.SPOT: "spot=當下快照",
    HorizonClass.SHORT: "short=≤10天",
    HorizonClass.MEDIUM: "medium=11-30天",
    HorizonClass.LONG: "long=31-180天",
    HorizonClass.STRUCTURAL: "structural=>180天",
}

_WEIGHT_LEGEND = """【權重說明】weight 為來源可信度（0-1）。低權重證據（<0.5）不足以單獨推翻
  高權重證據（>0.8）；若要如此主張，必須說明該高權重來源在此情境下為何不適用。"""


def current_signal_bands(primary_horizon: HorizonClass | None = None) -> list[HorizonClass]:
    """`≤ 主視野` 的帶（當前訊號）。與 `schemas.is_current_signal()` 同一條界線。"""
    primary = primary_horizon or DEFAULT_PRIMARY_HORIZON
    return HORIZON_ORDER[: HORIZON_ORDER.index(primary) + 1]


def structural_bands(primary_horizon: HorizonClass | None = None) -> list[HorizonClass]:
    """`> 主視野` 的帶（結構脈絡）。主視野為 structural 時為空。"""
    primary = primary_horizon or DEFAULT_PRIMARY_HORIZON
    return HORIZON_ORDER[HORIZON_ORDER.index(primary) + 1 :]


def _band_names(bands: list[HorizonClass]) -> str:
    return "／".join(b.value for b in bands)


def build_evidence_legend(primary_horizon: HorizonClass | None = None) -> str:
    """證據清單前的說明區塊：horizon 分帶與權重對抗規則（R2-4/R4-2/R7-3）。

    **分帶說明必須隨主視野生成，不能寫死。** 計分層的當前訊號集合是
    `is_current_signal(h, primary)`（會隨題目滑動），若 prompt 這邊固定寫
    「spot/short/medium 是當前訊號」，兩層就只在 primary=medium 時重合：
    題目問「最近一年」時 long/structural 已是當前訊號，模型卻仍被指示把
    它們當結構脈絡——跨帶的真實矛盾會被導進不扣分的 structural_context，
    分數虛高；題目問「今天」時則相反，模型為 short/medium 表態而計分層
    全部丟棄，共識樣本可能不足 2 而降級。
    """
    primary = primary_horizon or DEFAULT_PRIMARY_HORIZON
    current = current_signal_bands(primary)
    structural = structural_bands(primary)
    bands_line = "｜".join(_HORIZON_BAND_DESC[b] for b in HORIZON_ORDER)

    if structural:
        role_lines = (
            f"  當前訊號帶＝{_band_names(current)}（≤ 主視野）：直接參與本次判斷。\n"
            f"  結構脈絡帶＝{_band_names(structural)}（> 主視野）：用來定位當前判斷處在\n"
            f"  大週期何處，不應與當前訊號當成互相矛盾。"
        )
    else:
        # 主視野已是最長帶，沒有任何「更長的尺度」可以拿來當脈絡。
        role_lines = (
            f"  當前訊號帶＝{_band_names(current)}（≤ 主視野）：五帶全部直接參與本次判斷。\n"
            f"  本次無結構脈絡帶——主視野已涵蓋最長尺度，長窗證據同樣是當前訊號，\n"
            f"  不可因為它「看起來很長期」就排除在判斷之外。"
        )

    return (
        f"""【時間尺度說明】每筆證據標註了 horizon（觀察窗尺度）：
  {bands_line}

  本次主判斷視野為 {primary.value}。
{role_lines}

"""
        + _WEIGHT_LEGEND
    )


# 相容別名：主視野為預設 medium 時的說明區塊。新程式碼請改呼叫 `build_evidence_legend()`。
EVIDENCE_LIST_LEGEND = build_evidence_legend()

# weight_reason 內嵌的最終來源等級格式：「…來源等級0.80(B+:理由)…」（含 PR 降級後結果）。
# 分級標籤取自 static/source_reputation.json（由 filter 層寫入 reason），此處僅解析、不寫死對照（R4-1）。
_LEVEL_IN_REASON = re.compile(r"來源等級[0-9.]+\(([^:：)）]+)[:：]")


def _grade_label(evidence: Evidence) -> str:
    """從證據的 weight_reason 解析出來源分級標籤（A+/A/B+…）。解析不到回空字串（優雅降級）。"""
    m = _LEVEL_IN_REASON.search(evidence.weight_reason or "")
    return m.group(1).strip() if m else ""


def _window_str(evidence: Evidence) -> str:
    """組出觀察窗字串；spot 類無起訖時回 'n/a'。"""
    start = getattr(evidence, "window_start", None)
    end = getattr(evidence, "window_end", None)
    if start and end:
        return f"{start}~{end}"
    if end:
        return f"~{end}"
    return "n/a"


# R8-4：結構脈絡帶排後面但不丟掉——排序只是位置效應，證據仍完整在清單裡。
_HORIZON_MATCH_CURRENT = 1.0
_HORIZON_MATCH_STRUCTURAL = 0.6


def _evidence_priority(
    evidence: Evidence,
    question_type: str | None,
    primary_horizon: HorizonClass | None,
    importance_config: dict | None,
) -> float:
    """priority = source_weight × base_importance × horizon_match（design.md §3.9.4）。

    不新增 Evidence Prioritizer 這一層（ADR-8）——LLM 讀清單本來就有位置效應，
    高優先排前面即可達到 Ken 提案要的效果，且排序不會讓任何證據從清單消失。
    """
    base_importance = get_base_importance(evidence.source_type.value, question_type, importance_config)
    horizon_match = (
        _HORIZON_MATCH_CURRENT
        if is_current_signal(evidence.horizon_class, primary_horizon)
        else _HORIZON_MATCH_STRUCTURAL
    )
    return evidence.source_weight * base_importance * horizon_match


def _format_evidence_list(
    evidences: list[Evidence],
    question_type: str | None = None,
    primary_horizon: HorizonClass | None = None,
) -> str:
    """組裝證據清單文字，依 priority 由高到低排序（R8-4）。

    `question_type`／`primary_horizon` 皆為選填——舊呼叫端不傳時，`get_base_importance`
    退回全域預設、`is_current_signal` 退回預設主視野，排序退化成「純看 source_weight」，
    不會壞，只是少了題型/尺度加權（R6-1 降級優先）。
    """
    importance_config = load_signal_importance_config()
    ordered = sorted(
        evidences,
        key=lambda e: _evidence_priority(e, question_type, primary_horizon, importance_config),
        reverse=True,
    )
    lines = []
    for e in ordered:
        grade = _grade_label(e)
        weight_field = f"weight={e.source_weight:.2f}" + (f" [{grade}]" if grade else "")
        horizon = getattr(e, "horizon_class", None)
        horizon_value = horizon.value if horizon is not None else "spot"
        # fetched_at 保留：spot 類證據沒有觀察窗，抽掉它模型就完全沒有時間參考，
        # 無從判斷這筆「快照」是當下的還是舊的。
        lines.append(
            f"- id={e.id} | coin={e.coin} | type={e.source_type.value} | {weight_field} | "
            f"horizon={horizon_value} | window={_window_str(e)} | fetched_at={e.fetched_at} | "
            f"source={e.source} | content={e.content_reference}"
        )
    return "\n".join(lines) if lines else "（本次無可用證據）"


# 辯論層的權重意識規則（R4-3）。SYSTEM_PROMPT 第 8 條是全域規則，但辯論是對抗場景，
# 雙方都有動機把對己方不利的高權重證據輕描淡寫帶過，因此在角色 prompt 內再明確一次。
DEBATE_WEIGHT_RULE = (
    "引用證據時必須意識到權重差距，不可把不同權重的證據當成勢均力敵："
    "以高權重證據（>0.8）支撐的論點，份量大於僅以低權重證據（<0.5）支撐的論點。"
    "若你要用低權重證據推翻高權重證據，必須具體說明該高權重來源在此情境下為何不適用。"
)


# 辯論層的立場堅持規則。**正反方共用同一份文字**，不對稱的誠實要求會讓裁判讀到
# 語氣不對等的兩段論證，進而系統性偏袒語氣篤定的那方——那是修辭差異，不是論據差異。
#
# 這條刻意把兩件事拆開：
#   立場力度 → 拉滿（對抗式辯論的價值全在這裡，預留退路等於自廢武功）
#   證據呈現 → 照實（信任提煉流水線不能在中間層注入雜訊，指望裁判事後打折）
# 原本正方規則 2 把兩者綁在一起（「不要誇大成過度肯定的語氣」壓的是力度），
# 且只加在正方身上，是這次要修掉的不對稱來源。
#
# **不掛在 `build_step_c_prompt`（單模型 fallback）上**：那條路徑沒有對手，
# 反而被要求為每個假設列出 `opposing_evidence_ids`，叫它「別提自己的限制」會直接
# 打架。fallback 要的是多假設並陳，不是辯護。
DEBATE_ADVOCACY_RULE = (
    "立場選定後就堅持到底：把己方立場講到最強，不要替自己預留退路，"
    "也不要主動列出自己論證的限制或反例——找漏洞是對手的工作，不是你的。"
    "但證據本身不得美化：不可把證據講得比實際更硬（樣本數、觀察窗、統計顯著性照實呈現），"
    "也不可宣稱某筆證據支持了它其實沒說的事。"
    "要誠實的是「這筆證據寫了什麼」，不是「你的立場有多堅定」。"
)

# 辯論輸出長度上限（待辦 11）。原本只加在正方第 2 輪——那是 Task 3.8 實測踩到
# 「27 筆證據時輸出被 max_tokens 截斷、燒掉 360 秒且整輪作廢」才補的。
# **第 1 輪面對同樣 27–51 筆證據卻沒有任何約束，承擔同一個截斷風險**，
# 且沒有前輪逐字稿在旁邊約束它。三個辯論位置共用同一份文字，避免再次漂移。
DEBATE_LENGTH_RULE = (
    "論證長度控制在 600 字以內。精煉的論證本來就比冗長的更有說服力，"
    "而且證據筆數多時不設限會生到輸出上限被截斷、整輪作廢。"
)


def format_evidence_weight_index(evidences: list[Evidence] | None) -> str:
    """辯論層專用的精簡證據索引：只有 id／權重／尺度，不含 content。

    C1/C2 拿到的只有 `facts` 與 `cross_validation` 這兩份 LLM 產出的摘要，裡面
    只帶 evidence id，沒有權重也沒有 horizon。要求辯士「意識到權重差距」卻不給他
    權重，模型只能自行臆測——所以補這份索引。不重貼 content 是因為內容本身已在
    事實層摘要裡，而辯論會跑多輪且逐輪累積逐字稿，prompt 長度得省著用。
    """
    if not evidences:
        return ""
    lines = []
    for e in evidences:
        grade = _grade_label(e)
        horizon = getattr(e, "horizon_class", None)
        horizon_value = horizon.value if horizon is not None else "spot"
        weight_field = f"weight={e.source_weight:.2f}" + (f" [{grade}]" if grade else "")
        lines.append(f"- {e.id} | {weight_field} | horizon={horizon_value}")
    return (
        "證據權重與尺度索引（內容見上方事實層／交叉驗證層，此處只列可信度與時間尺度）：\n"
        + "\n".join(lines)
    )


def _weight_index_section(evidences: list[Evidence] | None) -> str:
    """把索引包成 prompt 區塊；沒有證據可列時整段省略（降級不中斷，R6-1）。"""
    index = format_evidence_weight_index(evidences)
    return f"\n{index}\n" if index else ""


def build_step_a_prompt(
    coin: str,
    question: str,
    evidences: list[Evidence],
    coin2: str | None = None,
    primary_horizon: HorizonClass | None = None,
    question_type: str | None = None,
) -> str:
    coin_note = (
        f"本題涉及兩個幣種：{coin} 與 {coin2}。每筆證據都已標註 coin 欄位，"
        f"請在每個 fact 中一併填入該事實所屬的幣種（coin 欄位），若證據同時適用兩者可自行判斷歸類。"
        if coin2
        else ""
    )
    return f"""題目：{question}
幣種：{coin}{f'／{coin2}' if coin2 else ''}
{coin_note}

{build_evidence_legend(primary_horizon)}

以下是本次蒐集到的所有證據（含 evidence id 與 coin 欄位）：
{_format_evidence_list(evidences, question_type, primary_horizon)}

請執行【事實層】分析：將上述證據依 source_type（{'與 coin ' if coin2 else ''}）分組，各自摘要成客觀事實陳述（不做推論、不下判斷）。

請只輸出以下 JSON 格式：
{{
  "facts": [
    {{"source_type": "price", "coin": "{coin}", "summary": "客觀事實摘要", "evidence_ids": ["ev-001", "ev-002"]}},
    ...
  ]
}}
"""


def build_step_b_prompt(
    coin: str,
    question: str,
    evidences: list[Evidence],
    facts: list[dict],
    coin2: str | None = None,
    primary_horizon: HorizonClass | None = None,
    question_type: str | None = None,
) -> str:
    current = current_signal_bands(primary_horizon)
    structural = structural_bands(primary_horizon)
    current_names = _band_names(current)
    # 有結構脈絡帶才需要第三段；主視野已是最長帶時要求模型硬填，只會逼出捏造的
    # 「跨尺度落差」——所以明講留空，而不是刪掉欄位（下游一律讀得到這個 key）。
    if structural:
        structural_instruction = (
            f"3. structural_context：當前訊號（{current_names}）與結構脈絡"
            f"（{_band_names(structural)}）之間的\n"
            "   方向差異，一律寫在這裡而非 contradictions，並以「位置關係」措辭描述。\n"
            "   每點是**一句話**（約 1-2 句、100 字以內），不是一段完整分析——\n"
            "   這裡只需要點出「處在什麼位置」，不需要重新論證為什麼。\n"
            "   例：「兩週情緒轉強，但價格仍處 5 年分佈第 88 百分位，屬高位反彈而非底部啟動」。"
        )
        contradiction_scope = f"、或「當前訊號各帶（{current_names}）之間」"
        contradiction_caveat = "**比主視野更長的尺度落差不是矛盾**（見時間尺度說明）。"
    else:
        structural_instruction = (
            "3. structural_context：本次主視野已涵蓋最長尺度，沒有「比主視野更長」的\n"
            "   結構脈絡可言，請填空陣列 []。不要為了填滿欄位而把當前訊號之間的\n"
            "   方向差異搬到這裡——那些是真矛盾，該寫進 contradictions。"
        )
        contradiction_scope = f"、或「五帶（{current_names}）之間」"
        contradiction_caveat = (
            "本次五帶皆為當前訊號，長窗證據的反向訊號同樣算矛盾，不可當成脈絡略過。"
        )
    cross_coin_note = (
        f"本題涉及兩個幣種（{coin} 與 {coin2}），除了各幣種內部的一致/矛盾訊號，"
        f"也請特別留意「跨幣種」的對比訊號（例如哪個幣種的鏈上活躍度相對更高、哪個情緒面更負面）。"
        if coin2
        else ""
    )
    return f"""題目：{question}
幣種：{coin}{f'／{coin2}' if coin2 else ''}
{cross_coin_note}

事實層摘要如下：
{json.dumps(facts, ensure_ascii=False, indent=2)}

{build_evidence_legend(primary_horizon)}

原始證據清單（供比對細節）：
{_format_evidence_list(evidences, question_type, primary_horizon)}

請執行【交叉驗證層】分析，輸出**三段**：
1. consistent_signals：多個獨立來源指向同一方向的一致訊號。
   若多筆證據其實引用同一篇文章或同一原始資料，請註明「非獨立來源」以避免重複計算可信度。
2. contradictions：**真正的矛盾訊號**。只有「同一 horizon 帶內」{contradiction_scope}的
   方向衝突才算矛盾。{contradiction_caveat}
{structural_instruction}

另外輸出 direction_matrix：各 source_type 對市場方向的表態。
  - direction 只能是 1（看多）、0（中性）、-1（看空）三個整數之一，不可填小數或文字。
  - 只針對 horizon 為 {current_names}（當前訊號帶）的證據表態；
    若某 source_type 在這些帶內無證據，該類別直接省略不列。
  - basis 填該表態依據的 evidence id 清單。

請只輸出以下 JSON 格式：
{{
  "consistent_signals": ["一致訊號描述（可引用 evidence id）", ...],
  "contradictions": ["僅限同尺度或當前訊號三帶之間的真實衝突", ...],
  "structural_context": ["跨尺度的位置關係描述", ...],
  "direction_matrix": [
    {{"source_type": "price", "direction": 1, "basis": ["ev-001"]}},
    ...
  ]
}}
"""


def build_step_c_prompt(
    coin: str,
    question: str,
    question_type: QuestionType,
    facts: list[dict],
    cross_validation: dict,
    coin2: str | None = None,
    evidences: list[Evidence] | None = None,
) -> str:
    """單模型推論層 prompt（正反方辯論失敗時的 fallback，不分角色，一次產出多個假設）。"""
    framing = _resolve_framing(question_type, coin, coin2)
    return f"""題目：{question}
幣種：{coin}{f'／{coin2}' if coin2 else ''}
{framing}

事實層：
{json.dumps(facts, ensure_ascii=False, indent=2)}

交叉驗證層：
{json.dumps(cross_validation, ensure_ascii=False, indent=2)}
{_weight_index_section(evidences)}
請執行【推論層】分析：根據以上事實與交叉驗證結果，提出 1-3 個市場狀態假設。
每個假設都必須同時列出支持它的 evidence id 與反對/削弱它的 evidence id（若真的沒有反對證據可留空陣列，但不可省略欄位）。
{DEBATE_WEIGHT_RULE}

請只輸出以下 JSON 格式：
{{
  "inference": [
    {{"hypothesis": "市場狀態假設描述", "supporting_evidence_ids": ["ev-001"], "opposing_evidence_ids": []}},
    ...
  ]
}}
"""


def build_step_c1_bull_prompt(
    coin: str,
    question: str,
    question_type: QuestionType,
    facts: list[dict],
    cross_validation: dict,
    coin2: str | None = None,
    evidences: list[Evidence] | None = None,
) -> str:
    """推論層 Step C1：正方分析師，只准建構最有利的論證。

    論證的漏洞交給反方在 C2 挖，不由正方自己預告——這樣裁判看到的才是「反方真的
    找到了什麼」，而不是「正方自己招了什麼」。
    """
    framing = _resolve_bull_framing(question_type, coin, coin2)
    return f"""題目：{question}
幣種：{coin}{f'／{coin2}' if coin2 else ''}

你現在的角色是【正方分析師】。{framing}

事實層：
{json.dumps(facts, ensure_ascii=False, indent=2)}

交叉驗證層：
{json.dumps(cross_validation, ensure_ascii=False, indent=2)}
{_weight_index_section(evidences)}
規則：
1. 只能使用上面提供的事實與證據，不可引入未出現的資訊或杜撰數據。
2. 必須引用 evidence id 支撐你的論點。
3. {DEBATE_ADVOCACY_RULE}
4. {DEBATE_WEIGHT_RULE}
5. {DEBATE_LENGTH_RULE}

請只輸出以下 JSON 格式：
{{
  "argument": "正方完整論證，需引用具體事實",
  "evidence_ids": ["ev-001", ...]
}}
"""


def format_debate_transcript(rounds: list[dict]) -> str:
    """把已完成的辯論輪次攤成可讀的逐輪紀錄，供後續輪次與裁判參考。"""
    if not rounds:
        return "（本輪為第一輪，尚無先前辯論）"
    blocks = []
    for r in rounds:
        blocks.append(
            f"【第 {r.get('round', '?')} 輪】\n"
            f"[正方] {r.get('bull_argument', '')}\n"
            f"[反方對正方的批評] {r.get('bear_critique', '')}\n"
            f"[反方] {r.get('bear_argument', '')}"
        )
    return "\n\n".join(blocks)


def build_step_c1_bull_rebuttal_prompt(
    coin: str,
    question: str,
    question_type: QuestionType,
    facts: list[dict],
    cross_validation: dict,
    rounds: list[dict],
    coin2: str | None = None,
    round_no: int = 2,
    evidences: list[Evidence] | None = None,
) -> str:
    """推論層 Step C1（第二輪起）：正方看過反方的批評後反駁並修正自己的論證。"""
    framing = _resolve_bull_framing(question_type, coin, coin2)
    return f"""題目：{question}
幣種：{coin}{f'／{coin2}' if coin2 else ''}

你現在的角色是【正方分析師】，這是第 {round_no} 輪。{framing}

事實層：
{json.dumps(facts, ensure_ascii=False, indent=2)}

交叉驗證層：
{json.dumps(cross_validation, ensure_ascii=False, indent=2)}
{_weight_index_section(evidences)}
先前的辯論紀錄：
{format_debate_transcript(rounds)}

你的任務是【回應反方對你的批評】並產出修正後的論證：
1. 逐項回應反方的批評。批評成立的部分要誠實承認並修正你的論證，不要硬拗。
2. 批評不成立的部分，要具體說明為什麼（引用事實或 evidence id），不可只說「反方誤解了」。
3. 輸出你這一輪修正後的**完整**論證，不要只寫增補的片段，也不要原文照抄上一輪。
4. 逐項回應批評指的是「每點都要回到」，不是「每點都要長篇大論」。

規則：
1. 只能使用上面提供的事實與證據，不可引入未出現的資訊或杜撰數據。
2. 必須引用 evidence id 支撐你的論點。
3. {DEBATE_ADVOCACY_RULE}
   （上面任務 1 的「批評成立就承認」講的是回應對手已經打中的點，
   不是叫你另外自曝其短——沒被打中的弱點不必主動交出來。）
4. {DEBATE_WEIGHT_RULE}
5. {DEBATE_LENGTH_RULE}

請只輸出以下 JSON 格式：
{{
  "argument": "第 {round_no} 輪修正後的正方完整論證",
  "evidence_ids": ["ev-001", ...]
}}
"""


def build_step_c2_bear_prompt(
    coin: str,
    question: str,
    question_type: QuestionType,
    facts: list[dict],
    cross_validation: dict,
    bull_argument: str,
    coin2: str | None = None,
    rounds: list[dict] | None = None,
    round_no: int = 1,
    evidences: list[Evidence] | None = None,
) -> str:
    """推論層 Step C2：反方分析師，可看到正方論證，任務是批評它並建構反向論證。

    第二輪起會附上先前的辯論紀錄，並要求反方自報是否還有新的實質論點
    （`has_new_points`），讓辯論在雙方開始重複時提早收斂，不必固定燒滿輪數。
    """
    framing = _resolve_bear_framing(question_type, coin, coin2)
    transcript_section = (
        f"""
先前的辯論紀錄：
{format_debate_transcript(rounds)}
"""
        if rounds
        else ""
    )
    return f"""題目：{question}
幣種：{coin}{f'／{coin2}' if coin2 else ''}

事實層：
{json.dumps(facts, ensure_ascii=False, indent=2)}

交叉驗證層：
{json.dumps(cross_validation, ensure_ascii=False, indent=2)}
{_weight_index_section(evidences)}{transcript_section}
正方分析師本輪（第 {round_no} 輪）的論證如下：
{bull_argument}

你現在的角色是【反方分析師】。{framing}
你的任務有三部分：
1. critique：具體指出正方論證的邏輯漏洞、忽略的反面證據、樣本選擇偏誤，或過度解讀之處（不可只是空泛地說「證據不足」，要指名道姓引用具體 evidence id 或論點）。
2. argument：建構你自己的反方論證，盡量引用正方沒有使用到、或方向相反的事實與證據。
3. has_new_points：誠實判斷你這一輪是否真的提出了**新的**實質論點。
   若你已經只是在重複先前輪次講過的說法、或正方的修正已經合理回應了你的疑慮，
   請填 false 讓辯論收斂；只有在你確實還有尚未被回應的實質疑慮時才填 true。
   為了讓辯論看起來熱鬧而硬填 true 是不誠實的。

規則：
1. 只能使用上面提供的事實與證據，不可引入未出現的資訊或杜撰數據。
2. 必須引用 evidence id 支撐你的論點。
3. {DEBATE_ADVOCACY_RULE}
4. {DEBATE_WEIGHT_RULE}
   批評正方時同樣適用：指出正方「證據薄弱」前，先確認他引用的是高權重還是低權重證據。
5. {DEBATE_LENGTH_RULE}
   critique 與 argument 分別計算，不是合計 600 字。

請只輸出以下 JSON 格式：
{{
  "critique": "對正方論證的具體批評",
  "argument": "反方完整論證，需引用具體事實",
  "evidence_ids": ["ev-003", ...],
  "has_new_points": true
}}
"""


STOP_REASON_LABEL: dict[str, str] = {
    "converged": "反方自認已無新的實質論點，辯論提前收斂",
    "max_rounds": "達到輪數上限",
    "deadline": "剩餘時間不足以再跑一輪，提前進入裁判",
    "bull_failed": "正方該輪呼叫失敗，以已完成的輪次進入裁判",
    "bear_failed": "反方該輪呼叫失敗，以已完成的輪次進入裁判",
}


def _format_debate_section(debate: dict | None) -> str:
    """把辯論全文交給裁判。

    推論層被攤平成 inference 時只保留了正反方的 argument，反方對正方的 critique
    整段遺失——那正是辯論最有價值的產出。這裡把完整逐輪紀錄補回給 Step D，
    否則裁判等於沒看到反方的反駁就下結論。
    """
    if not debate:
        return ""
    rounds = debate.get("rounds") or []
    if not rounds:
        # 相容舊的單輪扁平結構
        rounds = [
            {
                "round": 1,
                "bull_argument": debate.get("bull_argument", ""),
                "bear_critique": debate.get("bear_critique", ""),
                "bear_argument": debate.get("bear_argument", ""),
            }
        ]
    stopped = STOP_REASON_LABEL.get(debate.get("stopped_reason", ""), "未紀錄")
    return f"""
辯論紀錄（共 {len(rounds)} 輪；結束原因：{stopped}）：
{format_debate_transcript(rounds)}

裁判守則：
1. 你必須明確評估反方的批評是否成立，**兩個方向都要有結論**：
   - 批評成立 → market_judgment 與 confidence 據此下修，並把該批評寫進 limitations。
   - 批評不成立、且正方以具體事實或 evidence id 成功反駁 → **這是正方論證通過壓力測試
     的證據，debate_adjustment 應據此上調**，並在理由中寫明是哪一項批評被擋下。
   不可略過批評直接採信正方；但也不可因為反方提出了批評，就在批評其實不成立時
   仍然扣分。**「反方打中」與「正方擋住」都是辯論的有效產出，兩者都要反映在調整值上。**
2. 若有多輪，後續輪次的論證已經過反駁與修正，應比第一輪的初始版本更有參考價值；
   但若某一方在後續輪次只是重複或迴避批評，這件事本身就是該方論證薄弱的證據。
3. **雙方都被要求只管建構己方論證、不主動交代自身弱點**，所以兩邊的論證都不會
   自帶但書，語氣篤定不等於論據紮實。你要對雙方施以同等的檢視，不可因為某一方
   聽起來比較有把握就採信它。
4. 特別注意：**反方的最後一輪論證沒有人反駁過**（每輪都是正方先講、反方後講）。
   正方的漏洞有反方會挖，反方最後那段的漏洞只有你會看到——請主動檢查它引用的
   證據是否真的支持它的主張，並把發現寫進 limitations。
"""


def _has_debate_transcript(debate: dict | None) -> bool:
    """`_format_debate_section()` 是否會真的印出論證全文。"""
    if not debate:
        return False
    return bool(debate.get("rounds") or debate.get("bull_argument"))


def _format_inference_section(inference: list[dict], debate: dict | None) -> str:
    """推論層區塊；有辯論紀錄時只留辯論紀錄沒有的東西（HANDOFF 6.3）。

    有辯論時 `inference` 是從最後一輪攤平出來的，論證全文與下方辯論紀錄逐字重複——
    同一段文字餵兩次除了浪費 token，還可能讓裁判過度加權最後一輪。但辯論紀錄不印
    evidence id，所以不能整段拿掉，只截去重複的全文、保留 id 對應。
    """
    if not _has_debate_transcript(debate):
        return f"推論層：\n{json.dumps(inference, ensure_ascii=False, indent=2)}"

    compact = [
        {
            "hypothesis": _truncate_hypothesis(item.get("hypothesis", "")),
            "supporting_evidence_ids": item.get("supporting_evidence_ids", []),
            "opposing_evidence_ids": item.get("opposing_evidence_ids", []),
        }
        for item in inference
        if isinstance(item, dict)
    ]
    return (
        "推論層證據引用（論證全文見下方辯論紀錄，此處不重複）：\n"
        + json.dumps(compact, ensure_ascii=False, indent=2)
    )


def _truncate_hypothesis(text: str, limit: int = 40) -> str:
    """保留 `[正方]`／`[反方]` 標籤與開頭幾個字，讓 id 對得回是誰的論證即可。"""
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _debate_summary_instruction(debate: dict | None) -> str:
    """debate_summary 的指示文字；沒有辯論（fallback 路徑）時要求輸出空陣列，
    不要求模型硬編一份「攻防結果」出來——那不存在，編了就是幻覺。
    """
    if not _has_debate_transcript(debate):
        return (
            "本次未觸發正反辯論（fallback 路徑），debate_summary 請輸出空陣列 []，"
            "不要虛構攻防內容。"
        )
    return """另外輸出 debate_summary：這場辯論打了什麼、誰的哪個論點站得住腳、哪個被推翻，
給讀者不用看完兩輪逐字稿就能抓到重點。3-5 點，每點是一個具體的攻防結果
（不是「雙方各有論點」這種空話），且每點都要引用它所依據的 evidence id。
這是**你消化完整場辯論後的整理**，不是逐字稿的濃縮版——要點出「誰贏了這一點」，
不是「雙方都提到了這件事」。

請先想清楚 debate_summary 再寫 market_judgment：市場判斷應該是這場辯論攻防的
自然結果，不是另外重新分析一次。"""


def build_step_d_prompt(
    coin: str,
    question: str,
    question_type: QuestionType,
    facts: list[dict],
    cross_validation: dict,
    inference: list[dict],
    coin2: str | None = None,
    debate: dict | None = None,
) -> str:
    framing = _resolve_framing(question_type, coin, coin2)
    return f"""題目：{question}
幣種：{coin}{f'／{coin2}' if coin2 else ''}
{framing}

事實層：
{json.dumps(facts, ensure_ascii=False, indent=2)}

交叉驗證層：
{json.dumps(cross_validation, ensure_ascii=False, indent=2)}

{_format_inference_section(inference, debate)}
{_format_debate_section(debate)}
請執行【結論層】分析：綜合以上所有層次，給出最終市場判斷。
market_judgment 需開門見山說明判斷，不要用買賣建議（不要給進場價/停損點）。
confidence 只能是「高」、「中」或「低」三選一，並考量資料完整度、來源獨立性、矛盾訊號多寡來校準。
評估反方批評是否成立時，一併考量雙方所引用證據的權重分佈：以高權重證據支撐的論點，
比僅以低權重證據支撐的論點更有份量（低權重證據不足以單獨推翻高權重證據）。
follow_up_watchpoints 請列出 2-4 個具體、可觀察的後續追蹤重點（例如特定鏈上指標、特定事件的後續發展、
特定價位或情緒指標的變化），不要是空泛的「持續關注市場動態」這類廢話。

limitations 與 invalidation_conditions 回答的是不同問題，不要互相改寫成同一句話：
limitations 是「現在就存在的分析侷限」（資料缺口、因果無法確定、樣本/時效限制）；
invalidation_conditions 是「未來若觀察到什麼具體條件，這個結論就該被推翻」
（可觀察的價位/指標/事件門檻）。前者講的是「我現在不確定什麼」，
後者講的是「什麼會讓我改變主意」。

另外輸出 debate_adjustment：你對「這份分析報告本身」的信心調整，範圍 -15 到 +5 的整數。
這不是對市場的看多看空，而是「經過這場辯論，我對自己這個結論的把握變高還是變低」。
範圍不對稱是刻意的：辯論若揭露了實質漏洞，應大幅下修（可到 -15）；若只是確認了原有判斷，
最多小幅上調（+5 為上限）。
**但不對稱指的是「幅度」不是「方向」**——正方擋下反方的批評時就該給正值，
不要因為上限比較小就一律不給。若整場辯論的批評大多不成立、論證通過了壓力測試，
0 分是錯的答案。必須填寫 debate_adjustment_reason 說明理由，未填理由則視為 0。
debate_adjustment_reason **限 80 字以內、只講最關鍵的一個理由**——它會被放進報告的
信心分項表格裡，寫成長篇會把表格撐爆。完整的辯論評析請寫在 market_judgment 與
limitations，不要塞進這個欄位。

{_debate_summary_instruction(debate)}

請只輸出以下 JSON 格式：
{{
  "debate_summary": [
    {{"point": "反方對鏈上活躍度下滑的批評成立，正方未能有效反駁", "evidence_ids": ["ev-011"]}},
    ...
  ],
  "market_judgment": "最終市場判斷",
  "confidence": "高/中/低",
  "limitations": ["已知限制或資料不足之處", ...],
  "invalidation_conditions": ["可能推翻此結論的具體條件", ...],
  "evidence_ids": ["market_judgment 直接依據的 evidence id 清單"],
  "follow_up_watchpoints": ["具體後續觀察重點", ...],
  "debate_adjustment": -8,
  "debate_adjustment_reason": "調整理由（例：反方對鏈上活躍度的批評成立，正方第二輪未有效回應）"
}}
"""


def extract_json(text: str) -> dict:
    """從模型回應中解析 JSON。容忍模型仍包了 ```json ... ``` code fence 的情況。"""
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            return json.loads(brace_match.group(0))
        raise

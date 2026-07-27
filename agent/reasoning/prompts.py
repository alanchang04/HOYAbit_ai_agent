"""四步推理鏈的 prompt 模板、題型分支與 JSON 解析輔助函式。"""

from __future__ import annotations

import json
import re

from agent.schemas import Evidence, QuestionType

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
7. 不同時間尺度（horizon）的證據差異不等於矛盾。短窗訊號與長窗結構之間的落差是「位置關係」，應描述為脈絡而非衝突。
8. 證據權重（weight）代表來源可信度。低權重證據不足以單獨推翻高權重證據，除非你能具體說明該高權重來源在此情境下為何不適用。
"""

# 證據清單前的固定說明區塊：讓 LLM 看得懂 horizon 分帶與權重對抗規則（horizon-aware R2-4/R4-2）。
EVIDENCE_LIST_LEGEND = """【時間尺度說明】每筆證據標註了 horizon（觀察窗尺度）：
  spot=當下快照｜short=≤7天｜medium=8-30天（本次主判斷視野）｜long=31-180天｜structural=>180天
  medium 是主視野。long/structural 屬「結構脈絡」，用來定位當前判斷處在大週期何處，
  不應與短窗訊號當成互相矛盾。

【權重說明】weight 為來源可信度（0-1）。低權重證據（<0.5）不足以單獨推翻
  高權重證據（>0.8）；若要如此主張，必須說明該高權重來源在此情境下為何不適用。"""

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


def _format_evidence_list(evidences: list[Evidence]) -> str:
    lines = []
    for e in evidences:
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


def build_step_a_prompt(coin: str, question: str, evidences: list[Evidence], coin2: str | None = None) -> str:
    coin_note = (
        f"本題涉及兩個幣種：{coin} 與 {coin2}。每筆證據都已標註 coin 欄位，"
        f"請在每個 fact 中一併填入該事實所屬的幣種（coin 欄位），若證據同時適用兩者可自行判斷歸類。"
        if coin2
        else ""
    )
    return f"""題目：{question}
幣種：{coin}{f'／{coin2}' if coin2 else ''}
{coin_note}

{EVIDENCE_LIST_LEGEND}

以下是本次蒐集到的所有證據（含 evidence id 與 coin 欄位）：
{_format_evidence_list(evidences)}

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
    coin: str, question: str, evidences: list[Evidence], facts: list[dict], coin2: str | None = None
) -> str:
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

{EVIDENCE_LIST_LEGEND}

原始證據清單（供比對細節）：
{_format_evidence_list(evidences)}

請執行【交叉驗證層】分析，輸出**三段**：
1. consistent_signals：多個獨立來源指向同一方向的一致訊號。
   若多筆證據其實引用同一篇文章或同一原始資料，請註明「非獨立來源」以避免重複計算可信度。
2. contradictions：**真正的矛盾訊號**。只有「同一 horizon 帶內」、或「同屬當前訊號三帶
   （spot/short/medium）之間」的方向衝突才算矛盾。**不同尺度的落差不是矛盾**（見時間尺度說明）。
3. structural_context：當前訊號（spot/short/medium）與結構脈絡（long/structural）之間的
   方向差異，一律寫在這裡而非 contradictions，並以「位置關係」措辭描述。
   例：「兩週情緒轉強，但價格仍處 5 年分佈第 88 百分位，屬高位反彈而非底部啟動」。

另外輸出 direction_matrix：各 source_type 對市場方向的表態。
  - direction 只能是 1（看多）、0（中性）、-1（看空）三個整數之一，不可填小數或文字。
  - 只針對 horizon 為 spot/short/medium（當前訊號三帶）的證據表態；
    若某 source_type 在這三帶內無證據，該類別直接省略不列。
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

請執行【推論層】分析：根據以上事實與交叉驗證結果，提出 1-3 個市場狀態假設。
每個假設都必須同時列出支持它的 evidence id 與反對/削弱它的 evidence id（若真的沒有反對證據可留空陣列，但不可省略欄位）。

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
) -> str:
    """推論層 Step C1：正方分析師，只准建構最有利的論證。"""
    framing = _resolve_bull_framing(question_type, coin, coin2)
    return f"""題目：{question}
幣種：{coin}{f'／{coin2}' if coin2 else ''}

你現在的角色是【正方分析師】。{framing}

事實層：
{json.dumps(facts, ensure_ascii=False, indent=2)}

交叉驗證層：
{json.dumps(cross_validation, ensure_ascii=False, indent=2)}

規則：
1. 只能使用上面提供的事實與證據，不可引入未出現的資訊或杜撰數據。
2. 你的論證必須誠實：若證據其實薄弱、樣本數少、或有明顯反例，要在論證中承認，不要誇大成過度肯定的語氣。
3. 必須引用 evidence id 支撐你的論點。

請只輸出以下 JSON 格式：
{{
  "argument": "正方完整論證（可以是一段完整的話，需引用具體事實）",
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

先前的辯論紀錄：
{format_debate_transcript(rounds)}

你的任務是【回應反方對你的批評】並產出修正後的論證：
1. 逐項回應反方的批評。批評成立的部分要誠實承認並修正你的論證，不要硬拗。
2. 批評不成立的部分，要具體說明為什麼（引用事實或 evidence id），不可只說「反方誤解了」。
3. 輸出你這一輪修正後的**完整**論證，不要只寫增補的片段，也不要原文照抄上一輪。

規則：
1. 只能使用上面提供的事實與證據，不可引入未出現的資訊或杜撰數據。
2. 必須引用 evidence id 支撐你的論點。

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
{transcript_section}
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

請只輸出以下 JSON 格式：
{{
  "critique": "對正方論證的具體批評",
  "argument": "反方完整論證（可以是一段完整的話，需引用具體事實）",
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
1. 你必須明確評估反方的批評是否成立。若成立，market_judgment 與 confidence
   都要據此下修，並把該批評寫進 limitations；若不成立，要說明為何不採納。
   不可略過批評直接採信正方。
2. 若有多輪，後續輪次的論證已經過反駁與修正，應比第一輪的初始版本更有參考價值；
   但若某一方在後續輪次只是重複或迴避批評，這件事本身就是該方論證薄弱的證據。
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

另外輸出 debate_adjustment：你對「這份分析報告本身」的信心調整，範圍 -15 到 +5 的整數。
這不是對市場的看多看空，而是「經過這場辯論，我對自己這個結論的把握變高還是變低」。
範圍不對稱是刻意的：辯論若揭露了實質漏洞，應大幅下修（可到 -15）；若只是確認了原有判斷，
最多小幅上調（+5 為上限）。必須填寫 debate_adjustment_reason 說明理由，未填理由則視為 0。

請只輸出以下 JSON 格式：
{{
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

"""四步推理鏈的 prompt 模板與題型分支。

Stage 1 先定義資料結構與題型判斷邏輯；實際 prompt 文案將於 Stage 3
搭配 Bedrock 呼叫一併調校。
"""

from __future__ import annotations

from agent.schemas import QuestionType

QUESTION_TYPE_KEYWORDS: dict[QuestionType, list[str]] = {
    "comparison": ["比較", "相較", "對比", "vs", "與.*相比"],
    "hypothesis_test": ["市場上有聲音認為", "是否", "驗證", "支持與反對", "正確嗎"],
    "multi_source": ["整體市場", "整合", "市場狀態", "市場表現"],
}


def classify_question_type(question: str) -> QuestionType:
    """依關鍵字粗略判斷題型；三種題型的推理骨架皆為事實→交叉驗證→推論→結論，
    差異主要在 Step C/D 的框架（比較兩幣種 / 驗證特定陳述 / 綜合市場狀態）。
    """
    import re

    for qtype, keywords in QUESTION_TYPE_KEYWORDS.items():
        for kw in keywords:
            if re.search(kw, question):
                return qtype
    return "multi_source"


SYSTEM_PROMPT = """你是 HOYA BIT 加密市場分析 AI Agent 的推理引擎。
你的任務是根據提供的多來源證據，進行有層次的分析：
事實層 → 交叉驗證層 → 推論層 → 結論層。
規則：
1. 每個事實陳述必須標註對應的 evidence id（格式如 ev-001）。
2. 明確指出來源之間一致或矛盾的訊號。
3. 結論必須包含信心等級（高/中/低）、已知限制、可能推翻結論的條件。
4. 不得捏造證據中不存在的數據或事件。
5. 這不是價格預測系統，避免給出具體買賣建議。
"""

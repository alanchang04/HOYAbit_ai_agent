"""可開關對照組：未過濾證據直接一次 LLM 呼叫，作為信任提煉流水線的對比基準。"""

from __future__ import annotations

from agent.reasoning.llm_client import LLMClient
from agent.schemas import Evidence

BASELINE_SYSTEM_PROMPT = (
    "你是加密貨幣市場分析師。以下提供一組未經處理的原始證據資料，"
    "請直接基於這些資料產出對題目的分析結論。"
    "嚴禁提供任何投資建議（不得出現 buy/sell/hold/進場價/停損點/停利等語彙）。"
    "僅以客觀分析態度呈現你的觀察。以繁體中文回答。"
)


def run_baseline(
    question: str,
    evidences: list[Evidence],
    llm_client: LLMClient,
    coin: str = "",
    coin2: str | None = None,
) -> dict:
    """執行未過濾對照組分析。成功回傳 {"analysis": str, "caveat": str}，失敗回傳 {"error": str}。"""
    try:
        # 組合全量證據為純文字（不帶權重）
        evidence_text = "\n".join(
            f"[{ev.id}] {ev.source}: {ev.content_reference}"
            for ev in evidences
        )
        coin_label = f"{coin} vs {coin2}" if coin2 else coin
        user_prompt = (
            f"題目：{question}\n"
            f"分析幣種：{coin_label}\n\n"
            f"以下為全部原始證據（{len(evidences)} 筆）：\n{evidence_text}\n\n"
            f"請直接給出你的分析結論。"
        )

        analysis = llm_client.converse(BASELINE_SYSTEM_PROMPT, user_prompt)

        return {
            "analysis": analysis,
            "caveat": "此為未過濾對照組輸出：未做信源加權/雜訊過濾/證據回溯",
        }
    except Exception as exc:
        return {"error": f"baseline 執行失敗: {exc}"}


def run_baseline_dry_run(question: str, coin: str = "", coin2: str | None = None) -> dict:
    """dry-run 模式下的 baseline 假資料輸出。"""
    coin_label = f"{coin} vs {coin2}" if coin2 else coin
    return {
        "analysis": (
            f"（dry-run 假資料）針對「{question}」，{coin_label} 的未過濾對照組分析結論。"
            "此文案僅為版面驗證用途。"
        ),
        "caveat": "此為未過濾對照組輸出：未做信源加權/雜訊過濾/證據回溯",
    }

"""LLM 呼叫的共用介面與 backend 工廠。

競賽硬性規定推理僅能用 Bedrock 上的模型；`LLM_BACKEND=gemini` 是開發階段
（尚未取得 Bedrock 存取權限時）用來暫代開發/調 prompt 的後端，正式執行或
繳交前必須切回 `LLM_BACKEND=bedrock`。兩個 backend 實作同一個窄介面，
`reasoning/pipeline.py` 完全不需要知道底層是哪個模型。
"""

from __future__ import annotations

from typing import Protocol

from agent.config import Settings


class LLMClient(Protocol):
    def converse(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str: ...


def build_llm_client(settings: Settings) -> LLMClient:
    backend = settings.llm_backend.lower()
    if backend == "bedrock":
        from agent.reasoning.bedrock_client import BedrockClient

        return BedrockClient(settings)
    if backend == "gemini":
        from agent.reasoning.gemini_client import GeminiClient

        return GeminiClient(settings)
    raise ValueError(f"未知的 LLM_BACKEND: {settings.llm_backend}（合法值：bedrock, gemini）")

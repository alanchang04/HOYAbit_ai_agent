"""Google Gemini 呼叫封裝（僅供開發階段暫代 Bedrock，正式比賽不得使用）。

介面與 `bedrock_client.BedrockClient` 一致（`converse()`），
讓 `reasoning/pipeline.py` 可以無痛切換兩者。使用官方新版 `google-genai` SDK
（舊版 `google-generativeai` 已於官方公告停止維護）。
"""

from __future__ import annotations

import time

from google import genai
from google.genai import types

from agent.config import Settings


class GeminiClientError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, settings: Settings, max_retries: int = 3, base_backoff_seconds: float = 1.5):
        if not settings.gemini_api_key:
            raise GeminiClientError(
                "未設定 GEMINI_API_KEY。這是開發階段暫代用的後端，正式比賽必須改用 Bedrock（LLM_BACKEND=bedrock）。"
            )
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model_id = settings.gemini_model_id
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds

    def converse(self, system_prompt: str, user_prompt: str, max_tokens: int = 2048) -> str:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model_id,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        max_output_tokens=max_tokens,
                        temperature=0.2,
                        # Gemini 2.5 系列預設開啟 thinking，thinking token 會跟輸出 token
                        # 共用 max_output_tokens 額度；運氣不好時 thinking 會把額度耗盡，
                        # 讓 response.text 變成空字串。這裡關閉 thinking 確保額度全部用在
                        # 我們要的 JSON 輸出上（此為 Gemini 特有行為，Bedrock/Claude 無此問題）。
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                if not response.text:
                    raise GeminiClientError(f"模型回應為空（finish_reason={response.candidates[0].finish_reason if response.candidates else '未知'}）")
                return response.text
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(self.base_backoff_seconds * (2 ** (attempt - 1)))
        raise GeminiClientError(f"Gemini 呼叫失敗，已重試 {self.max_retries} 次: {last_exc}")

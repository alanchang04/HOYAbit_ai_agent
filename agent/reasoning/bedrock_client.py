"""AWS Bedrock Converse API 呼叫封裝（含 exponential backoff retry）。

Stage 1 僅提供骨架；真實呼叫邏輯將於 Stage 3 補上並用
`scripts/check_bedrock.py` 驗證後再整合進推理鏈。
"""

from __future__ import annotations

import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from agent.config import Settings


class BedrockClientError(RuntimeError):
    pass


class BedrockClient:
    def __init__(self, settings: Settings, max_retries: int = 3, base_backoff_seconds: float = 1.5):
        self.settings = settings
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self._client = None
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client("bedrock-runtime", region_name=self.settings.aws_region)
        return self._client

    def converse(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        """呼叫 Bedrock Converse API，失敗時以 exponential backoff 重試最多 max_retries 次。

        真實 Bedrock 驗證時實測發現：辯論步驟（尤其第 2 輪反駁，要求輸出完整
        修正後論證）在 max_tokens=2048 時會被截斷，導致 JSON 沒有正確收尾。
        stopReason=="max_tokens" 時直接視為失敗、不嘗試解析——截斷的 JSON
        parse 出來的錯誤訊息（如 "Unterminated string"）不會告訴你真正原因
        是輸出被砍斷，這裡提早攔截給出明確診斷，下次再遇到能立刻定位。
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.converse(
                    modelId=self.settings.bedrock_model_id,
                    system=[{"text": system_prompt}],
                    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                    inferenceConfig={"maxTokens": max_tokens, "temperature": 0.2},
                )
                # 累計 token usage
                usage = response.get("usage", {})
                self.usage["input_tokens"] += usage.get("inputTokens", 0)
                self.usage["output_tokens"] += usage.get("outputTokens", 0)
                self.usage["calls"] += 1
                text = response["output"]["message"]["content"][0]["text"]
                stop_reason = response.get("stopReason")
                if not text:
                    last_exc = BedrockClientError(
                        f"回應內容為空（stopReason={stop_reason}），可能被 guardrail 攔截或模型拒答"
                    )
                    if attempt < self.max_retries:
                        time.sleep(self.base_backoff_seconds * (2 ** (attempt - 1)))
                        continue
                    raise last_exc
                if stop_reason == "max_tokens":
                    last_exc = BedrockClientError(
                        f"回應被 max_tokens={max_tokens} 截斷（stopReason=max_tokens），"
                        f"輸出內容不完整無法視為有效回應，需提高 max_tokens 或縮短 prompt"
                    )
                    if attempt < self.max_retries:
                        time.sleep(self.base_backoff_seconds * (2 ** (attempt - 1)))
                        continue
                    raise last_exc
                return text
            except (ClientError, BotoCoreError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(self.base_backoff_seconds * (2 ** (attempt - 1)))
        raise BedrockClientError(f"Bedrock 呼叫失敗，已重試 {self.max_retries} 次: {last_exc}")

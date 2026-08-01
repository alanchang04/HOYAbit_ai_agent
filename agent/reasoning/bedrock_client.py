"""AWS Bedrock Converse API 呼叫封裝（含 exponential backoff retry 與時間預算控制）。

## 為什麼要自己指定 timeout 與關掉 botocore 重試（2026-08-01）

一次 BTC 多源整合實跑花了 1189 秒（硬性上限 900 秒），其中 `step_a_facts`
**單一次呼叫卡了 1020 秒**——同一題其他跑都在 33s 上下。事後查證的完整因果：

1. `boto3.client()` 不傳 `Config` 時，`read_timeout` 預設 **60 秒**。
   而 27 次真實呼叫的樣本裡，最慢的 `step_d_conclusion` 是 **56.5 秒**
   （要吃完整辯論逐字稿，prompt 達 18k 字）。**只剩 6% 餘裕**，
   模型稍微慢一點就會拋 `ReadTimeoutError`。
2. botocore 預設 `retries={'mode': 'legacy'}`，`__default__.max_attempts = 5`，
   而 `general_socket_errors` 政策對應的 `EXCEPTION_MAP` **包含 `ReadTimeoutError`**
   ——所以單一次 `client.converse()` 內部最多重打 5 次，各等 60 秒。
3. `ReadTimeoutError` 是 `BotoCoreError` 的子類，會被本檔外層的
   `except (ClientError, BotoCoreError)` 接住再重試 3 次。
4. 兩層相乘 = 最多 15 次嘗試 × 60 秒 ≈ 900 秒＋backoff，與實測的 1020 秒相符。
   而且**全程沒有留下任何一行 log**，事後只能靠側錄的耗時反推。

三個對策，缺一不可：

- **read_timeout 拉到 150s**（實測最大值的 2.7 倍），連線逾時收到 10s。
- **關掉 botocore 的重試**（`max_attempts=0`），重試政策只留應用層這一份。
  兩層各自重試會相乘，而且底層那層無法記錄、無法感知總時間預算。
  代價是 throttling 的重試也只剩應用層的 3 次——可接受，因為現在看得見。
- **每次重試都要記錄**（`on_retry`），並在**每次嘗試前檢查總時間預算**（`deadline`）。
  預算不足時直接失敗，把剩下的時間留給下游步驟，而不是把整跑拖過 15 分鐘。
"""

from __future__ import annotations

import time
from collections.abc import Callable

import boto3
from botocore.config import Config
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
        # 由 orchestrator 設定：`time.monotonic()` 的絕對值，代表整跑的硬性截止時間。
        # None 代表不限時（測試與 scripts/ 的單次驗證皆如此）。
        self.deadline: float | None = None
        # 由 orchestrator 設定：`on_retry(detail: str)`，讓重試在 execution_log 留下痕跡。
        # 上面那次 1020 秒的卡頓之所以難查，正是因為重試完全沒有紀錄。
        self.on_retry: Callable[[str], None] | None = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.settings.aws_region,
                config=Config(
                    read_timeout=self.settings.llm_read_timeout_seconds,
                    connect_timeout=self.settings.llm_connect_timeout_seconds,
                    # 重試政策只留應用層一份，理由見檔頭。
                    # botocore 的 `max_attempts` 算的是「重試次數」不是「總嘗試次數」，
                    # 0 才是完全不重試（解析後為 total_max_attempts=1）。
                    retries={"mode": "standard", "max_attempts": 0},
                ),
            )
        return self._client

    def _remaining_seconds(self) -> float | None:
        return None if self.deadline is None else self.deadline - time.monotonic()

    def _report_retry(self, detail: str) -> None:
        if self.on_retry is not None:
            try:
                self.on_retry(detail)
            except Exception:  # noqa: BLE001 — 記錄失敗不該讓推理鏈中斷
                pass

    def converse(self, system_prompt: str, user_prompt: str, max_tokens: int = 8192) -> str:
        """呼叫 Bedrock Converse API，失敗時以 exponential backoff 重試最多 max_retries 次。

        真實 Bedrock 驗證時實測發現：辯論步驟（尤其第 2 輪反駁，要求輸出完整
        修正後論證）在 max_tokens=2048 時會被截斷，導致 JSON 沒有正確收尾。
        stopReason=="max_tokens" 時直接視為失敗、不嘗試解析——截斷的 JSON
        parse 出來的錯誤訊息（如 "Unterminated string"）不會告訴你真正原因
        是輸出被砍斷，這裡提早攔截給出明確診斷，下次再遇到能立刻定位。
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            remaining = self._remaining_seconds()
            if remaining is not None and remaining <= 0:
                raise BedrockClientError(
                    f"已超過整跑時間預算（剩餘 {remaining:.1f}s），第 {attempt} 次嘗試前中止"
                )
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
                    if self._sleep_before_retry(attempt, last_exc):
                        continue
                    raise last_exc
                if stop_reason == "max_tokens":
                    last_exc = BedrockClientError(
                        f"回應被 max_tokens={max_tokens} 截斷（stopReason=max_tokens），"
                        f"輸出內容不完整無法視為有效回應，需提高 max_tokens 或縮短 prompt"
                    )
                    if self._sleep_before_retry(attempt, last_exc):
                        continue
                    raise last_exc
                return text
            except (ClientError, BotoCoreError) as exc:
                last_exc = exc
                self._sleep_before_retry(attempt, exc)
        raise BedrockClientError(f"Bedrock 呼叫失敗，已重試 {self.max_retries} 次: {last_exc}")

    def _sleep_before_retry(self, attempt: int, exc: Exception) -> bool:
        """決定要不要再試一次；要的話先記錄並睡完 backoff。回傳是否應該重試。

        時間預算不足時**不再重試**——把剩下的時間留給下游步驟，比在這裡把整跑拖過
        15 分鐘硬限制好。依命題文件執行限制第 1 條，超時後的產出主辦方可不採計。
        """
        if attempt >= self.max_retries:
            return False
        backoff = self.base_backoff_seconds * (2 ** (attempt - 1))
        remaining = self._remaining_seconds()
        if remaining is not None and remaining <= backoff:
            self._report_retry(
                f"第 {attempt} 次嘗試失敗（{type(exc).__name__}），"
                f"剩餘預算 {remaining:.1f}s 不足以再試一次，放棄重試"
            )
            return False
        self._report_retry(
            f"第 {attempt}/{self.max_retries} 次嘗試失敗（{type(exc).__name__}: {str(exc)[:120]}），"
            f"{backoff:.1f}s 後重試"
            + (f"，剩餘預算 {remaining:.0f}s" if remaining is not None else "")
        )
        time.sleep(backoff)
        return True

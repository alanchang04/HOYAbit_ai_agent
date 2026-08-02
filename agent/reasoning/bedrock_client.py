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
- **單次呼叫的 read timeout 依剩餘預算收緊**。只擋「不啟動」是不夠的：
  在截止前 1 秒發出的請求，照樣能跑滿 150 秒的 read timeout 才回來。
  timeout 取 `min(設定值, 剩餘 − 連線逾時 − 安全邊際)`。
  botocore 的 timeout 綁在 client 上、無法逐次指定，所以依 timeout 值快取多個 client。

## ⚠️ read_timeout 不是總時長上限（2026-08-01 第二次事故）

上面那條**不足以保證不超時**。實測：一次 `step_d_conclusion` 跑了 **6756 秒**
（1 小時 53 分），而該 client 的 `read_timeout` 明明是 150 秒。

原因：`read_timeout` 量的是**兩次 socket 讀取之間的間隔**，不是整個請求的總時長。
Bedrock 的連線只要持續有資料或 keepalive 進來，計時器就一直被重置，
於是一個永遠「還在回應中」的請求可以無限期地跑下去——最後是被
`ConnectionClosedError` 中斷的，不是逾時。

**唯一可靠的總時長上限是在呼叫端強制中斷。** `converse()` 因此改成在
worker thread 中執行 API 呼叫，主執行緒用 `Future.result(timeout=...)` 等待；
逾時就放棄那個 future（背景 thread 會隨 process 結束而終止，不阻塞收尾）
並拋出 `BedrockClientError`，讓上層走既有的降級路徑。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError

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
        # botocore 的 read_timeout 綁在 client 建構時、無法逐次覆寫，
        # 因此依「有效 timeout 秒數」快取多個 client（同秒數共用同一個）。
        self._clients: dict[int, object] = {}
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
        # 由 orchestrator 設定：`time.monotonic()` 的絕對值，代表整跑的硬性截止時間。
        # None 代表不限時（測試與 scripts/ 的單次驗證皆如此）。
        self.deadline: float | None = None
        # 由 orchestrator 設定：`on_retry(detail: str)`，讓重試在 execution_log 留下痕跡。
        # 上面那次 1020 秒的卡頓之所以難查，正是因為重試完全沒有紀錄。
        self.on_retry: Callable[[str], None] | None = None
        # 逾時的呼叫不能靠 socket timeout 收（見檔頭），改由呼叫端強制中斷：
        # API 呼叫丟到 worker thread，主執行緒用 Future.result(timeout) 等。
        # daemon thread 讓被放棄的呼叫不會阻擋 process 結束。
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="bedrock-call"
        )

    # 收到截止時間前留給「解析回應＋寫報告」的安全邊際。
    SAFETY_MARGIN_SECONDS = 5

    @property
    def client(self):
        """不限時（deadline=None）時用設定值建的 client。"""
        return self._client_with_timeout(self.settings.llm_read_timeout_seconds)

    def _client_with_timeout(self, read_timeout: int):
        key = int(read_timeout)
        if key not in self._clients:
            self._clients[key] = boto3.client(
                "bedrock-runtime",
                region_name=self.settings.aws_region,
                config=Config(
                    read_timeout=key,
                    connect_timeout=self.settings.llm_connect_timeout_seconds,
                    # 重試政策只留應用層一份，理由見檔頭。
                    # botocore 的 `max_attempts` 算的是「重試次數」不是「總嘗試次數」，
                    # 0 才是完全不重試（解析後為 total_max_attempts=1）。
                    retries={"mode": "standard", "max_attempts": 0},
                ),
            )
        return self._clients[key]

    def _effective_timeout(self) -> int | None:
        """這次呼叫可用的 read timeout；剩餘預算不足以發出任何請求時回 None。

        取 `min(設定值, 剩餘 − 連線逾時 − 安全邊際)`：只要請求是在截止前發出的，
        它就不可能跑過截止時間。這是 15 分鐘上限的「不超時」那一半保證。
        """
        configured = self.settings.llm_read_timeout_seconds
        remaining = self._remaining_seconds()
        if remaining is None:
            return configured
        usable = remaining - self.settings.llm_connect_timeout_seconds - self.SAFETY_MARGIN_SECONDS
        if usable < 1:
            return None
        return max(1, min(configured, int(usable)))

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
            timeout = self._effective_timeout()
            if timeout is None:
                remaining = self._remaining_seconds()
                raise BedrockClientError(
                    f"剩餘時間預算 {remaining:.1f}s 不足以發出請求，第 {attempt} 次嘗試前中止"
                    f"（確保整跑不超過硬性上限）"
                )
            try:
                client = self._client_with_timeout(timeout)
                future: Future = self._executor.submit(
                    client.converse,
                    modelId=self.settings.bedrock_model_id,
                    system=[{"text": system_prompt}],
                    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                    inferenceConfig={"maxTokens": max_tokens, "temperature": 0.2},
                )
                try:
                    # 硬上限：socket read timeout 只管兩次讀取的間隔，攔不住一個
                    # 持續回應但永遠不結束的請求（實測 6756s）。這裡是唯一的總時長閘門。
                    response = future.result(timeout=timeout)
                except FutureTimeoutError:
                    future.cancel()  # 已在執行中的呼叫取消不掉，交給 daemon thread 自然結束
                    last_exc = BedrockClientError(
                        f"單次呼叫超過 {timeout}s 硬上限仍未回應，主動中斷"
                        f"（socket read timeout 攔不住持續回應但不結束的請求）"
                    )
                    if self._sleep_before_retry(attempt, last_exc):
                        continue
                    raise last_exc
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

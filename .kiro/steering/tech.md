# 技術棧與 LLM 抽象層約束

## 語言與執行環境

- **Python 3.11**（不使用 3.12+ 語法）
- **pydantic v2**（所有資料模型、schema 驗證）
- **標準庫優先**：能用標準庫解決就不引入第三方套件
- **非同步**：蒐集階段使用 `asyncio`（`asyncio.run()` 於 orchestrator 層呼叫）
- **型別註記**：全面使用 type hints（`from __future__ import annotations`）

## 依賴管理

- 依賴定義於 `requirements.txt`，新增依賴須有明確理由
- 禁止引入的重量級框架：LangChain、LlamaIndex、CrewAI
- 可接受的輕量依賴：`httpx`（HTTP）、`feedparser`（RSS）、`google-genai`（Gemini）、`boto3`（Bedrock）

## LLM 抽象層

### 介面（`agent/reasoning/llm_client.py`）

所有 LLM 呼叫必須經由統一介面 `LLMClient`：

```python
class LLMClient(ABC):
    async def converse(self, system_prompt: str, user_prompt: str) -> str: ...
```

- 後端切換僅靠 `.env` 中的 `LLM_BACKEND` 設定（`bedrock` / `gemini`）
- `build_llm_client(settings)` 工廠函式回傳對應實作
- 新功能不得直接呼叫 `boto3` 或 `google.genai`——必須透過 `LLMClient`
- Token 統計由各 client 內部累計（`self.usage` dict），pipeline 結束後可讀取

### 約束

- `converse()` 簽名不可變更（向後相容）
- 選用參數（如 layer/metrics）透過額外方法或 orchestrator 注入，不動介面
- 任何 LLM 呼叫失敗須隔離（try/except），不可中斷整體 pipeline

## 失敗隔離原則

- 單一 collector/層/步驟失敗 → log 紀錄 + 跳過 → `integrity_status = "DEGRADED"`
- 絕不讓新功能弄壞舊的穩定性
- degraded mode：超過 `degraded_mode_trigger_seconds` 後跳過剩餘蒐集直接推理

## 資料模型慣例（schemas.py）

- 新增欄位必須提供預設值（向後相容，既有測試零修改通過）
- 使用 `str Enum` 定義有限集合（如 `SourceType`、`LogPhase`、`LogStatus`）
- Evidence ID 格式：`ev-NNN`（三位數以上，正則 `^ev-\d{3,}$`）
- 時間戳：ISO 8601 UTC（`%Y-%m-%dT%H:%M:%SZ`）

## 測試

- 框架：`pytest`（搭配 `pytest-asyncio`）
- 測試檔案位於 `tests/` 目錄
- 命名慣例：`test_<module>.py`
- dry-run 可完整跑完全流程（不消耗 LLM 額度），用於 CI 與快速驗證
- Property-based testing：`hypothesis` 框架

## 環境變數

必要：`LLM_BACKEND`
Bedrock：`AWS_REGION`、`BEDROCK_MODEL_ID`
Gemini：`GEMINI_API_KEY`、`GEMINI_MODEL_ID`
選用 collector keys：`CRYPTOPANIC_API_KEY`、`ETHERSCAN_API_KEY`、`BSCSCAN_API_KEY`、`FRED_API_KEY`
執行控制：`HARD_DEADLINE_SECONDS`、`DEGRADED_MODE_TRIGGER_SECONDS`、`COLLECTOR_TIMEOUT_SECONDS`

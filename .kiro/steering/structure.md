# 目錄結構與擴充慣例

## 頂層目錄

```
HOYAbit_ai_agent/
├── agent/                  # 核心 Agent 邏輯（純 Python 模組）
│   ├── collectors/         # 五類資料蒐集器
│   ├── filters/            # 信任提煉過濾層（L2 內容過濾等）
│   ├── reasoning/          # LLM 推理管線（四步推理＋辯論）
│   ├── report/             # 報告產生器與 view_builder
│   ├── fixtures/           # dry-run 假資料
│   ├── config.py           # 環境設定載入
│   ├── logging_utils.py    # execution log 寫入工具
│   ├── orchestrator.py     # 主流程編排（Phase 1-4）
│   └── schemas.py          # pydantic 資料模型（全域共用）
├── webapp/                 # Flask Web UI
│   ├── app.py              # 路由與 server
│   ├── templates/          # Jinja2 HTML 模板
│   └── static/             # CSS/JS 靜態資源
├── tests/                  # pytest 測試
├── scripts/                # 工具腳本（check_llm.py 等）
├── data/                   # 本地 OHLCV CSV（命題提供）
├── output/                 # 執行輸出（report.md/evidence.json/execution_log.jsonl）
├── .kiro/                  # Kiro 配置與證據
│   ├── specs/              # 功能規格三件套
│   └── steering/           # 專案引導檔（本目錄）
├── main.py                 # CLI 入口（click）
├── Dockerfile              # 容器化部署
├── requirements.txt        # Python 依賴
└── .env                    # 環境變數（不進版控）
```

## 擴充慣例

### 新增 Collector

1. 在 `agent/collectors/` 建立新檔，繼承 `BaseCollector`
2. 實作 `async def run(self, coin: str) -> list[EvidenceDraft]`
3. 在 `orchestrator.py` 的 `build_collectors()` 中註冊
4. 對應的 dry-run fixture 加入 `agent/fixtures/dry_run_evidence.json`
5. 加入 `SOURCE_TYPES` 清單（若為新類別，須同步更新 `SourceType` enum）

### 新增過濾層（filters）

1. 在 `agent/filters/` 建立新模組
2. 輸入：`list[Evidence]`，輸出：`list[FilterDecision]`（定義於 schemas.py）
3. 純程式邏輯（零 LLM 呼叫、毫秒級完成）
4. 在 orchestrator 的 Phase 2 與 Phase 3 之間呼叫
5. 過濾結果寫入 log（含 layer 標記）

### 新增推理步驟

1. 在 `agent/reasoning/prompts.py` 定義 prompt 模板
2. 在 `agent/reasoning/pipeline.py` 加入步驟邏輯
3. 透過 `LLMClient.converse()` 呼叫——不直接碰底層 SDK
4. 失敗時拋 `ReasoningStepError`，orchestrator 會降級處理

### 新增前端頁面

1. 在 `webapp/templates/` 建立 Jinja2 模板
2. 在 `webapp/app.py` 加入路由
3. 樣式寫入 `webapp/static/style.css`（沿用既有 CSS 變數）
4. 無 JS 框架——server-side rendering 為主

### 新增 schemas

1. 在 `agent/schemas.py` 定義 pydantic BaseModel
2. **所有新欄位必須有預設值**（向後相容原則）
3. Enum 欄位使用 `str, Enum` 雙繼承以利 JSON 序列化

## 輸出檔案契約

以下三個檔案為命題交付物，格式不可變更：

| 檔案 | 說明 |
|---|---|
| `output/report.md` | Markdown 分析報告 |
| `output/evidence.json` | 證據清單 JSON array |
| `output/execution_log.jsonl` | 逐行 JSON 執行紀錄 |

新增的 `output/report_view.json` 為前端面板資料來源，不影響上述三檔。

## 命名規範

- 模組/檔案：`snake_case.py`
- 類別：`PascalCase`
- 函式/變數：`snake_case`
- 常數：`UPPER_SNAKE_CASE`
- 私有方法：`_leading_underscore`
- 測試函式：`test_<描述>()`

## Git 慣例

- `.env` 不進版控（已列入 `.gitignore`）
- `output/` 不進版控（執行產物）
- `.kiro/` 進版控（Kiro 使用證據，+10% 加分）

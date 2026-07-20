# Tasks — 全專案升級：信任提煉流水線與 Execution Logs 可視化

> 對應 `requirements.md`（R1–R11）與 `design.md`。
> 執行慣例：每個 task 完成即跑 `pytest -q` 確認 41+ 測試全綠再進下一個；
> 需要消耗 LLM 額度的驗證一律排在最後、優先用 `--dry-run`。
> 標記 `[BLOCKED: bedrock]` 的 task 等 Bedrock 開通後才執行。

## Phase 0 — Kiro 證據與 bug 修復（無依賴，先做）

- [x] 0.1 建立 `.kiro/steering/` 三檔（product.md：命題目標與合規紅線／tech.md：技術棧與
      LLM 抽象層約束／structure.md：目錄結構與擴充慣例）＿R11-2
- [x] 0.2 設定 agent hook：儲存 `agent/**/*.py` 或 `tests/**/*.py` 時自動執行 `pytest -q`＿R11-3
- [x] 0.3 修復 news 比對：`coin_map.py` 匯出 `FULL_NAME_ALIASES`；`news.py` `_matches_coin()`
      改雙軌比對（ticker 大小寫敏感＋全名小寫）；回歸測試（method/solution 不誤中；
      Ethereum/SOL 正常命中）＿R1-1, R1-2
- [x] 0.4 修復 macro 重複：`collect_all()` macro 只建一次 task；更新比較題測試斷言
      「macro 證據無重複」＿R1-3

## Phase 1 — Schema 與 log 地基（向後相容）

- [x] 1.1 `schemas.py` 新增：`PipelineLayer`、`FilterVerdict`、`FilterDecision`、`RunMetrics`；
      `EvidenceDraft` 加 `source_weight`/`weight_reason`/`rag_verified`/`rag_support`；
      `LogEntry` 加 `layer`/`metrics`（全預設值）＿R3-1~3
- [x] 1.2 `logging_utils.py` `log()` 接受選用 `layer`/`metrics`；驗證既有測試零修改通過＿R3-4, R3-5
- [x] 1.3 schema 單元測試：新欄位預設值、FilterDecision/RunMetrics 驗證＿R3

## Phase 2 — 流水線指標與過濾（純本地，零 LLM 成本）

- [x] 2.1 `agent/filters/source_weights.py`：L1 靜態權重表＋orchestrator 於證據化後統一補權重
      ＋L1 彙總 log；單元測試（查表規則）＿R4-1
- [x] 2.2 `agent/filters/content.py`：PR 英文詞典降權＋模板 Jaccard 相似度（≥0.8 標非獨立）；
      FilterDecision 逐筆＋彙總 log；F9 佔位（enabled:false）；單元測試＿R4-2
- [x] 2.3 `pipeline.py`：Step A 後補 L3 metrics（input/kept/removed/removal_rate）、
      Step B 後補 L4 metrics＿R4-3, R4-4
- [x] 2.4 `pipeline.py`：L5 數值信心公式（base＋權威加成−矛盾−缺口，夾 5–95），
      分項寫 log；單元測試（手算樣本）＿R4-5
- [x] 2.5 兩個 LLM client 累計 usage；orchestrator 讀取 → RunMetrics.total_tokens；
      FakeLLMClient 補假 usage 測試＿R4-6
- [x] 2.6 `agent/collectors/relative.py`：雙幣相對指標（相關係數/beta/最大回撤/相對強弱
      90 日位置），比較題型時 orchestrator 呼叫，失敗隔離；數學單元測試＿R2-1, R2-4
- [x] 2.7 macro F&G `limit=30` 百分位；news 命中則數量化證據；測試＿R2-2, R2-3

## Phase 3 — view_builder 與 dry-run

- [x] 3.1 `agent/report/view_builder.py`：組 `report_view.json`（schema_version 1.0，
      指紋映射 F1..Fn、log_events_by_layer、confidence_breakdown）；組裝失敗只記 log
      不影響三個命題交付檔＿R5-1~5
- [x] 3.2 dry-run fixtures 擴充（權重/假 FilterDecision/假 usage/假 baseline 文案）；
      dry-run 端到端測試斷言 report_view.json 全欄位非空＿R8
- [x] 3.3 degraded 整合：任一層跳過 → integrity_status=DEGRADED＋view 註明；測試＿R4-7

## Phase 4 — 前端 Stage 1（MVP）

- [x] 4.1 result.html 分頁化：報告｜執行時間線｜Raw Log；header 摘要列（讀 RunMetrics）＿R6-1~3
- [x] 4.2 app.py 傳入 log entries 與 view model；dry-run 表單路徑目視驗收＿R6-4

## Phase 5 — 前端 Stage 2（完整四面板）

- [x] 5.1 `agent/reasoning/baseline.py`：可開關對照組（--with-baseline／表單 checkbox，
      同一 LLMClient，prompt 禁投資建議，失敗隔離）＿R7-2
- [x] 5.2 view.html 四面板版面（`/view/{run_id}` 路由）；面板③逐層 `<details>` 展開 log 事件；
      缺資料誠實顯示＿R7-1, R7-3, R7-4
- [x] 5.3 合規檢查：全部面板文案無投資建議語彙；INTACT=分析完整性；效能實測新增耗時
      （不含 baseline）<2 秒＿R9

## Phase 6 — 最終驗證 [BLOCKED: bedrock]

- [-] 6.1 Bedrock 煙測（sts → check_llm.py → 必要時 inference profile／max_tokens 4096／
      stopReason 檢查）＿R10-2
- [~] 6.2 Bedrock 3 題型端到端＋四面板／usage 核對；Gemini 額度允許時先預演一次＿R10-2
- [~] 6.3 簡報素材：Kiro 工作流截圖＋AgentCore 取捨說明段落＿R11-4

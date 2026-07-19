# Requirements — 全專案升級：信任提煉流水線與 Execution Logs 可視化

> Kiro spec：`trust-refinement-upgrade`
> 本規格取代 `UPGRADE_SPEC_execution_logs.md`（v2）成為可執行版本；v2 保留作背景參考。
> 完整審計依據見 `AUDIT.md`（2026-07-18，逐檔原始碼盤點）。

## Introduction

現有系統已能完成「五類蒐集 → 四步推理（含正反方辯論）→ 可回溯報告」，但 execution log
只是扁平的工具呼叫紀錄，無法展示「資料如何被信任提煉」。本升級把 log 升級為分層事件流、
新增可視化四面板，並一併修復兩個已知 bug、補上比較題型的量化指標缺口、
註記 Bedrock 切換（最後才測試）、建立 Kiro 使用證據（對應 +10% 加分）。

## 現況盤點（逐檔驗證，2026-07-19）

### 已有（實證可運作）
| 能力 | 位置 | 驗證方式 |
|---|---|---|
| execution_log.jsonl（ts/phase/action/detail/status，append-only，含子來源失敗） | `agent/logging_utils.py` | 41 tests＋真實執行 |
| evidence.json 完整 schema（coin/source/source_url/fetched_at/content_reference/related_claim/source_type）＋報告引用強制檢查 | `agent/schemas.py`、`agent/report/builder.py` | tests |
| 四步推理＋辯論＋fallback＋幻覺 id 過濾＋失敗降級報告 | `agent/reasoning/pipeline.py` | 3 題型真實驗證（Gemini） |
| degraded mode（超時跳過蒐集） | `agent/orchestrator.py` | 單元測試 |
| CLI／--dry-run／Web UI（報告顯示＋三檔下載）／Docker | `main.py`、`webapp/`、`Dockerfile` | 實測 |
| LLM 抽象層（bedrock/gemini 以 .env 切換） | `agent/reasoning/llm_client.py` | Gemini 實測；Bedrock 僅程式碼就緒 |
| 單幣技術指標（SMA/RSI/波動率/量能，純本地） | `agent/collectors/price.py` | tests＋實測 |
| 比較題型雙幣蒐集＋幣種自動偵測 | `agent/orchestrator.py`、`coin_map.py` | 實測（BTC vs ETH） |

### 沒有（本規格要補的缺口）
| 缺口 | 影響 |
|---|---|
| log 無 layer/metrics 欄位；無信源權重；無過濾判定與剔除率；無數值信心；無 token 統計 | 四面板無資料可畫 |
| 無 `report_view.json`／view_builder；前端只有報告全文＋下載連結，無時間線/四面板/Raw Log 顯示 | execution log 有記但看不見 |
| 無 L2 內容層過濾（PR 話術/模板相似度）；無未過濾基準對照組 | 「清理雜訊」只有事實層隱性做，不可展示 |
| 無雙幣相對指標（相關係數/beta/最大回撤/相對強弱）；F&G 只抓當日值；新聞命中則數未量化 | 比較題缺唯一可量化共同尺度 |
| **bug**：`news.py` `_matches_coin()` 短別名子字串誤判（"eth"∈"method"、"sol"∈"solution"） | 污染 ETH/SOL 新聞證據 |
| **bug**：比較題型 macro collector 跑兩次產生重複證據 | 傷「來源獨立性」評分 |
| Bedrock 從未實際呼叫成功（帳號未開通） | 僅註記，最後測試（R10） |
| 無 `.kiro/` artifacts（specs/steering/hooks） | +10% 加分無證據 |

---

## Requirements

### R1 已知 bug 修復
**User Story**：作為評審抽查者，我希望證據清單不含無關文章與重複項目，以確認來源正確且獨立。

驗收條件：
1. WHEN news collector 過濾新聞 THE SYSTEM SHALL 使用與 `coin_map.detect_coins_in_text()` 一致的比對規則（ticker 大小寫敏感、全名別名大小寫不敏感），不得以小寫短別名做子字串比對
2. WHEN 標題含 "method"/"synthetic"/"solution"/"console" 等一般英文單字 THE SYSTEM SHALL 不將其誤判為 ETH/SOL 相關新聞（回歸測試覆蓋）
3. WHEN 執行比較題型（雙幣種） THE SYSTEM SHALL 僅執行 macro collector 一次，evidence.json 中不得出現內容相同的重複 macro 證據（回歸測試覆蓋）

### R2 比較題量化指標與便宜升級
**User Story**：作為報告讀者，我希望比較題有可量化的共同尺度證據，而非只有敘事對比。

驗收條件：
1. WHEN 比較題型執行 THE SYSTEM SHALL 從兩份本地 CSV 計算雙幣相對指標（90 日相關係數、beta、各自最大回撤、相對強弱比值之 90 日位置）並輸出為 price 類證據（零外部 API）
2. WHEN macro collector 抓取 Fear & Greed THE SYSTEM SHALL 以 `limit=30` 取近 30 日資料，證據內容含當前值與 30 日百分位
3. WHEN news collector 完成過濾 THE SYSTEM SHALL 額外輸出一筆量化證據：該幣種於各 RSS 來源的命中則數（市場關注度代理指標）
4. WHEN 上述任一計算因資料不足失敗 THE SYSTEM SHALL 隔離失敗（記 log、跳過該證據），不中斷流程

### R3 Schema 與 execution log 分層擴充
**User Story**：作為前端開發者，我需要 log 與證據帶有分層/權重/指標欄位，才能組出四面板。

驗收條件：
1. `EvidenceDraft` SHALL 新增 `source_weight: float = 0.5`、`weight_reason: str = ""`、`rag_verified: bool | None = None`、`rag_support: str = ""`（後兩者為同伴 RAG 介面，本規格只定義不實作）
2. `LogEntry` SHALL 新增 `layer: PipelineLayer | None = None` 與 `metrics: dict = {}`；`PipelineLayer` SHALL 定義 L1_source/L2_content/L3_fact/L4_cross/L5_conclusion
3. SHALL 新增 `FilterDecision`（evidence_id/check_code/verdict[kept|downweighted|removed]/reason/weight_before/weight_after）與 `RunMetrics`（confidence 0-100/noise_removal_rate/total_tokens/integrity_status/raw_evidence_count/kept_fact_count）
4. WHEN 既有測試以舊欄位建構物件 THE SYSTEM SHALL 因預設值而不需修改即可通過（向後相容）
5. `ExecutionLogger.log()` SHALL 接受選用參數 `layer`、`metrics`，未提供時行為與現況完全相同

### R4 信任提煉流水線 L1–L5
**User Story**：作為評審，我希望看到資料經過哪幾層處理、每層剔除了什麼、為什麼。

驗收條件：
1. **L1 信源層**：每筆證據 SHALL 依靜態權重表獲得 `source_weight`＋`weight_reason`（官方 CSV/本地指標/鏈上 RPC ≥0.7；新聞/總經 0.35–0.7；社群 <0.35），並 log 一筆彙總 metrics
2. **L2 內容層（本方實作縮減版）**：
   a. PR 話術偵測 SHALL 以英文詞典比對（"skyrocket"、"to the moon"、"guaranteed"、"once-in-a-lifetime" 等），命中即產出 `FilterDecision(downweighted)` 並下調權重，reason 註明命中詞與權重變化
   b. 模板相似度 SHALL 以純本地演算法（token 集合相似度，閾值 0.8）偵測跨來源雷同內容，標記「非獨立來源」
   c. 情緒分布（F9） SHALL 僅定義介面與 view 欄位，實作歸同伴 RAG；缺席時面板顯示「未啟用」
   d. 全部 check SHALL 為純程式（零 LLM 呼叫、毫秒級），英文語料優先
3. **L3 事實提取層**：現有 Step A SHALL 補記量化 metrics（input/kept/removed/removal_rate），`noise_removal_rate` = removed/input
4. **L4 交叉驗證層**：現有 Step B SHALL 補記 metrics（consistent/contradictions 數量）
5. **L5 結論層**：SHALL 以可解釋公式產出數值信心：`base(高75/中55/低35) + 權威源占比加成(≤+10) − 矛盾訊號×5(下限−15) − 缺失來源類別×5(下限−15)`，夾在 5–95；公式各項 SHALL 寫入 log metrics 可對帳
6. LLM client（bedrock 與 gemini） SHALL 累計 usage token 數，pipeline 結束時可讀取總量（`converse()` 簽名不變）
7. WHEN degraded mode 觸發或任一層被跳過 THE `integrity_status` SHALL 為 `DEGRADED` 並於 view 中說明原因

### R5 report_view.json 契約與 view_builder
**User Story**：作為前端，我只讀一份結構化 JSON 就能畫出全部面板。

驗收條件：
1. SHALL 新增 `agent/report/view_builder.py`，於 pipeline 結束後由 execution_log＋evidence＋ReasoningResult 組裝 `report_view.json`（`schema_version: "1.0"`）
2. view model SHALL 含四區塊：`panel1_raw_feed`（原始證據流）、`panel2_naive_baseline`（未過濾基準對照，可 `enabled:false`）、`panel3_refinement`（信任提煉流水線 L1-L5）、`panel4_report`（分析報告），欄位定義見 design.md §5
3. 證據 SHALL 依出現順序映射顯示指紋 F1..Fn；canonical id 仍為 ev-NNN
4. **面板上出現的每一個數字 SHALL 能在 execution_log.jsonl 或 evidence.json 中查到**（不允許前端自行發明數值）
5. 既有 `report.md`／`evidence.json`／`execution_log.jsonl` 輸出 SHALL 完全不變（命題交付物）

### R6 前端 Stage 1（MVP）：時間線＋Raw Log
**User Story**：作為 Demo 觀眾，我至少要能看到執行過程的時間軸與原始紀錄。

驗收條件：
1. result 頁 SHALL 增加分頁/區塊：「執行時間線」——依 ts 排序顯示每筆 log（phase 圖示、action、status 顏色、耗時、metrics 摘要）
2. result 頁 SHALL 增加「Raw Log」檢視——逐行顯示 execution_log.jsonl 原文（主辦方抽查用）
3. 頁面 header SHALL 顯示執行摘要：生成時間｜信心 N%｜雜訊剔除率 N%｜tokens（來自 RunMetrics）
4. WHEN --dry-run 執行 THE SYSTEM SHALL 同樣產出完整（假資料）view，前端開發不需消耗 LLM 額度

### R7 前端 Stage 2：完整四面板
**User Story**：作為評審，我希望一眼看懂「原始資料 → 提煉 → 報告」的全過程。

驗收條件：
1. SHALL 實作四面板版面：①原始證據流（來源+權重+指紋）②未過濾基準對照 ③信任提煉流水線（L1-L5 逐層展開，含剔除項與理由）④分析報告（結論/信心/核心事實/利好與風險證據/限制/可推翻條件/觀察重點）
2. 基準對照組 SHALL 為可開關（CLI `--with-baseline`／表單勾選；預設關閉）；啟用時以**同一個 LLMClient** 對全量未過濾證據做一次呼叫，prompt 同樣禁止投資建議；`enabled:false` 時面板顯示「本次未啟用」
3. 面板③每層 SHALL 可展開對應的 log 事件（ts/action/metrics）
4. WHEN 某類資料缺失（如 Reddit 403） THE 面板 SHALL 誠實顯示缺口，不得以假資料填充

### R8 dry-run 完整支援
驗收條件：
1. dry-run fixtures SHALL 擴充：假權重、假 FilterDecision、假 baseline 輸出、假 usage，使 `report_view.json` 每個欄位皆有值
2. 既有 dry-run 測試 SHALL 全數通過

### R9 合規與語言約束（非功能，全域適用）
1. 所有面板與 baseline 輸出 SHALL NOT 出現 buy/sell/hold/進場價/停損點等投資建議語彙；`INTACT` 語意 SHALL 為「分析完整性」
2. 過濾詞典與相似度 SHALL 以英文為第一優先（新聞/社群來源為英文）；UI 標籤繁中、證據原文保留英文引用
3. 單層失敗 SHALL 不中斷整體流程（沿用既有隔離原則）；效能上 L2 過濾 SHALL 為純本地毫秒級，整體新增耗時（不含 baseline） SHALL <2 秒

### R10 Bedrock 切換（僅註記，最後測試）
1. 本規格所有功能 SHALL 對 LLM backend 中立（僅透過 `LLMClient` 介面）
2. 最終驗證 task SHALL 標記 blocked-on-bedrock-access，內容：`check_llm.py` 煙測 → 必要時改 inference profile ID → 觀察 stopReason/截斷 → 3 題型端到端 → token 統計核對
3. WHEN Bedrock 未開通 THE 開發與驗收 SHALL 全程以 `LLM_BACKEND=gemini`＋dry-run 完成，不阻塞本規格

### R11 Kiro 使用證據（+10% 加分）
1. 本 spec 三件套 SHALL 位於 `.kiro/specs/trust-refinement-upgrade/` 並 commit 進 repo（GitHub 交付物可見）
2. SHALL 建立 `.kiro/steering/`（product.md/tech.md/structure.md：專案脈絡、合規紅線、架構約束），使 Kiro 產出遵守專案規則
3. SHALL 設定至少一個 agent hook（如：儲存 `agent/**/*.py` 時自動跑 pytest）
4. 簡報素材 SHALL 含 Kiro 工作流截圖與「評估過 AgentCore 但因單次執行/15 分鐘場景選擇自刻 orchestrator」的取捨說明

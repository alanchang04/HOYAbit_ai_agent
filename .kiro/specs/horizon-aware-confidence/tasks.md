# Implementation Plan: Horizon-Aware 推理與可解釋信心

> 對應 `requirements.md`（R1–R7）與 `design.md`（ADR-1~7、§3 詳細設計）。
> 立案日：2026-07-25。最後更新：2026-07-28（納入團隊決策①~⑥）。
> 設計已由 alanchang 拍板，**不需再徵詢方向**，
> 但遇到 §3.6.2 標註的公式鑑別度問題（Task 4.3）必須停下回報，不得自行改公式。

## 執行狀態一覽（2026-07-28）

| Phase | 內容 | 狀態 | 執行者 |
|---|---|---|---|
| Phase 0 | 分支合併與標註補齊 | ⬜ 待做 | **alanchang** |
| Phase 1 | Schema 地基 | ✅ 完成 | vic（`feat-horizon-aware-reasoning`） |
| Phase 2 | Collector 標註／缺口補齊／序列化 | ✅ 完成（2.11 除外） | vic |
| Phase 3 | Prompt 層 | ✅ 完成（3.8 除外） | vic |
| Phase 4 | 信心公式重寫 | ⬜ 待做 | — |
| Phase 5 | 報告與前端呈現 | ⬜ 待做 | — |
| Phase 6 | 語氣模板 | ⬜ 待做 | — |
| Phase 7 | 整合驗收 | ⬜ 待做 | — |
| Phase 8 | 多尺度供給與動態主視野（R7） | ⬜ 待做 | — |

> vic 的 Phase 1–3 成果在 `origin/feat-horizon-aware-reasoning`（1798 行，7 個測試檔），
> **尚未合併進 main**，Phase 0 就是要處理這件事。

## Overview

修復三個彼此扣連的結構性缺陷：資料時效斷層（R1）、時間尺度資訊遺失（R2）、
信心分數不可解釋（R3），並補上權重進辯論（R4）、語氣模板（R5）、
多尺度資料供給與動態主視野（R7）。

**Phase 1 是所有後續工作的地基**——`horizon_class` 欄位不存在時，Phase 3/4 無事可做。

## Task Dependency Graph

```
Phase 0（合併 vic 分支 + 解衝突 + 補 Ken 新來源標註）
  └─▶ Phase 1（schema 地基）✅ vic 已完成
        ├─▶ Phase 2（collector 側）✅ vic 已完成（2.11 待補）
        │       └─▶ Phase 3（prompt 側）✅ vic 已完成（3.8 待驗證）
        │               └─▶ Phase 4（信心公式重寫，需要 direction_matrix）
        │                       └─▶ Phase 5（報告與前端呈現）
        │                               └─▶ Phase 7（整合驗收）
        └─▶ Phase 8（R7 多尺度＋動態主視野）── 只依賴 Phase 1 的 schema

Phase 6（語氣模板）── 完全獨立，只依賴 Phase 5 的報告結構
```

```json
{
  "waves": [
    {"wave": 0, "phases": ["Phase 0"], "description": "合併 vic 的 Phase 1-3 成果並解衝突，所有後續工作的前提"},
    {"wave": 1, "phases": ["Phase 1"], "description": "Schema 地基（vic 已完成）"},
    {"wave": 2, "phases": ["Phase 2"], "description": "Collector 側（vic 已完成，2.11 待 alanchang 補）"},
    {"wave": 3, "phases": ["Phase 3"], "description": "Prompt 層（vic 已完成，3.8 待真實 LLM 驗證）"},
    {"wave": 4, "phases": ["Phase 4", "Phase 8"], "description": "Phase 4 信心公式依賴 Phase 3 的 direction_matrix；Phase 8 只依賴 Phase 1 schema——兩者互不依賴、可平行推進"},
    {"wave": 5, "phases": ["Phase 5"], "description": "報告與前端呈現，依賴 Phase 4 的 breakdown 結構"},
    {"wave": 6, "phases": ["Phase 6"], "description": "語氣模板，獨立功能"},
    {"wave": 7, "phases": ["Phase 7"], "description": "整合驗收，依賴全部"}
  ]
}
```

## 執行慣例

- 每個 task 完成即跑 `.venv/Scripts/python.exe -m pytest -q` 確認全綠再進下一個
- 需要真實網路的驗證（Binance klines）用 `scripts/test_collectors.py --coin BTC` 實跑
- 需要消耗 LLM 額度的驗證集中在 Phase 3.6 與 Phase 4.5，不要每個 task 都跑
- 提交訊息格式：`feat(horizon): <描述>` / `fix(confidence): <描述>`
- **不要**在同一個 commit 混入多個 Phase 的改動

---

## Tasks

### Phase 0 — 分支合併與標註補齊（alanchang，2026-07-28 決策②③）

> 這是所有後續工作的前提。vic 的 Phase 1–3 成果還在獨立分支上，
> 且他從 Ken 的新工作之前分岔，合併時會撞到一個衝突、漏掉四筆標註。

- [ ] **0.1** 合併 `origin/feat-horizon-aware-reasoning` 進主線，解 `price.py` 衝突
  - 衝突原因：Ken 在 `d8e1b15` 加 `compute_volatility_compression()`，
    vic 同時重構 `price.py` 做缺口補齊與序列摘要——**功能互補、邏輯不衝突，純文字碰撞**
  - **裁定：兩邊都留**（決策③）。共 3 個衝突區塊：
    | 位置 | HEAD（Ken） | 分支（vic） | 解法 |
    |---|---|---|---|
    | 常數區 | `VOL_COMPRESSION_WINDOW/PCTL_WINDOW` | `SERIES_WINDOW`、`BINANCE_KLINES_*`、`GAP_FILL_TRIGGER_DAYS` | 兩組都保留 |
    | 函式區 | `compute_volatility_compression()` | `_rsi14()`／`_volatility_pct()` | 三個函式都保留 |
    | 摘要輸出 | 波動壓縮描述字串 | MA 位置分離判定＋序列摘要 | 合併輸出，波動壓縮敘述併入 vic 的新格式 |
  - 合併後 `pytest -q` 必須全綠（vic 分支 + main 各自的測試都要過）
  - _Requirements: —（工程整合）_

- [ ] **0.2** 補上 Ken 新增子來源的 horizon 標註（design.md §3.2.1 對照表）
  - `price.py` 波動率壓縮 → **`structural`**（⚠ 最重要，錯標會製造假矛盾）
  - `macro.py` 供給節奏日曆 → `long`
  - `onchain.py` BTC/ETH 歷史趨勢 → `medium`（回看窗 >30 天則 `long`）
  - `derivatives.py` Coinbase 溢價 → `spot`（顯式標註，不靠預設值）
  - 同步在 `tests/test_collectors_horizon.py` 補對應斷言（該測試逐項比對 §3.2 表，
    新子來源沒進表會被漏測）
  - _Requirements: R2-2_

- [ ] **0.3** 推送合併結果並通知 vic 與 Ken（避免各自分支繼續分岔）
  - _Requirements: —（團隊協作）_

### Phase 1 — Schema 地基
> ✅ **已由 vic 完成**（commit `7b2c2bd`）。以下保留原始驗收條件供對帳。

- [ ] **1.1** 在 `agent/schemas.py` 新增 `HorizonClass` 列舉（五值）與三個常數集合
  `CURRENT_SIGNAL_HORIZONS`／`STRUCTURAL_HORIZONS`／`PRIMARY_HORIZON`
  - 依 design.md §3.1 的定義
  - _Requirements: R2-1_

- [ ] **1.2** 在 `EvidenceDraft` 新增 `window_start`／`window_end`／`horizon_class` 三欄位，
  皆給預設值（`None`／`None`／`HorizonClass.SPOT`）
  - **不加** `window_start <= window_end` 的 validator（理由見 design.md §3.1 註記）
  - _Requirements: R2-1, R2-3, R2-9_

- [ ] **1.3** 擴充 `tests/test_schemas.py`：
  - 新欄位預設值正確
  - 舊格式 JSON（無這三個欄位）可正常載入為 `Evidence`，不拋錯（R2-9 回歸）
  - `HorizonClass` 五值與兩個集合的成員關係正確
  - _Requirements: R2-1, R2-9_

- [ ] **1.4** 在 `agent/orchestrator.py` 分配 evidence id 的環節加入標註檢查：
  若 `horizon_class` 為預設 `spot` 但 `window_start`/`window_end` 有值（矛盾標註），
  或 collector 明顯應標非 spot 卻未標，寫一筆 `LogStatus.SKIPPED` 的警示 log
  - 只記 log，**不得**拋錯或過濾掉該證據（R6-1）
  - _Requirements: R2-3, R6-1_

### Phase 2 — Collector 側：標註、補齊、序列化
> ✅ **已由 vic 完成**（commit `52378bf`），惟 Ken 新增的四筆子來源標註移至 Task 0.2。
> Task 2.8 的邊界問題已由 alanchang 拍板同意，正式化為 **R1-9**（design.md §3.4.1）。

- [ ] **2.1** 依 design.md §3.2 對照表，為**所有** collector 的每筆 `EvidenceDraft`
  補上 `horizon_class`／`window_start`／`window_end`
  - 檔案：`price.py`、`onchain.py`、`news.py`、`social.py`、`macro.py`、
    `derivatives.py`、`relative.py`
  - ⚠ **最關鍵的三筆**（假矛盾主要來源）：`price` 的 MA120／波動率全歷史百分位
    標 `structural`、`derivatives` 的 CME COT 標 `long`、`relative` 標 `long`
  - _Requirements: R2-2_

- [ ] **2.2** 新增 `tests/test_collectors_horizon.py`：逐 collector 斷言產出的
  `horizon_class` 與 §3.2 對照表一致（用 dry-run／mock，不打真實 API）
  - _Requirements: R2-2_

- [ ] **2.3** 在 `agent/collectors/price.py` 實作 `_fetch_gap_klines(coin, since_date)`：
  - 端點：`GET https://api.binance.com/api/v3/klines?symbol={TICKER}USDT&interval=1d&startTime={ms}&limit=1000`
  - **必須剔除最後一筆未收盤 K 棒**（design.md §3.3）
  - 欄位映射 `[0]=openTime, [1]=open, [2]=high, [3]=low, [4]=close, [5]=volume`
  - 失敗時 `log_subsource(..., LogStatus.SKIPPED, ...)` 並回傳空 list，**不得拋錯**
  - _Requirements: R1-2, R1-3, R6-1_

- [ ] **2.4** 實作併接邏輯與 `as_of_date` 計算：
  - `gap_days <= 1` → 跳過補齊（R1-5，**用 mock 斷言零 API 呼叫**）
  - 同日重複時 **CSV 優先**（維護「共同基準」語意）
  - 補齊成功 → `as_of_date` = klines 末日；失敗 → `as_of_date` = csv_end
  - _Requirements: R1-1, R1-2, R1-5_

- [ ] **2.5** 在價格證據的 `content_reference` 加入接縫揭露文字：
  - 成功：`其中 {start} 起 {n} 日採 Binance 公開日線補齊，官方基準資料集止於 {csv_end}`
  - 失敗：`⚠ 未能補齊，資料止於 {csv_end}，距執行日 {n} 天`
  - _Requirements: R1-3, R1-4_

- [ ] **2.6** 新增 `tests/test_price_gap_fill.py`（全部用 mock，不打真實網路）：
  補齊成功／失敗／空回應／未收盤 K 棒剔除／同日 CSV 優先／無缺口零呼叫
  - _Requirements: R1-2, R1-3, R1-5_

- [ ] **2.7** 實作 `summarize_series()` 取代單點輸出（design.md §3.4）：
  - 每個指標輸出：首尾值與變化、方向判定、期間極值與發生日、現值於近 30 天分佈的百分位
  - 方向判定四態（單調上升／單調下降／震盪走高／震盪走低／橫盤），決定性計算
  - **不得**把 30 天原始數列寫進 `content_reference`（R1-7）
  - _Requirements: R1-6, R1-7_

- [ ] **2.8** 確認長歷史指標仍以官方 CSV 全歷史計算（R1-8）：
  `compute_historical_volatility_percentile()` 與 MA120 的 `full_closes`
  **不得**改用併接後的序列
  - ⚠ vic 實作時發現邊界：均線**值**用 CSV 沒問題，但「站上／跌破」的**位置判定**
    若也用 CSV 末日收盤，在 CSV 落後執行日 56 天時會判出與現實相反的結論
    （實測 BTC：MA120=72,613，CSV 末日收盤判「站上」，但 2026-07-26 現價 65,400
    其實是跌破）。他改為「均線值用 CSV、位置用補齊後現價」並揭露兩個基準日
  - ✅ **2026-07-28 alanchang 已確認同意**，正式化為 **R1-9**（design.md §3.4.1）
  - _Requirements: R1-8, R1-9_

- [ ] **2.9** 新增 `tests/test_price_series_summary.py`：四種方向判定各一例、
  30 天資料不足時的降級行為
  - _Requirements: R1-6_

- [ ] **2.10** 用 `scripts/test_collectors.py --coin BTC` 實跑一次真實補齊，
  人工確認 `as_of_date` 已推進到執行日、接縫文字正確、序列摘要可讀
  - _Requirements: R1-2, R1-4, R1-6_

### Phase 3 — Prompt 層：讓 LLM 看見尺度與權重
> ✅ **已由 vic 完成**（commit `a7582a8`），惟 Task 3.8（真實 LLM 驗證）尚未執行。
> `debate_adjustment_raw` 已在 `pipeline.py` 接住，等 Phase 4 夾值套用。

- [ ] **3.1** 改寫 `agent/reasoning/prompts.py` 的 `_format_evidence_list()`：
  加入 `weight`＋分級標籤、`horizon`、`window` 三組欄位（design.md §3.5.1 格式）
  - 分級標籤取自 `static/source_reputation.json`，**不得在程式碼寫死對照**
  - _Requirements: R2-4, R4-1_

- [ ] **3.2** 在證據清單前加入【時間尺度說明】與【權重說明】兩個固定區塊
  （design.md §3.5.1 原文）
  - _Requirements: R2-4, R4-2_

- [ ] **3.3** 在 `SYSTEM_PROMPT` 新增第 7、8 條規則（design.md §3.5.2 原文）
  - _Requirements: R2-6, R4-2_

- [ ] **3.4** 改寫 `build_step_b_prompt()` 為三段輸出＋`direction_matrix`：
  - 新增 `structural_context` 欄位與「僅同尺度才算矛盾」的約束（design.md §3.5.3）
  - `direction_matrix` 限縮 `-1|0|1` 整數、只針對當前訊號三帶表態
  - _Requirements: R2-5, R2-6, R2-7, R3-3_

- [ ] **3.5** 在 `agent/reasoning/pipeline.py` 接住 Step B 的新欄位：
  - `cross_validation` dict 新增 `structural_context` 與 `direction_matrix`
  - 兩者解析失敗時各自降級為 `[]`，**不得**中斷（R6-1）
  - `direction_matrix` 需做 sanitize：過濾非法 direction 值、過濾不存在的 evidence id
  - _Requirements: R2-5, R3-3, R3-15, R6-1_

- [ ] **3.6** 改寫 `build_step_d_prompt()` 新增 `debate_adjustment`／
  `debate_adjustment_reason` 兩個輸出欄位（design.md §3.5.4 原文，含不對稱範圍的說明）
  - 同時依 R4-4 要求裁判考量雙方引用證據的權重分佈
  - _Requirements: R3-8, R4-4_

- [ ] **3.7** 擴充 `tests/test_prompts.py`：斷言清單含 horizon/window/weight、
  說明區塊存在、Step B prompt 含三段與 direction_matrix 規格、Step D prompt 含調整欄位
  - _Requirements: R2-4, R3-3, R3-8, R4-1_

- [ ] **3.9** 確認辯論層 Step C1/C2 的 prompt 也帶到權重意識（R4-3）
  - `SYSTEM_PROMPT` 第 8 條是全域規則，但辯論 prompt 應再明確要求：
    正反方引用證據時不得把不同權重的證據當作勢均力敵
  - vic 的 Phase 3 主要處理 `_format_evidence_list` 與 Step B/D，
    **此條需合併後複查是否已涵蓋**，未涵蓋則補上
  - _Requirements: R4-3_

- [ ] **3.8** 【需 LLM 額度】用真實 Bedrock 跑一次 BTC 多源整合題，
  人工檢查 Step B 是否正確把跨尺度差異放進 `structural_context` 而非 `contradictions`
  - 這是本規格**最核心的驗證點**，若 LLM 仍把跨尺度判成矛盾，需回頭加強 §3.5.3 的約束措辭
  - _Requirements: R2-6, R2-7_

### Phase 4 — 信心公式重寫

- [ ] **4.1** 重寫 `agent/reasoning/confidence.py`，新介面
  `compute_confidence(evidences, cross_validation, debate_adjustment, debate_adjustment_reason)`
  - 保留舊的 `compute_confidence_score()` 為 deprecated wrapper 或直接移除
    （若移除，Task 4.6 必須把既有測試改寫成新公式的等價驗證，**不得刪測試**）
  - _Requirements: R3-7, R3-11, R6-4_

- [ ] **4.2** 實作 Data Confidence（design.md §3.6.1）：
  - `DATA_COMPLETENESS_THRESHOLD` 常數表放檔案頂部，六類（**含 derivatives**，修 D7）
  - 三檔評分：完整 100%／部分 60%／缺失 0%
  - 純統計，**不得**呼叫 LLM
  - _Requirements: R3-1, R3-2_

- [ ] **4.3** 實作 Signal Consensus（design.md §3.6.2）：
  - 只納入當前訊號三帶對應的 source_type
  - 公式 `100 × (1 - pstdev(dirs) / 1.0)`，樣本 < 2 時回 50
  - ⚠ **完成後必須驗算並回報**：用 §3.6.2 的三組範例與一次真實執行的 direction_matrix，
    確認分數分佈是否有鑑別度。若普遍落在 0–20 而失去鑑別度，**停下來回報 alanchang**，
    不得自行改成 `100 × |mean|` 或其他映射
  - _Requirements: R3-4, R3-5_

- [ ] **4.4** 實作 Evidence Strength（design.md §3.6.3）：
  各類平均 `source_weight` × 覆蓋度折減。**不得**引入 LLM 主觀評分
  - _Requirements: R3-6_

- [ ] **4.5** 實作組合、夾值與 breakdown（design.md §3.6.4/§3.6.5）：
  - `base = 0.4·data + 0.4·consensus + 0.2·strength`
  - `adj`：無理由強制 0（R3-10）、超界夾到 −15/+5 並 log 原始值（R3-9）
  - `final = clamp(round(base + adj), 5, 95)`
  - breakdown 完整寫入 execution_log `metrics`（`layer=L5_conclusion`）
  - **確認 `structural_context` 完全不進入任何扣分路徑**（R2-8）
  - _Requirements: R2-8, R3-9, R3-10, R3-11, R3-12, R3-14_

- [ ] **4.6** 實作「Why this confidence?」決定性生成（design.md §3.6.6 觸發表）
  - 新增 `agent/reasoning/confidence_why.py` 或放在 `confidence.py` 內
  - **不得**呼叫 LLM；同輸入必須同輸出
  - _Requirements: R3-13_

- [ ] **4.7** 改寫 `tests/test_confidence.py`（既有測試改為新公式的等價驗證，**不刪案例**）
  ＋新增 `tests/test_confidence_why.py`：
  - 六類三檔評分、derivatives 已納入（D7 回歸測試）
  - §3.6.2 三組驗算值
  - 超界夾值、無理由強制 0
  - `structural_context` 不計入矛盾懲罰（R2-8 回歸）
  - why 各觸發條件都產生對應行，且決定性
  - _Requirements: R2-8, R3-1, R3-5, R3-9, R3-10, R3-13, R6-4_

### Phase 5 — 報告與前端呈現

- [ ] **5.1** 在 `agent/report/builder.py` 第 4 節改為 Confidence Breakdown 表
  （三維分數＋權重＋Base＋Debate Adjustment＋Final）
  - _Requirements: R3-12_

- [ ] **5.2** 在報告加入「Why this confidence?」條列區塊（承 Task 4.6 的輸出）
  - _Requirements: R3-13_

- [ ] **5.3** 在報告第 3 節新增「結構脈絡（不計入矛盾）」小節，
  呈現 `structural_context`，與「矛盾訊號」明確區分
  - _Requirements: R2-7, R2-8_

- [ ] **5.4** 在執行摘要的信心行補上 Base/Adjustment 的拆解，
  並在 `agent/report/view_builder.py` 的面板④ summary 帶上新的 breakdown 欄位
  - _Requirements: R3-12_

- [ ] **5.5** 前端（`webapp/templates/view.html`／`result.html`）呈現 breakdown 表與 why 條列；
  面板①證據列表加上 horizon 標籤
  - 沿用既有 `render_longtext` filter 與 `.llm-longtext` 樣式，不新造渲染機制
  - _Requirements: R2-4, R3-12, R3-13_

- [ ] **5.6** 若 Step B 未產出 `direction_matrix`（降級路徑），
  報告需明確揭露「訊號共識以中性 50 計算」
  - _Requirements: R3-15_

- [ ] **5.7** 擴充 `tests/test_view_builder.py`／`tests/test_report_evidence_mapping.py`：
  breakdown 表欄位齊全、why 條列出現、structural_context 與 contradictions 分開呈現
  - _Requirements: R2-8, R3-12, R3-13_

### Phase 6 — 語氣模板（獨立，最後做）

- [ ] **6.1** 新增 `agent/report/tone.py`，定義 `TONE_PROFILES`
  （`professional` 預設／`plain`），內容為章節標題與導語措辭
  - **不得**模仿任何具名真實人物（R5-3）
  - _Requirements: R5-1, R5-3_

- [ ] **6.2** `main.py` 與 `webapp/app.py` 加入 `--tone` / 表單選項，
  預設 `professional`
  - _Requirements: R5-1_

- [ ] **6.3** `plain` 模式在 Step D 額外要求 `plain_summary` 欄位，
  且 prompt 必須維持與 professional 完全相同的買賣建議禁令
  - _Requirements: R5-4, R5-5_

- [ ] **6.4** 新增 `tests/test_tone.py`：同一 `ReasoningResult` 以兩種 tone 產生報告，
  斷言證據 id 引用集合、信心分數、facts/inference 內容**完全相同**（R5-2 的關鍵驗證）
  - _Requirements: R5-2_

### Phase 7 — 整合驗收

- [ ] **7.1** 全套測試 `pytest -q` 通過，且既有 269 個案例無刪除
  - _Requirements: R6-3, R6-4_

- [ ] **7.2** 【需 LLM 額度】三題型各跑一次真實 Bedrock，記錄耗時，
  確認總時長仍在 10 分鐘內（新增 Binance 呼叫預估 < 5 秒）
  - _Requirements: R6-2_

- [ ] **7.3** 人工驗收核心成效：對照修改前後同一題目的報告，確認
  (a) `contradictions` 數量下降且剩下的都是真實同尺度衝突
  (b) 辯論雙方語氣不再普遍性地吞吞吐吐
  (c) 信心分數有 breakdown 且可逐項對帳
  - _Requirements: R2-6, R2-7, R3-12_

- [ ] **7.4** 更新 `raw_data/_meta/window_policy.md`：把 §3.2 的 horizon 對照表
  併入該文件，使窗口政策與 horizon 標註成為單一事實來源
  - _Requirements: R2-2_

- [ ] **7.5** 更新 `STATUS.md`、`AUDIT.md`，並在
  `.kiro/specs/trust-refinement-upgrade/design.md` 的 L5 信心公式段落
  加註「已由 horizon-aware-confidence R3 取代」
  - _Requirements: —（文件同步）_

- [ ] **7.6** 把 requirements.md 待確認事項 #1/#2（比賽當日資料集）
  併入 `STATUS.md` 待辦第 8 項「向主辦方確認比賽當日執行環境」
  - _Requirements: —（風險管理）_

### Phase 8 — 多尺度資料供給與動態主視野（R7，2026-07-28 新增）

> 只依賴 Phase 1 的 schema，**與 Phase 4 互不依賴、可平行推進**。
> 這一 Phase 修的是原設計一個沒被發現的假設：把主視野寫死 `medium`，
> 等於假設題目永遠問「兩週」。現場若抽到「最近一年」，五年結構資料
> 會被歸成「結構脈絡」排除在共識投票外——**最該用的資料反而被降級**。

- [ ] **8.1** 在 `agent/schemas.py` 新增 `HORIZON_ORDER` 排序清單與
  `is_current_signal(h, primary)` 函式（design.md §3.1）
  - 保留 vic 已實作的 `CURRENT_SIGNAL_HORIZONS`／`STRUCTURAL_HORIZONS` 不刪除
    （primary=`medium` 時兩者結果相同，既有測試不會失敗）
  - 調整 `short` 邊界由「≤7 天」為「≤10 天」以容納「10 日」標準粒度；
    已核對**不影響任何一筆 vic 現有標註**
  - _Requirements: R7-1, R7-3_

- [ ] **8.2** 實作 `resolve_primary_horizon(question)`（design.md §3.1.1）
  - 規則式關鍵字比對，**不呼叫 LLM**；由長詞到短詞避免「一年」被「年」搶先命中
  - 回傳 `(主視野, 觸發判定的題目片段)`，片段供 R7-7 在報告揭露
  - 無命中 → 回 `(MEDIUM, "")`
  - _Requirements: R7-2_

- [ ] **8.3** 新增 `tests/test_primary_horizon.py`：
  七組關鍵字各一例、無命中的預設值、「一年」不被「年」誤搶、
  天數→帶的邊界值（1／10／30／180）
  - _Requirements: R7-1, R7-2_

- [ ] **8.4** 把 `primary_horizon` 貫穿 pipeline：
  `orchestrator` 判定後傳入 `run_reasoning()`，
  並取代 `prompts.py`／`confidence.py` 中所有寫死的「當前訊號三帶」判斷
  - _Requirements: R7-3_

- [ ] **8.5** `price.py` 補齊五檔標準粒度證據（design.md §3.2.2 表）
  - 日／10 日／季／年 四檔為新增（月已由 vic 的 `SERIES_WINDOW=30` 完成）
  - 資料來自本地 CSV，**不得**新增任何 API 呼叫
  - 各檔標註對應的 `horizon_class` 與 `window_start`/`window_end`
  - _Requirements: R7-4_

- [ ] **8.6** 其他 collector 依 R7-5「盡力而為」盤點：
  列出各 collector 實際能覆蓋的粒度，未覆蓋者確認會反映在 Data Confidence 扣分
  - **不要**為了湊滿五檔而製造假資料（news/social 本質上沒有「年」尺度）
  - _Requirements: R7-5_

- [ ] **8.7** 實作主視野無證據時的揭露（R7-6）與主視野判定依據的揭露（R7-7）
  - _Requirements: R7-6, R7-7_

- [ ] **8.8** 定義 `raw_data/` 讀取介面契約（R7-8）
  - 只定義 agent 端需要什麼格式，**不規範檔案產生流程**（那是 alanchang 的範圍）
  - 檔案缺失／格式不符 → collector 降級為僅用即時 API，不得中斷
  - _Requirements: R7-8, R6-1_

- [ ] **8.9** 新增 `tests/test_multiscale_supply.py`：
  五檔粒度都有證據產出、動態主視野下的角色推導正確
  （primary=`structural` 時 `long` 應為當前訊號而非結構脈絡）
  - _Requirements: R7-3, R7-4_

---

## Notes

### 給執行者（Sonnet）的重點提醒

0. **Phase 0 沒做完不要碰任何其他 Phase**（2026-07-28 新增）。vic 的 Phase 1–3
   成果還在 `origin/feat-horizon-aware-reasoning` 分支上未合併。在合併前動
   `agent/collectors/` 或 `agent/reasoning/prompts.py` 只會製造更多衝突。

1. **Phase 1 不做完不要跳去 Phase 3/4**——沒有 `horizon_class` 欄位，
   prompt 與信心公式都無事可做，硬做會產生要重寫的程式碼。
   （已由 vic 完成，此條保留供對帳。）

2. **Task 3.8 是本規格的成敗關鍵**。整套設計的價值在於「LLM 真的不再把跨尺度差異
   判成矛盾」。若那次真實驗證顯示 LLM 仍然誤判，優先加強 prompt 約束措辭
   （§3.5.3），而不是繼續往下做 Phase 4。

3. **Task 4.3 的公式鑑別度問題必須停下回報**，不要自作主張換公式。
   需求方明確指定了 `stdev_max = 1.0` 的線性映射，但設計階段已發現它與需求方
   舉例的期望值（65/40）落差極大（實得 17/0）。這是需要人來拍板的取捨。

4. **降級優先於正確**（R6-1）。本規格新增的每一個功能點，
   失敗時都必須讓 pipeline 繼續跑完並在報告揭露，不得中斷。
   比賽只有一次執行機會，這條的優先度高於任何功能完整性。

5. **不要動 R12 四因子公式**（`agent/filters/`）。本規格只消費 `source_weight`，
   不改變它的產生方式。該目錄另有 steering 規範 `.kiro/steering/data-trust-layer.md`。

### 團隊協作注意

- Phase 2.1 會動到**所有** collector，而 `agent/collectors/` 是 Ken 的範圍。
  開工前先 `git fetch` 確認 `origin/ken` 無未合併的 collector 改動，
  必要時先合併再動工（見 `.kiro/specs/trust-refinement-upgrade/team-division.md`）。
- Phase 2.3 的 Binance klines 補齊與 Ken 的 `pipeline/fetch_realtime_price.py`
  用途不同（他抓當下單點、這裡抓日線序列），不衝突，但完成後應告知避免重複實作。

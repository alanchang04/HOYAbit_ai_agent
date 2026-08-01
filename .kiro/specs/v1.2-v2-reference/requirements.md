# v1.2 V2 Reference — Requirements

## Goal

在不改變 v1.2 既有結論、信心公式與 15 分鐘 deadline 的前提下，加入可獨立驗證、低風險合併的 v2 參考能力：Structured Feature Extraction、Knowledge Lite 與 Evidence Relationship Graph Lite。

## Functional requirements

### R1 — Structured features

1. 系統應從已驗證 Evidence 產生型別化 feature，至少涵蓋價格、技術指標、資金費率、OI 與鏈上 key-value 指標。
2. 每個 feature 必須保留 `evidence_id`、`coin`、`value`、`unit`、`window`、`as_of`、`method` 與 extraction mode。
3. 抽取必須是決定性的，不呼叫 LLM；無法安全解析時應略過，不得猜值。
4. 若未來 Evidence 直接提供 `structured_features`，應優先採用顯式欄位，文字解析僅作向後相容 fallback。

### R2 — Knowledge Lite

1. Knowledge 只說明指標定義、適用範圍、限制與參考來源，不得產生 bullish／bearish 方向結論。
2. 只有 catalog 中已審核的 feature 才能取得 Knowledge Card；未知 feature 應保留 feature 本身但不生成知識。
3. Knowledge Card 必須揭露 `evidence_scope` 與 limitations。

### R3 — Evidence Relationship Graph Lite

1. Graph 應把 Evidence 與既有 facts、inference、conclusion、debate summary 連結起來。
2. 應支援未來 v1.2 `related_claims` 欄位，也保留 legacy `related_claim` 作為 topic，而非把 topic 假裝成報告 claim。
3. duplicate、quarantined、invalid Evidence 必須留在 graph 供稽核；不得靜默刪除。
4. Graph 是展示與稽核 sidecar，不得回寫或改變推理結果。

### R4 — Integration and compatibility

1. 所有能力應由單一 `build_research_context()` 入口組裝，並可寫成 `research_context.json`。
2. 模組不得依賴 Claude 正在修改的 Validation／claim mapping 具體類別；應以相容 adapter 讀取選填欄位。
3. v1.2 原有三項正式交付與 `report_view.json` 不得因 sidecar 失敗而中止。
4. 輸出必須有 schema version，且排序穩定以利 diff、測試與稽核。

## Non-goals

- 不實作完整 Market Regime 或 Dynamic Weight Engine。
- 不新增 Hypothesis Generator。
- 不讓 Evidence Graph 參與信心計分。
- 不使用 LLM 解讀 feature 或補齊缺失值。

## Acceptance criteria

- 相同輸入連續執行產生相同 JSON。
- 所有 feature 都可回到真實 Evidence ID。
- Knowledge 內容不含方向性判斷。
- quarantined／duplicate evidence 在 graph 中可見。
- 缺少未來 v1.2 選填欄位時仍可在目前 v1.2 基線運作。


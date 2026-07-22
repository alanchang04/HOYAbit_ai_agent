# Design Document

> 全專案升級：信任提煉流水線與 Execution Logs 可視化
> 對應 `requirements.md`。實作語言與慣例沿用現有 codebase（Python 3.11、pydantic v2、
> 標準庫優先、繁中註解、失敗隔離原則）。不引入新的重量級依賴。
>
> ⚠️ **2026-07-20 架構決策**：§3.1（L1 信源權重）與 §3.2（L2 內容層）的 PR/模板相似度
> 部分已被隊友 Ken 的 `07_流程圖迭代定案.md` 設計取代，詳見新增的 §3.9。§3.1/§3.2
> 保留作為「目前實作」記錄，改版時以 §3.9 為準。§3.3–§3.7（L3-L5 metrics、信心公式、
> token usage、雙幣指標、macro 單次執行）與 §4 之後（baseline／view_builder／前端）
> **不受影響、維持不變**——LLM 結論仍由辯論鏈產生，Ken 的「投票算結論」模式不採用。

## Overview

本設計把現有「五類蒐集 → 四步推理 → report.md」流程升級為可視化的信任提煉流水線：
在既有蒐集/推理階段前後插入 L1-L5 分層評分與過濾，並新增 `report_view.json` 供
四面板前端消費。所有插入點皆為既有函式的前後掛鉤或新增獨立模組，不改動既有三個
命題交付檔案（report.md／evidence.json／execution_log.jsonl）的格式與內容。

## Architecture

### 1. 架構總覽（插入點）

```
run_pipeline()（orchestrator.py）
 ├─ 題型分類（不變）
 ├─ Phase 1 蒐集（collectors × coins）
 │    ├─ [R1-3] macro 特例：只跑一次
 │    ├─ [R4-1] L1：collector 產出時填 source_weight/weight_reason（靜態表）
 │    └─ [R2] 比較題：本地雙幣相對指標（新函式，orchestrator 呼叫）
 ├─ Phase 2 證據化（不變）＋ log L1 彙總
 ├─ [R4-2] L2 內容層過濾（新模組 agent/filters/）→ FilterDecision 清單、調權
 ├─ Phase 3 推理（pipeline.py，四步不變）
 │    ├─ Step A → 補 L3 metrics（剔除率）
 │    ├─ Step B → 補 L4 metrics
 │    └─ Step D → [R4-5] 數值信心公式
 ├─ [R7-2] 選配：baseline 一次呼叫（--with-baseline）
 ├─ Phase 4 報告（builder.py 不變）
 └─ [R5] view_builder.py → report_view.json（新）
```

既有三個輸出檔案（report.md / evidence.json / execution_log.jsonl）格式與內容不變，
只是 log 每行**多兩個選用欄位**（layer/metrics，舊行為不受影響）。

## Data Models

### 2. 資料模型（schemas.py 新增）

依 requirements R3 逐字實作：

```python
class PipelineLayer(str, Enum):
    SOURCE = "L1_source"
    CONTENT = "L2_content"
    FACT = "L3_fact"
    CROSS = "L4_cross"
    CONCLUSION = "L5_conclusion"

class FilterVerdict(str, Enum):
    KEPT = "kept"
    DOWNWEIGHTED = "downweighted"
    REMOVED = "removed"

class FilterDecision(BaseModel):
    evidence_id: str
    check_code: str          # "PR" | "F10" | "F9" | "SUBJ"
    verdict: FilterVerdict
    reason: str
    weight_before: float | None = None
    weight_after: float | None = None

class RunMetrics(BaseModel):
    confidence: int = 0
    noise_removal_rate: float = 0.0
    total_tokens: int = 0
    integrity_status: str = "INTACT"   # INTACT | DEGRADED
    raw_evidence_count: int = 0
    kept_fact_count: int = 0
```

`EvidenceDraft` 加四欄（全預設值）；`LogEntry` 加 `layer`/`metrics`（預設 None/{}）。
向後相容驗證：既有 41 個測試零修改通過（R3-4 的驗收）。

## Components and Interfaces

| 元件 | 介面 | 說明 |
|---|---|---|
| `agent/filters/dedup.py`（§3.9，2026-07-21 新增） | `apply_dedup(evidences, logger, min_sample=None) -> DedupResult`（原地標 `duplicate_of`/dedup 統計欄位） | Phase 2 去重（R12-1），news/social 限定 |
| `agent/filters/trust_config.py`（§3.9，2026-07-21 新增） | `load_reputation_config() -> dict \| None`（失敗回 None → 呼叫端 fallback） | 載入 `static/source_reputation.json` |
| `agent/filters/source_weights.py`（§3.9 四因子版，舊制表保留為 fallback） | `apply_source_weights(evidences, logger, dedup_result=None, pr_demotions=None) -> dict[str, WeightBreakdown]`（原地補 `source_weight`/`weight_reason`，回傳四因子分解供 L2 對帳） | L1 信源層（R12-3/4/5） |
| `agent/filters/content.py`（§3.9 版：話術掃描＋F9 詞典法；模板相似度由 dedup 取代） | `scan_pr_terms(evidences) -> dict`；`apply_content_filters(evidences, logger, pr_hits=None, breakdowns=None) -> list[FilterDecision]` | L2 內容層 |
| `agent/reasoning/pipeline.py`（不變） | `run_reasoning(...) -> ReasoningResult`；內部 Step A-D 補寫 L3-L5 metrics | 推理鏈＋辯論＋L3-L5 metrics |
| `agent/reasoning/confidence.py`（不變） | 內嵌於 pipeline Step D 後，純函式輸出 `(score, breakdown)` | L5 數值信心公式 |
| `agent/reasoning/baseline.py`（§4） | `run_baseline(question, evidences, llm_client) -> dict` | 未過濾對照組，同一 `LLMClient` |
| `agent/collectors/relative.py`（§3.6） | `compute_relative_metrics(coin, coin2, data_dir) -> EvidenceDraft` | 雙幣相對指標，純本地 |
| `agent/report/view_builder.py`（§6） | `build_report_view(out_dir, evidences, reasoning_result, run_metrics, filter_decisions, baseline_result, ...) -> dict \| None` | 組裝 `report_view.json`，失敗回傳 None 不拋例外 |
| `webapp/templates/result.html` / `view.html`（§7） | 讀 `report_view.json` ＋ `execution_log.jsonl` 渲染 | 前端 MVP／完整四面板 |

各元件之間透過 `Evidence`／`FilterDecision`／`RunMetrics`／`ReasoningResult` 這幾個
共用 pydantic model 傳遞資料，彼此不直接呼叫對方內部函式（維持低耦合，方便個別替換，
例如 §3.9 的 Ken 設計改版只需替換 `source_weights.py`/`content.py` 內部實作，不影響
下游 pipeline／view_builder 的呼叫介面）。

## 3. 各層設計

### 3.1 L1 信源權重（靜態表）

`agent/filters/source_weights.py`：以 `(source_type, source 關鍵字)` 查表。

| 規則（依序比對） | weight | reason |
|---|---|---|
| source 含 "HOYA BIT 共同基準" 或 "本地技術指標" | 0.95 | 官方基準資料／決定性本地運算 |
| source_type == onchain | 0.85 | 鏈上公開 RPC，數據不可竄改 |
| source 含 "CoinGecko"/"CryptoCompare" | 0.80 | 交易所聚合行情 API |
| source_type == macro | 0.65 | 公開指數/央行匯率 |
| source_type == news | 0.60 | 主流媒體，未逐篇查證 |
| source_type == social | 0.30 | 未經查證社群內容 |

實作位置選擇：**collector 不動**，在 Phase 2 證據化後由 orchestrator 統一補權重
（單點修改、dry-run 同樣生效）。log 一筆 `layer=L1_source` 彙總 metrics。

### 3.2 L2 內容層（agent/filters/content.py，純本地）

- **PR 詞典**（英文優先）：`PR_TERMS = ["skyrocket", "to the moon", "guaranteed", "once-in-a-lifetime", "can't miss", "100x", "explode", "moonshot", "暴漲", "千載難逢"]`
  命中 → weight × 0.5（下限 0.05），`FilterDecision(check_code="PR", downweighted)`
- **模板相似度**：對 news/social 證據的 `content_reference` 做小寫 token 集合 Jaccard 相似度，
  ≥0.8 的配對 → 兩筆都標 `FilterDecision(check_code="F10", downweighted, reason="near-duplicate of ev-XXX（非獨立來源）")`，後到者權重 × 0.6。
  純標準庫（set 運算），不引入 rapidfuzz
- **F9 情緒分布**：不實作，view 中該 check 輸出 `{"enabled": false}`（同伴 RAG 介面：
  未來由 `rag_verified`/`rag_support` 欄位＋獨立 metrics 注入）
- 過濾在推理之前執行；`removed` 的證據**不進 LLM prompt** 但**仍留在 evidence.json**
  （完整可回溯——被剔除本身就是要展示的資訊）。目前 L2 只降權不剔除（removed 保留給
  L3 的主觀剝離統計），推理 prompt 的證據清單附上權重讓 LLM 參考
- 全部 FilterDecision 逐筆寫 log（layer=L2_content）＋一筆彙總 metrics

### 3.3 L3/L4 metrics（pipeline.py 小改）

- Step A 後：`input=len(evidences)`、`kept=Σ facts.evidence_ids 去重`、`removed=input−kept`、
  `removal_rate` → log（layer=L3_fact）＋回填 RunMetrics.noise_removal_rate
- Step B 後：`consistent`/`contradictions` 數量 → log（layer=L4_cross）

### 3.4 L5 數值信心（pipeline.py）

```
base = {"高": 75, "中": 55, "低": 35}[conclusion.confidence]
auth_bonus  = round(10 * 權威源(weight≥0.7)證據數 / 總證據數)
contradiction_penalty = min(15, 5 * 矛盾訊號數)
gap_penalty = min(15, 5 * 缺失來源類別數)   # 5 類中證據數為 0 的類別
confidence_score = clamp(base + auth_bonus - contradiction_penalty - gap_penalty, 5, 95)
```
各分項寫入 log metrics（layer=L5_conclusion），評審可逐項對帳。

### 3.5 Token usage（兩個 client 同步改）

`converse()` 簽名不變；client 內部累計：

```python
self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
# bedrock: response["usage"]["inputTokens"/"outputTokens"]
# gemini:  response.usage_metadata.prompt_token_count / candidates_token_count
```
orchestrator 於推理結束後 `getattr(llm_client, "usage", None)` 讀取 → RunMetrics.total_tokens。

### 3.6 雙幣相對指標（R2，agent/collectors/relative.py 新檔）

輸入兩份本地 CSV（近 90 日收盤），純 Python 計算：
- 日報酬皮爾森相關係數
- beta（coin 對 coin2 報酬回歸斜率，母體變異數）
- 各自期間最大回撤
- 相對強弱比值 close_A/close_B 目前值在 90 日分布的百分位

輸出**一筆** price 證據：`coin=f"{coin}/{coin2}"`（配對證據標籤）、source="本地雙幣相對指標計算"、
weight 0.95。orchestrator 在比較題型且兩份 CSV 齊備時呼叫；失敗隔離。

### 3.7 macro 單次執行（R1-3）

`collect_all()` 特例：macro collector 的 tasks 只建一次（用主幣種呼叫）。
dry-run 路徑同樣生效；更新比較題測試斷言「macro 證據無重複」。

### 3.8 news 比對修復（R1-1/2）

`_matches_coin()` 改為與 `coin_map` 一致的雙軌比對：
ticker 大小寫敏感（`"ETH" in text`）＋全名別名小寫比對（`"ethereum" in text.lower()`）。
`coin_map.py` 匯出 `_FULL_NAME_ALIASES`（改名 `FULL_NAME_ALIASES`）供共用，單一事實來源。
回歸測試：含 "method"/"solution" 的標題不得命中 ETH/SOL；含 "Ethereum"/"SOL" 的正常命中。

### 3.9 資料層目標設計：採用 Ken 的信任評分公式（R12，取代 3.1/3.2a/3.2b）

> 設計權威為 Ken（`07_流程圖迭代定案.md`），本節只是把它轉寫成與本文件其他章節
> 一致的格式。**2026-07-21 已由 Alan 實作完成 filters 層**（`dedup.py`／
> `trust_config.py`／`source_weights.py`／`content.py`／`static/source_reputation.json`，
> 見 tasks.md Phase 7；R12-2 的 collector 側計數仍待 Kevin/Ken）。**本節只影響
> L1/L2 的評分/去重邏輯，不影響 §3.3-3.8、§4 之後任何章節**——結論仍由辯論鏈
> 產生（Property 6）。

**Phase 2（證據化）新增去重步驟**：標題相似度去重（本地字串級，不經 LLM），
與去重同步算出並隨證據傳遞：
- `raw_count`：去重前筆數
- `deduped_count`：去重後筆數
- `dedup_rate = 1 − deduped_count／raw_count`

**權重公式改為四因子**（取代 §3.1 現行單一權重表）：

```
w = 新鮮度 × 來源等級 × 覆蓋度 × dedup_penalty
```

| 因子 | 定義 | 來源 |
|---|---|---|
| 新鮮度 | 證據時效性（越新越高） | 沿用 `fetched_at` 計算 |
| 來源等級 | 查靜態信譽表 | `static/source_reputation.json`（賽前定案＋一行分級理由，印進報告附錄） |
| 覆蓋度 | 去重後的**獨立來源數**（來源多樣性） | Phase 2 去重結果 |
| `dedup_penalty` | 灌水/聯播程度，**獨立於覆蓋度計算**（覆蓋度量多樣性，dedup_penalty 量單一敘事被灌水的程度，兩者量測對象不同，不可併入同一因子） | Phase 2 的 `dedup_rate`；去重前筆數 <5 時固定為 1（不觸發降權，避免除零/小樣本誤判） |

**拉盤話術詞庫**（取代 §3.2 現行 PR_TERMS 的「權重 ×0.5」做法）：命中則**來源等級降一級**，
與 `dedup_penalty` 降權是獨立維度、允許同時疊加（不是重複扣分，需在報告/文件註明避免
被誤認為 bug）。

**與現行 §3.1/§3.2 的差異總表**：

| 項目 | 現行實作（§3.1/§3.2） | Ken 目標設計（本節） |
|---|---|---|
| 權重結構 | 單一 `source_weight`（規則表查一次） | 四因子相乘（新鮮度×來源等級×覆蓋度×dedup_penalty） |
| 去重時機 | 無去重，命中則數在 collector 內、去重前計數（違反 R2-3 新版驗收條件） | Phase 2 先去重，命中則數用去重後數字 |
| 模板相似度／PR 降權 | `content.py` 各自獨立乘一次係數 | 併入 `dedup_penalty`（相似度）＋來源等級降級（話術），可疊加 |
| 覆蓋度 vs 覆蓋率 | 未定義覆蓋度 | 明確區分：覆蓋度＝去重後獨立來源數（L1/L2 用）；覆蓋率＝collector 成功執行比例（L5 信心公式用，見 §3.4，兩者不可混用） |

**Fallback**：靜態信譽表或去重邏輯計算失敗時，SHALL 退回 §3.1 現行規則表作為
fallback，不得中斷整體流程（R12-5）。

## 4. Baseline 對照組（R7-2）

`agent/reasoning/baseline.py`：
- 單一 prompt：全量證據（未加權重註記、含被降權者原文）＋題目 → 要求直接給分析結論
  （prompt 內明文禁止投資建議）
- 同一個 `llm_client.converse()` 一次呼叫；失敗隔離（view 標 `enabled:false, error:...`）
- caveat 由 view_builder 以模板產生：「此為未過濾對照組輸出：未做信源加權/雜訊過濾/證據回溯」
- 開關：CLI `--with-baseline`、表單 checkbox；預設 off

## 5. report_view.json schema（v1.0，前後端契約）

頂層：`schema_version`、`meta{coin,coin2,question,question_type,generated_at,metrics:RunMetrics}`。

- `panel1_raw_feed`: `{count, items:[{fingerprint, evidence_id, source, source_type, source_weight, weight_reason, content_reference, coin, filter_decisions:[FilterDecision]}]}`
- `panel2_naive_baseline`: `{enabled, steps:[{step,label,desc}×4 固定文案], naive_output:{analysis, caveat} | null, error?}`
- `panel3_refinement`: `{noise_removal_rate, layers:[
    {layer:"L1_source", summary:{total,authoritative,normal,low}, note},
    {layer:"L2_content", checks:[{code:"PR",hits:[...]},{code:"F10",pairs:[...]},{code:"F9",enabled:false}]},
    {layer:"L3_fact", input, kept, removed, removal_rate, removed_items:[{fingerprint,reason}]},
    {layer:"L4_cross", consistent:[...], contradictions:[...]},
    {layer:"L5_conclusion", debate:{bull,bear_critique,bear}, confidence_breakdown:{base,auth_bonus,contradiction_penalty,gap_penalty,final}}
  ], log_events_by_layer:{L1_source:[LogEntry...], ...}}`
- `panel4_report`: `{integrity_status, confidence, market_judgment, core_facts:[{fingerprint,text}], bullish_evidence:[...], risk_evidence:[...], limitations:[...], invalidation_conditions:[...], follow_up_watchpoints:[...]}`
  - bullish/risk 由 debate 的 bull/bear evidence_ids 映射；無辯論（fallback 路徑）時由
    inference 的 supporting/opposing 映射
- 指紋映射：evidence.json 順序 → F1..Fn；view 內全部用 fingerprint，附 evidence_id 供對帳

範例資料（英文幣圈語料）沿用 `UPGRADE_SPEC_execution_logs.md` v2 §6，該檔保留作參考。

## 6. view_builder（agent/report/view_builder.py）

輸入：`out_dir`（讀 execution_log.jsonl、evidence.json）＋ `ReasoningResult` ＋ `RunMetrics`
＋ FilterDecision 清單 ＋ baseline 結果。輸出：`out_dir/report_view.json`。
純函式、無網路、失敗隔離（view 組裝失敗只記 log，不影響三個命題交付檔案）。

## 7. 前端

### Stage 1 MVP（改 result.html）
分頁籤：`報告`（現有內容）｜`執行時間線`｜`Raw Log`。
- 時間線：template 端遍歷 log entries（由 app.py 讀檔傳入），每行：時間、phase 徽章、
  action、status 色點（ok 綠/error 紅/skipped 黃）、metrics 摘要（有才顯示）
- Raw Log：`<pre>` 逐行原文
- header 摘要列：讀 report_view.json 的 meta.metrics
- 無 JS 框架，沿用現有 Jinja2＋style.css（新增樣式類）

### Stage 2 完整四面板（新 template：view.html）
- 四欄響應式版面（窄螢幕直排），視覺對齊參考截圖但配色沿用現有 style.css 變數
- 面板③每層 `<details>` 展開對應 log 事件（`log_events_by_layer`）
- 資料來源：`/view/{run_id}` 路由讀 `report_view.json` 渲染；dry-run 假資料同路徑可測

## 8. dry-run fixtures（R8）

`fixtures/dry_run_evidence.json` 各項加 `source_weight`/`weight_reason`；
`orchestrator` dry-run 路徑：跳過 LLM 但走完 L1/L2/metrics/view_builder（L2 對假資料
照樣跑詞典/相似度——純本地無成本）；baseline 於 dry-run 時輸出固定假文案。
結果：`--dry-run` 產出的 report_view.json 每個欄位皆非空。

## Error Handling

### 9. 錯誤處理與 degraded 整合

- 任一新增層失敗：記 log（error）→ 跳過該層 → `integrity_status="DEGRADED"`＋
  view 註明哪層被跳過（沿用既有隔離哲學，絕不讓新功能弄壞舊的穩定性）
- degraded mode（超時）：L2 直接跳過，同樣標 DEGRADED

## Correctness Properties

以下不變量在測試策略（見下）與 code review 時都要能對應驗證：

### Property 1: 向後相容
新增欄位一律有預設值，既有 pydantic model 建構呼叫不需修改即可通過。

**Validates: Requirements 3.4**

### Property 2: 面板數字可追溯
`report_view.json` 任何數字都必須能在 `execution_log.jsonl` 或 `evidence.json` 中
查到來源，不允許前端／view_builder 自行發明數值。

**Validates: Requirements 5.4**

### Property 3: 三個命題交付檔案不變
無論本規格如何擴充，`report.md`／`evidence.json`／`execution_log.jsonl` 的既有欄位
與產生邏輯不受影響。

**Validates: Requirements 5.5**

### Property 4: 單層失敗不中斷全流程
L1/L2/baseline/view_builder 任一環節失敗，其餘流程必須照常完成並產出三個命題交付
檔案，沿用既有 collector 失敗隔離原則。

**Validates: Requirements 9.3**

### Property 5: LLM backend 中立
所有推理相關程式碼只透過 `LLMClient` 介面呼叫，替換 bedrock/gemini 不需要修改
`pipeline.py`／`baseline.py` 的邏輯。

**Validates: Requirements 10.1**

### Property 6: 結論產生權不下放
市場判斷與信心必須來自 `pipeline.py` 的辯論鏈（Step D），不得由規則式評分（L1-L5
的權重/過濾/量化指標）直接決定，這些只能作為輸入（2026-07-20 架構決策，見文件頂部）。

**Validates: Requirements 12.6**

## 10. Bedrock 切換註記（R10，不在本規格實作範圍內測試）

切換僅動 `.env`（LLM_BACKEND/AWS_REGION/BEDROCK_MODEL_ID）。最終驗證清單
（blocked-on-bedrock-access）：
1. `aws sts get-caller-identity` → `scripts/check_llm.py`
2. 若 ValidationException 提示 on-demand 不支援 → 改 inference profile ID（`us.anthropic....`）
3. 一次真實 pipeline：檢查 stopReason 無 max_tokens 截斷（必要時 2048→4096）、
   JSON 遵從、耗時、usage 統計有值
4. 3 題型端到端＋view 檢查
本規格所有功能只經 `LLMClient` 介面，天然 backend 中立。

## Testing Strategy

### 11. 測試策略

- 單元：source_weights 查表、PR/相似度過濾、相對指標數學（手算樣本）、信心公式、
  news 比對回歸、macro 單次回歸、view_builder 組裝（假輸入）、usage 累計（FakeLLMClient 擴充）
- 整合：dry-run 端到端斷言 report_view.json schema 完整、三個舊檔案不變
- 手動：MVP 時間線與四面板以 dry-run 資料目視驗收；真實 Gemini 一次（額度允許時）

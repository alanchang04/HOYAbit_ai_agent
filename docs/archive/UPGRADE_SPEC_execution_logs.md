# 升級規格書：Execution Logs 可視化流水線（v2）

> 撰寫對象：負責 execution logs 顯示的成員（你）。
> 分工前提：資料來源抓取與 RAG 驗證由同伴負責；本規格聚焦在 **execution log 的資料結構、
> 分層事件、以及四面板 UI 的資料契約**。
> 對照基準：現有程式碼（`agent/schemas.py`、`agent/logging_utils.py`、`agent/reasoning/pipeline.py`、
> `agent/report/builder.py`）。
> v2 變更：面板重新命名、明確「execution log 即顯示核心」、範例改為英文幣圈語料、
> 與比賽規則逐條對照檢查（§0.5）。

---

## 0. 一句話目標

把目前「一行一個工具呼叫」的 `execution_log.jsonl`，升級成一條**可視化、可回溯的「信任提煉流水線」**：
原始資料進來 → 逐層過濾雜訊（並記錄每一層剔除了什麼、為什麼）→ 每個保留下來的事實都有指紋 ID →
最終報告的每個結論都能反查回指紋。UI 的四個面板**就是 execution log 的四個切面**——
使用者在畫面上看到的每一個項目，都對應 log 裡的一筆帶時間戳的事件。

主辦方要的不是「預測漲跌」，而是「**蒐集 → 清雜訊 → 分層推理 → 產出證據充分的分析報告**，
且資料來源與推理邏輯全程透明」。execution logs 就是這個「透明」的載體，也是這次升級的主角。

---

## 0.5 與比賽規則的逐條對照檢查

| 比賽規則 | 本規格的對應 | 狀態 |
|---|---|---|
| LLM 推理僅能用 Bedrock | 五層流水線與**基準對照組（§8）都走同一個 `LLMClient`**，正式執行時 `LLM_BACKEND=bedrock`；內容層過濾建議用純程式規則（不經 LLM），天然合規 | ✅ |
| 不是價格預測系統、不得給買賣建議 | 面板④只輸出「市場判斷＋信心＋限制」；**基準對照組的 prompt 也回答分析題**（禁止其輸出 buy/sell/hold），對照點是「有無可驗證依據」而非「建議對不對」；`INTACT` 定義為「分析完整性」非持有訊號（§11.1） | ✅（v2 修正） |
| 15 分鐘執行時限 | 內容層過濾走純程式（毫秒級）；基準對照組可開關，計時跑可關（§8、§11.3）；degraded mode 可跳過過濾層並在 view 標記（§11.6） | ✅ |
| Execution Log 需含時間戳、工具呼叫、資料取得紀錄、分析流程摘要 | 保留現有逐行 `execution_log.jsonl`（append-only raw trace），僅擴充欄位不刪減；四面板是它的視覺化，另附 raw log 檢視（§2.1） | ✅ |
| Evidence 需可回溯（source/fetched_at/content_reference/related_claim） | 現有 schema 不動主鍵，只擴充權重/驗證欄位；指紋 F1..Fn 只是顯示標籤，映射回 `ev-NNN` | ✅ |
| 不得把第三方完整市場判斷當結論 | 過濾層只做「剔除/降權」，判斷仍由自有四步推理鏈產生；RAG 僅作查證輔助 | ✅ |
| 報告語言依題目語言（預設繁中） | UI 標籤與報告文字為繁中；**證據原文（英文新聞標題等）保留原文引用**，不影響規則 | ✅ |

**v2 發現並修正的兩個潛在衝突**：
1. v1 的基準對照組範例輸出含「建議：持有」——即使是反面教材，畫面上出現持有建議仍有被
   誤解為投資建議的風險 → 改為讓對照組回答同一道分析題，展示「結論無可驗證依據」的對比。
2. v1 未寫明對照組用哪個 LLM——若誤用非 Bedrock 服務會直接違規 → 明定走同一個 `LLMClient`。

---

## 1. 四面板定義（v2 重新命名）

| 面板 | v1 名稱（附圖） | **v2 正式名稱** | 本質 | 現有專案對應 |
|---|---|---|---|---|
| ① | 新聞流 | **原始證據流**（Raw Evidence Feed） | 五類來源的原始資料 + 信源權重 | 五類 collector 產出的 raw evidence（需**新增權重**） |
| ② | 套殼 AI | **未過濾基準對照**（Naive Baseline） | 對照組：不過濾、全量餵 LLM 會得到什麼 | **全新**，可開關 |
| ③ | 五層防禦 | **信任提煉流水線**（Trust Refinement Pipeline） | 逐層過濾/推理，每層記錄剔除項與指標 | 現有四步推理**前置兩層過濾**＋剔除率統計 |
| ④ | 推送給用戶 | **分析報告**（Analysis Report） | 結論＋信心＋核心事實＋正反證據 | 現有 `report.md`（需**指紋化＋結構化 JSON**） |

命名理由：「信任提煉流水線」直接呼應命題主題「**多源資訊的信任提煉**」，簡報講起來一體成形；
「未過濾基準對照」講清楚它是實驗對照組而非我們的產品；「防禦/投毒」的攻擊性語彙全部退場，
改用中性的「雜訊剔除」（見 §4.4，`poison_rate` → `noise_removal_rate`），
因為命題原文用語是「**辨識市場雜訊**」。

---

## 2. Execution log 是顯示核心（v2 強化）

### 2.1 顯示原則

1. **四面板 = execution log 的渲染結果**。`view_builder` 的唯一輸入是
   `execution_log.jsonl` + `evidence.json` + `ReasoningResult`；不允許前端顯示任何
   log 裡查不到的數字（否則「透明化」就是假的）。
2. **頁面 header 直接展示執行摘要**（對應附圖最上方那行）：
   `生成時間 ｜ 信心 85% ｜ 雜訊剔除率 33% ｜ 10,428 tokens`——四個數字全部來自 log。
3. **必須附「原始 log 檢視」**：四面板之外提供一個 Raw Log 分頁（或摺疊區塊），
   逐行按時間戳列出 `execution_log.jsonl` 原文。這是主辦方抽查時的直接證據，
   也證明面板不是另外編的故事。
4. 面板③每一層點開，要能看到該層對應的 log 事件（含 `ts`、`action`、`metrics`）。

### 2.2 現有落差

現有 `execution_log.jsonl` 每行：
```json
{"ts":"...","phase":"collect|reason|report","action":"price_collector","detail":"...","status":"ok"}
```
只知道「某工具跑了、成功或失敗」，**看不出**：
- 每筆資料的信源權重是多少、為什麼
- 哪些資料被當成雜訊剔除、依據什麼規則
- 剔除率（雜訊佔比）是多少
- 每個最終結論引用了哪些指紋事實

現有 `Evidence`（`schemas.py:38`）缺：`source_weight`、過濾判定結果、指紋顯示標籤。
現有 `pipeline.py` 的四步（事實→交叉驗證→辯論→結論）**沒有前置的雜訊過濾層**，
也沒有把「剔除了幾條主觀內容」量化出來。

---

## 3. 分工界線（重要）

| 項目 | 負責人 | 產出/介面 |
|---|---|---|
| 資料抓取（五類 collector） | 同伴 | 產出 `EvidenceDraft`（需新增 `source_weight` 等欄位，見 §4.1） |
| 信源權重指派 | 同伴（建議） | 在 collector 端或 RAG 端決定每筆 `source_weight` 與 `weight_reason` |
| RAG 事實驗證 | 同伴 | 對每筆 evidence 標記 `rag_verified` / `rag_support` |
| 內容層過濾邏輯（情緒/模板/PR 偵測） | **待議**（見 §11.7） | 產出 `FilterDecision`（本規格定義 schema，實作可你我分攤） |
| **Execution log 分層事件結構** | **你** | 本規格 §4–§5 |
| **四面板 view model（`report_view.json`）** | **你** | 本規格 §6 |
| **四面板前端顯示＋Raw Log 檢視** | **你** | 消費 `report_view.json` ＋ `execution_log.jsonl` |

> 你只要確保：**同伴的 collector/RAG 依 §4 的 schema 吐資料，你的 view_builder 就能組出 §6 的 view model**。
> 中間的過濾層（§5）是介面清楚的黑盒，誰實作都不影響你的顯示層。

---

## 4. 資料模型升級（schema）

以下都加在 `agent/schemas.py`。**向後相容原則**：新欄位一律給預設值，
讓現有 `--dry-run` 與測試不用大改就能跑。

### 4.1 Evidence 擴充（信源層需要）

```python
class EvidenceDraft(BaseModel):
    coin: str
    source: str
    source_url: str | None = None
    fetched_at: str
    content_reference: str
    related_claim: str
    source_type: SourceType
    # --- 新增（信源層）---
    source_weight: float = 0.5          # 0.0-1.0，信源可信度權重
    weight_reason: str = ""             # 為何是這個權重（例："官方基準資料集/交易所公開 API"）
    # --- 新增（RAG，同伴填）---
    rag_verified: bool | None = None    # None=未驗證, True/False=RAG 查證結果
    rag_support: str = ""               # RAG 佐證片段或反證說明
```

**權重分級建議**（對應附圖「權威源 ≥0.7 / 一般源 / 低質源 <0.35」）：
| 權重區間 | 分類 | 我們的來源範例 |
|---|---|---|
| ≥ 0.7 | 權威源 | 主辦方 OHLCV CSV、本地技術指標（決定性運算）、鏈上公開 RPC、CoinGecko 行情 API |
| 0.35–0.7 | 一般源 | CoinDesk / Cointelegraph 新聞、Fear & Greed、Frankfurter 匯率 |
| < 0.35 | 低質源 | Reddit 社群貼文、未經查證的轉載/聚合內容 |

### 4.2 過濾判定（內容層＋事實提取層需要）

```python
class FilterVerdict(str, Enum):
    KEPT = "kept"                 # 保留為事實
    DOWNWEIGHTED = "downweighted" # 降權但保留
    REMOVED = "removed"           # 剔除（主觀/PR/模板/低質）

class FilterDecision(BaseModel):
    evidence_id: str              # 對應 ev-001
    check_code: str               # "F9"(情緒) "F10"(模板) "PR"(話術) "SUBJ"(主觀) 等
    verdict: FilterVerdict
    reason: str                   # 人看得懂的理由（會直接顯示在面板③）
    weight_before: float | None = None
    weight_after: float | None = None
```

### 4.3 分層事件（execution log 核心升級）

**不打掉現有 LogEntry**（它仍是逐行 append 的 raw trace，命題文件要求保留時間戳與工具呼叫），
而是**新增 layer/metrics 欄位**，讓每筆 log 可歸屬到流水線的某一層：

```python
class PipelineLayer(str, Enum):
    SOURCE = "L1_source"          # 信源層
    CONTENT = "L2_content"        # 內容層（情緒/模板/PR）
    FACT = "L3_fact"              # 事實提取層（剝離主觀，現有 Step A 強化）
    CROSS = "L4_cross"            # 交叉驗證層（現有 Step B）
    CONCLUSION = "L5_conclusion"  # 結論層（現有 Step C 辯論 + Step D）

class LogEntry(BaseModel):
    ts: str
    phase: LogPhase
    action: str
    detail: str = ""
    status: LogStatus
    # --- 新增 ---
    layer: PipelineLayer | None = None     # 這筆 log 屬於哪一層（None=非流水線事件）
    metrics: dict = {}                      # 該步驟的量化指標（見下）
```

`metrics` 範例（依 layer 不同）：
- L2 情緒：`{"pos":0.38,"neg":0.04,"neu":0.58,"baseline":[0.25,0.20,0.55],"anomaly":false}`
- L2 模板：`{"cluster_threshold":0.8,"batch_detected":false}`
- L3 剔除：`{"input":24,"kept":9,"removed":8,"removal_rate":0.33}`
- L5 結論：`{"confidence":85,"contradictions":2}`

### 4.4 執行摘要指標（頁面 header 需要）

```python
class RunMetrics(BaseModel):
    confidence: int = 0               # 0-100，對應 header「信心 85%」
    noise_removal_rate: float = 0.0   # 0.0-1.0，雜訊剔除率（v1 的 poison_rate 更名）
    total_tokens: int = 0             # LLM token 用量（Bedrock usage 回傳，§11.8）
    integrity_status: str = "INTACT"  # 「分析完整性」：五層皆完成且無關鍵資料缺口（§11.1）
    raw_evidence_count: int = 0
    kept_fact_count: int = 0
```

---

## 5. 五層流水線規格（每層要 log 什麼）

> 過濾演算法本身（情緒分析、模板偵測、PR 話術）可你我分攤或走 RAG；
> 本節定義**每層必須產出哪些 log/指標**，這是你顯示層的輸入契約。
> **所有 check 都必須以英文語料為第一優先**（我們的新聞/社群來源是英文，§11.4）。

### L1 信源層
- 對每筆 evidence 指派 `source_weight` + `weight_reason`
- log 一筆彙總：`metrics={"total":24,"authoritative":14,"normal":8,"low":2}`
- 面板①直接顯示每筆 source + weight

### L2 內容層（三個 check，建議純程式實作，不經 LLM）
- **F9 情緒分布**：統計正/負/中性比例，對照歷史基準；偏離過大 → 標記 anomaly（可能有情緒操縱）。
  英文財經情緒可用 VADER / Loughran-McDonald 類詞典起步
- **F10 模板化掃描**：對標題/內容做相似度分群（閾值例 0.8），發現批量雷同 → 疑似水軍/複製貼上。
  （現有系統已有雛形：交叉驗證層曾自行指出兩則新聞「非獨立來源」，這裡把它前移並量化）
- **PR 話術偵測**：命中英文行銷詞（"skyrocket"、"to the moon"、"once-in-a-lifetime"、
  "guaranteed"、"can't-miss" 等）→ 產出 `FilterDecision(check_code="PR", verdict=DOWNWEIGHTED)`，
  權重下調（例 0.60→0.40）
- 每個判定都要有 `reason`（直接顯示在面板③，例：`hit "skyrocket", weight 0.60→0.40`）

### L3 事實提取層（現有 Step A 強化）
- 強制剝離：形容詞、目標價、模糊預測 → 只保留可驗證事實
- 產出 `FilterDecision(check_code="SUBJ", verdict=REMOVED, reason="vague prediction / price target")`
- **計算 `noise_removal_rate` = removed / input**（header 頭條指標）
- log：`metrics={"input":24,"kept":9,"removed":8,"removal_rate":0.33}`

### L4 交叉驗證層（現有 Step B，不變）
- 沿用現有一致訊號/矛盾訊號輸出
- 額外 log：`metrics={"consistent":5,"contradictions":2}`

### L5 結論層（現有 Step C 辯論 + Step D，不變）
- 沿用現有正反方辯論 + 結論
- **信心數值化**：現有「高/中/低」之外增加 0-100 數值，須由可解釋公式產生（§11.2）
- log：`metrics={"confidence":85,"debate":true}`

---

## 6. 四面板 UI 資料契約（`report_view.json`）

新增 `agent/report/view_builder.py`，在 pipeline 結束後把 `execution_log.jsonl` + `evidence.json` +
`ReasoningResult` 組裝成這份 JSON。**這是你顯示層唯一需要讀的檔案**（Raw Log 分頁另讀
`execution_log.jsonl` 原文）。範例一律用英文幣圈語料（BTC / CoinDesk 等）：

```json
{
  "schema_version": "1.0",
  "meta": {
    "coin": "BTC",
    "coin2": null,
    "question": "分析 BTC 過去兩週的市場表現…",
    "question_type": "multi_source",
    "generated_at": "2026-07-15T10:52:16Z",
    "metrics": {
      "confidence": 85,
      "noise_removal_rate": 0.33,
      "total_tokens": 10428,
      "integrity_status": "INTACT",
      "raw_evidence_count": 24,
      "kept_fact_count": 9
    }
  },

  "panel1_raw_feed": {
    "count": 24,
    "items": [
      {"fingerprint": "F1", "evidence_id": "ev-001",
       "source": "HOYA BIT 共同基準資料集 (BTC_daily_ohlcv.csv)",
       "source_type": "price", "source_weight": 0.95,
       "content_reference": "2026-06-24 ~ 2026-07-07: close 63,100 → 62,800 USDT (-0.5%)",
       "coin": "BTC"},
      {"fingerprint": "F4", "evidence_id": "ev-008",
       "source": "CoinDesk RSS", "source_type": "news", "source_weight": 0.60,
       "content_reference": "Bitcoin stalls as open interest decline raises questions about rally's staying power",
       "coin": "BTC"},
      {"fingerprint": "F9", "evidence_id": "ev-021",
       "source": "Reddit r/CryptoCurrency", "source_type": "social", "source_weight": 0.30,
       "content_reference": "BTC is guaranteed to skyrocket next week, once-in-a-lifetime entry!",
       "coin": "BTC"}
    ]
  },

  "panel2_naive_baseline": {
    "enabled": true,
    "steps": [
      {"step": 1, "label": "接收資料", "desc": "不加區分地接收全部 24 筆原始資料"},
      {"step": 2, "label": "直接餵給 LLM", "desc": "沒有信源加權／沒有事實校驗／沒有異常偵測"},
      {"step": 3, "label": "LLM 內部推理", "desc": "PR 軟文、模板水軍與權威源混在一起，無法區分"},
      {"step": 4, "label": "形成結論", "desc": "產出結論，但無可驗證依據、無證據回溯"}
    ],
    "naive_output": {
      "analysis": "BTC sentiment appears mixed; social buzz suggests strong upside momentum next week...",
      "caveat": "此為未過濾對照組輸出：注意它把 Reddit 的『guaranteed to skyrocket』貼文當成有效訊號"
    }
  },

  "panel3_refinement": {
    "noise_removal_rate": 0.33,
    "layers": [
      {"layer": "L1_source", "name": "信源層",
       "summary": {"total": 24, "authoritative": 14, "normal": 8, "low": 2},
       "note": "主要來源：HOYA BIT 基準資料(3)、CoinGecko(1)、Blockchair(1)、CoinDesk(5)、Cointelegraph(5)…"},
      {"layer": "L2_content", "name": "內容層",
       "checks": [
         {"code": "F9", "name": "情緒分布", "result": "正常",
          "metric": {"pos": 0.38, "neg": 0.04, "neu": 0.58}, "baseline": [0.25, 0.20, 0.55]},
         {"code": "F10", "name": "模板化掃描", "result": "發現 1 組雷同",
          "detail": "CoinDesk 與 Cointelegraph 各一篇報導同一事件（Japanese firms buying BTC），標記為非獨立來源"},
         {"code": "PR", "name": "PR 話術偵測", "hits": [
           {"fingerprint": "F9", "severity": "重度",
            "reason": "hit \"guaranteed\" + \"skyrocket\" + \"once-in-a-lifetime\", weight 0.30 → 0.10"}
         ]}
       ]},
      {"layer": "L3_fact", "name": "事實提取層",
       "input": 24, "kept": 9, "removed": 8, "removal_rate": 0.33,
       "removed_items": [
         {"fingerprint": "F9", "reason": "unverifiable prediction, promotional language"},
         {"fingerprint": "F17", "reason": "opinion piece without data reference"}
       ]},
      {"layer": "L4_cross", "name": "交叉驗證層",
       "consistent": ["價格下跌與 Extreme Fear 情緒指標方向一致 (F1, F14)"],
       "contradictions": ["恐懼情緒下 7 日量能反增 10.13%，與情緒面不完全吻合 (F2, F14)"]},
      {"layer": "L5_conclusion", "name": "結論層（正反方辯論）",
       "debate": {"bull": "…", "bear_critique": "…", "bear": "…"}}
    ]
  },

  "panel4_report": {
    "integrity_status": "INTACT",
    "confidence": 85,
    "market_judgment": "BTC 短期呈修正格局，情緒面極度恐懼，但鏈上與量能未見恐慌性訊號…",
    "core_facts": [
      {"fingerprint": "F1", "text": "近 14 日收盤價 -4.32%，RSI14 30.6（中性區間）"},
      {"fingerprint": "F3", "text": "24h 鏈上交易 602,253 筆，未見異常放量"}
    ],
    "bullish_evidence": [
      {"fingerprint": "F6", "text": "Japanese firms diversifying treasuries into BTC (CoinDesk)"}
    ],
    "risk_evidence": [
      {"fingerprint": "F4", "text": "Open interest decline raises questions about rally durability (CoinDesk)"}
    ],
    "limitations": ["社群資料本次僅 2 筆有效樣本", "…"],
    "invalidation_conditions": ["若恐懼貪婪指數回升至 50 以上且量能同步放大…"],
    "follow_up_watchpoints": ["…"]
  }
}
```

**指紋 ID（F1, F2…）**：canonical id 維持現有 `ev-001`（不動 schema 主鍵），
view_builder 依出現順序映射成 `F1, F2…` 的顯示標籤放進 view model，前端只認 fingerprint。

**注意面板④的措辭**：只有市場判斷、信心、限制、可推翻條件、觀察重點——
**不出現 buy / sell / hold / 進場價 / 停損點**（§11.1）。

---

## 7. 與現有程式的整合點（落地清單）

| 檔案 | 改動 |
|---|---|
| `agent/schemas.py` | 加 §4.1–§4.4 的欄位/類別（都給預設值） |
| `agent/logging_utils.py` | `ExecutionLogger.log()` 增加 `layer`、`metrics` 參數（預設 None/{}），向後相容 |
| `agent/collectors/*.py` | 同伴：產出 evidence 時填 `source_weight`/`weight_reason` |
| `agent/filters/`（新增） | 內容層三個 check＋事實提取剝離；產出 `FilterDecision` 清單（英文語料優先） |
| `agent/reasoning/pipeline.py` | 事實層前插入 L2 過濾；計算 `noise_removal_rate`；結論層補數值 confidence 與 token 統計 |
| `agent/reasoning/bedrock_client.py` / `gemini_client.py` | 回傳 usage token 數，供 `total_tokens` 累加（§11.8） |
| `agent/report/view_builder.py`（新增，**你**） | 組 `report_view.json` |
| `webapp/app.py` + `templates/` | 你：四面板前端＋Raw Log 分頁（現有 result.html 改成讀 view model） |
| `agent/report/builder.py` | 維持 markdown 輸出（命題要交的 report.md），不衝突 |

---

## 8. 未過濾基準對照（面板②）規格

**目的**：對照組，凸顯「不做信任提煉的 naive LLM 會被雜訊帶偏」。Demo 說服力很強，
但要控制成本與合規（§0.5、§11.3）。

實作：
1. 把**全量 raw evidence（含未過濾的低質源/PR 貼文）**塞進單一 prompt
2. **用同一個 `LLMClient`（正式時即 Bedrock）呼叫一次**，要求它回答同一道分析題——
   prompt 中同樣註明「不得給出買賣建議」，對照重點是「結論缺乏可驗證依據、把行銷貼文當訊號」，
   而不是「它給了錯誤的投資建議」
3. 捕捉輸出，放進 `panel2_naive_baseline.naive_output`，並由 view_builder 附上一句
   `caveat` 指出它哪裡被雜訊帶偏（這句可由裁判步驟順帶產出，或前端寫死模板）
4. 面板②的四個 step 文案寫死即可（描述 naive 流程本身，不需真的分四次呼叫）

做成**可開關**（`--with-baseline` / config flag）：正式比賽計時跑可關掉省時間與 token，
Demo 錄影時開。`panel2.enabled=false` 時前端顯示「本次執行未啟用對照組」。

---

## 9. dry-run 也要能產出 view model（前端開發用）

你要開發前端四面板，不能每次都真的打 API + LLM（會撞額度）。
所以 `--dry-run` 流程也必須輸出一份**格式完整、內容為假**的 `report_view.json`
（假資料請直接用 §6 的英文範例），讓你純前端開發時有資料可畫。
現有 `agent/fixtures/dry_run_evidence.json` 可擴充：加上假權重、假過濾判定、假 baseline 輸出。

---

## 10. 建議開發順序

1. **先定 schema**（§4）＋擴充 dry-run fixtures（§9）→ 你就能拿假的 `report_view.json` 開始刻前端
2. 前端四面板＋Raw Log 分頁刻到能吃假資料正常顯示
3. `view_builder.py` 把真實 pipeline 的資料組成 view model
4. L1 信源權重（同伴）＋ L2 內容層過濾接上
5. 真實端到端驗證（等 Bedrock）

前端與後端用 §6 的 JSON 契約解耦，可平行開發。

---

## 11. 其他需要一併考量的事項

### 11.1 ⚠️ 合規性：措辭全面去投資建議化
附圖原型是 A 股個股、輸出「坚定持有」——那是投資建議，直接踩命題紅線。v2 已在 §0.5 修正：
- `INTACT` 定義為「**分析完整性**」（五層皆完成、無關鍵資料缺口），不是持倉訊號
- 面板④與基準對照組都不得出現 buy/sell/hold/進場價/停損點
- 這點務必跟同伴與簡報口徑一致（主題切合度佔 30%）

### 11.2 信心數值要可解釋
「85%」不能是模型隨口說的。建議由公式產生並把各項寫進 log，例如：
`confidence = base(結論層高/中/低 → 75/55/35) + 權威源占比加成(≤+10) − 矛盾訊號扣分(每項−5) − 資料缺口扣分(每類−5)`。
評審問「為什麼是 85 不是 70」時，你可以直接翻出 log 逐項對帳——這正是「推理邏輯透明化」的展示點。

### 11.3 效能：過濾層與對照組都不能吃掉 deadline 預算
現況一次真實跑 ~20-40 秒。L2 過濾**建議純程式實作**（詞典＋相似度，毫秒級、零額度、天然合規）；
對照組多一次全量 LLM 呼叫，設成可開關。改完要重新量測 worst case 仍 < 10 分鐘。

### 11.4 英文語料是第一優先（v2 強化）
我們研究幣圈，新聞（CoinDesk/Cointelegraph）與社群（Reddit）**都是英文**：
- L2 的情緒詞典、PR 話術清單、模板相似度以**英文為主**設計（中文可作次要補充）
- LLM 推理鏈本身無虞：現有 prompt 已實測能吃英文證據、產繁中報告
- 面板顯示：UI 標籤繁中、證據原文保留英文直接引用（§6 範例即此格式），不需翻譯層

### 11.5 缺資料要誠實反映在面板
現有設計：某類 collector 掛掉（例 Reddit 403）→ 標記 skipped、報告揭露缺失。
四面板也要誠實：面板①的 count 反映真實抓到幾筆、面板③信源層統計不得虛構社群資料、
面板④ limitations 列明缺口。**別讓漂亮的 UI 蓋掉資料缺口**——誠實正是我們的賣點。

### 11.6 degraded mode 下過濾層要能降級
超過 12 分鐘會跳過剩餘蒐集直接推理。時間緊迫時 L2 過濾也要能跳過，
且 view model 標記「本次因時間限制略過內容層過濾」，`integrity_status` 相應改為
`DEGRADED`（並在面板④說明），維持透明。

### 11.7 內容層過濾誰做要儘早定案
§3 標「待議」。建議：PR 話術（英文關鍵詞）＋模板相似度這兩個純本地演算法不重、可你來；
情緒分布若要準建議走 RAG/模型 → 同伴。先講清楚免得漏做。

### 11.8 token 統計需要 LLM usage 欄位
header 的「10,428 tokens」來自 LLM 回應的 usage。Bedrock Converse API 回傳 `usage`，
Gemini 也有 usage metadata；`bedrock_client.py` / `gemini_client.py` 需把它累加後回傳。小改動但別忘。

### 11.9 前後端契約版本化
`report_view.json` 最上層已加 `"schema_version": "1.0"`，之後改欄位前端才好判斷相容性。

---

## 12. 一頁總結

- **不改**：`report.md`（要交的）、四步推理核心、失敗隔離機制、`execution_log.jsonl` 逐行 append 原則
- **擴充**：`Evidence`（權重/RAG 欄位）、`LogEntry`（layer/metrics）、`pipeline.py`（前插過濾層＋剔除率＋數值信心＋token 統計）
- **新增**：`agent/filters/`（內容層，英文語料優先）、`agent/report/view_builder.py`（**你的主戰場**）、未過濾基準對照（可開關、走同一 LLMClient）、四面板前端＋Raw Log 分頁
- **面板命名**：原始證據流 → 未過濾基準對照 → 信任提煉流水線 → 分析報告
- **你的介面契約**：同伴依 §4 吐資料 → 你依 §6 的 `report_view.json` 畫四面板；Raw Log 分頁直接渲染 `execution_log.jsonl`
- **最大的坑**：§11.1 合規（全面去投資建議化）、§11.3 效能（deadline）、§11.4 英文語料

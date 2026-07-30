# Requirements Document

> 時間尺度感知（Horizon-Aware）推理與可解釋信心分數
> Kiro spec：`horizon-aware-confidence`
> 前置規格：`.kiro/specs/trust-refinement-upgrade/`（R12 四因子信譽表為本規格 R3-3 的輸入）
> 窗口政策依據：`raw_data/_meta/window_policy.md`
> 立案日：2026-07-25，需求來源：alanchang（產品決策）＋逐行原始碼查證

## Glossary

| 詞彙 | 定義 |
|---|---|
| `horizon_class` | 單筆證據所代表的時間尺度分帶，五選一：`spot`／`short`／`medium`／`long`／`structural`（定義見 R2-1） |
| 主視野（primary horizon） | 一次分析的主判斷尺度，**由題目的時間範圍動態決定**（R7-2），未明示時預設 `medium` |
| 當前訊號（current signal） | horizon **≤ 主視野**的證據，正常參與看多/看空辯論與共識投票 |
| 結構脈絡（structural context） | horizon **> 主視野**的證據，職責是定位「本次判斷處在大週期何處」，**不參與**矛盾判定與共識投票 |
| 五檔標準粒度 | 日／10 日／月／季／年，對應五個 horizon 帶的標準取樣點（R7-1） |
| 假矛盾（pseudo-contradiction） | 不同 horizon 帶之間的正常尺度差異，被誤判為同尺度的訊號衝突 |
| `as_of_date` | 本次分析的價格資料基準日＝補齊後 OHLCV 序列的最後一天（見 R1-1） |
| 缺口補齊（gap-fill） | 官方基準 CSV 末日至執行日之間，以 Binance 公開日線補足的區段（見 R1-2） |
| Data Confidence | 信心三維之一：資料完整度（40%），決定性計算，不經 LLM |
| Signal Consensus | 信心三維之一：來源方向一致性（40%），輸入為 Direction Matrix |
| Evidence Strength | 信心三維之一：證據強度（20%），由 `source_weight` 與覆蓋度推導，決定性計算 |
| Direction Matrix | 各 `source_type` 的方向表態（+1 看多／0 中性／−1 看空），由 Step B 產出 |
| Debate Adjustment | 辯論結束後由 Step D 裁判給出的信心調整值，範圍 **−15 ~ +5**（不對稱，見 R3-5） |

## Introduction

現行系統已能完成「六類蒐集 → 四步推理（含多輪辯論）→ 可回溯報告」，但推理層存在
三個彼此扣連的結構性缺陷，導致**辯論雙方系統性地缺乏信心、信心分數不可解釋**：

1. **資料時效斷層**：技術面完全依賴官方 CSV（止於 2026-05-31），與即時類資料（news／
   social／derivatives，皆為執行日）混在同一份證據清單，且兩者 `fetched_at` 都寫執行日。
2. **時間尺度資訊遺失**：`window_policy.md` 設計的六類窗口，在 `Evidence` schema 沒有
   對應欄位，推理層無從得知每筆證據代表多長的窗。
3. **信心分數不可解釋**：現行公式的基底來自 LLM 主觀填寫的「高/中/低」，±項則是資料統計，
   兩種哲學混用；且矛盾懲罰直接吃上述假矛盾。

本規格一次修復三者，並補上「辯論後信心」與「可切換語氣」兩項產品需求。

## 問題診斷（2026-07-25 逐行查證，皆為實證非推測）

### D1 — 官方資料集與執行日存在 55 天斷層，且落差極大

| 幣 | CSV 末日收盤（2026-05-31） | 執行日實際收盤（2026-07-25） | 落差 |
|---|---:|---:|---:|
| BTC | 73,674.39 | 64,071.42 | **−13.0%** |
| SOL | 82.44 | 74.02 | −10.2% |
| ETH | 2,007.01 | 1,859.18 | −7.4% |

`data/*_daily_ohlcv.csv` 與 `raw_data/price/*/` 兩份皆為 `2021-06-01 ~ 2026-05-31`
（後者是前者的複製品，非獨立來源）。`pipeline/fetch_realtime_price.py` 僅抓「當下現價」
單點，不含日線序列——**全專案沒有任何 5/31 之後的 OHLCV 序列來源**。

因此 `agent/collectors/price.py` 產出的 `RSI14`／`SMA7/14`／`MA20/60/120`／`波動率`／
`波動率全歷史百分位`／`量能趨勢`／`相對強弱` **全部描述一個已不存在的市場**。

### D2 — 斷層在同一份證據清單裡直接製造假矛盾（現行 bug，非設計問題）

`price.py:241` 產出的 CSV 摘要與 `price.py:288` 產出的 CoinGecko 即時報價，
`fetched_at` 皆為 `now_iso()`（執行日）：

```
ev-001 | fetched_at=2026-07-25 | 期間 2026-05-18~05-31：收盤 77,001 → 73,674
ev-003 | fetched_at=2026-07-25 | 現價 64,071 USD
```

Step B 無從分辨兩者時間基準不同，會將 `73,674 vs 64,071` 判為 contradiction，
經 `confidence.py:46` 扣 5 分，並使辯論雙方為不存在的衝突互相讓步。

### D3 — horizon 資訊在 schema 層完全缺席

`agent/schemas.py:62-84` 的 `EvidenceDraft` 僅有 `fetched_at`（何時抓），
無 `window_start`／`window_end`／`horizon_class`。`window_policy.md` 的六類窗口設計
在證據層 100% 蒸發。

### D4 — Step B 攤平比對，無尺度概念

`agent/reasoning/prompts.py:139-141` 僅要求「找出一致訊號與矛盾訊號」，
未區分尺度。5 天 social 情緒與 1826 筆全歷史波動率百分位被平等比對。

### D5 — LLM 全程看不到 `source_weight`

`agent/reasoning/prompts.py:84-91` 的 `_format_evidence_list()` 輸出欄位為
`id/coin/type/source/fetched_at/content`，**不含 `source_weight`**。
R12 四因子信譽計算目前僅影響過濾層與報告附錄，對辯論零影響。

### D6 — 信心公式基底其實是 LLM 主觀值

`agent/reasoning/confidence.py:20` 的 `CONFIDENCE_BASE = {高:75, 中:55, 低:35}`，
該標籤由 Step D 自行填寫，佔最終分數 70–80%。現況既非「資料信心」亦非「可複現」。

### D7 — `confidence.py` 漏算 derivatives（既有 bug）

`agent/reasoning/confidence.py:11-17` 的 `SOURCE_TYPE_CATEGORIES` 僅五類，
未隨 Ken 的 `SourceType.DERIVATIVES` 同步。衍生品資料再完整也不改善 `gap_penalty`。

## 規則依據（命題數據集 README，2026-07-25 查閱原文）

> 本資料僅作為參賽隊伍共同使用的**基準**價格資料。
>
> 除本資料包提供之 OHLCV 歷史資料外，其餘新聞、官方公告、鏈上資料、社群情緒、
> 總體經濟、政策與監管事件等資料，**均由參賽者自行取得**。

規則未明文禁止自行補充 OHLCV，亦未明文允許。但命題範例題型要求分析「過去兩週」，
而基準資料集止於執行日前 55 天——**僅用官方 CSV 在物理上無法回答該題型**。
團隊裁定採**雙軌**（R1-2），並將此問題列入待向主辦方確認事項。

---

## Requirements

### R1 — 資料時效：雙軌基準與序列化

**User Story:** 作為報告讀者，我要知道分析基於哪一天的價格資料、以及該資料是否涵蓋到今天，
這樣我才能判斷結論是否還適用於當下市場。

#### Acceptance Criteria

- **R1-1** WHEN price collector 啟動 THEN 系統 SHALL 從 OHLCV 序列末列動態計算 `as_of_date`，
  且 SHALL NOT 將 `as_of_date` 寫死為任何常數。
- **R1-2** WHEN 官方 CSV 末日早於執行日 1 天以上 THEN 系統 SHALL 呼叫 Binance
  `GET /api/v3/klines?interval=1d` 補齊缺口區段，並將補齊後序列作為所有技術指標的輸入。
- **R1-3** IF 缺口補齊失敗（網路／API／解析錯誤） THEN 系統 SHALL 降級為純 CSV 模式繼續執行，
  SHALL 在該筆證據的 `content_reference` 標註「⚠ 未能補齊，資料止於 {csv_end}，距執行日 {n} 天」，
  且 SHALL NOT 中斷 pipeline。
- **R1-4** WHEN 產生補齊後的價格證據 THEN `content_reference` SHALL 明確標示接縫，
  格式為「其中 {start} 起 {n} 日採 Binance 公開日線補齊，官方基準資料集止於 {csv_end}」。
- **R1-5** WHERE 官方 CSV 已涵蓋至執行日（主辦方當日提供更新資料集的情境）
  THEN 系統 SHALL 自動判定無缺口並跳過補齊，且 SHALL NOT 需要任何程式或設定變更。
- **R1-6** WHEN 產生技術指標證據 THEN 系統 SHALL 輸出近 30 天的**序列摘要**（起訖值、方向、
  期間極值與其發生日、目前於近 30 天分佈的百分位），SHALL NOT 僅輸出最新一天的單點數值。
- **R1-7** WHEN 產生技術指標證據 THEN 系統 SHALL NOT 將 30 天原始數列直接寫入
  `content_reference`（token 成本考量），僅寫入 R1-6 定義的摘要欄位。
- **R1-8** WHERE 長歷史指標（MA120 歷史位置、波動率全歷史百分位）
  THEN 系統 SHALL 繼續以官方 CSV 全歷史為計算基礎，SHALL NOT 改用 Binance 資料
  （其僅回溯約 1000 日，不足以取代 5 年基準）。
- **R1-9**（2026-07-28 新增，實作時發現的邊界；alanchang 已確認）
  WHEN 判定均線的「站上／跌破」位置 THEN 系統 SHALL 以**補齊後的最新收盤價**判定，
  SHALL NOT 以官方 CSV 末日收盤判定；均線**數值本身**仍依 R1-8 由官方 CSV 計算。
  且 SHALL 在證據文字同時揭露兩者的基準日。
  - **理由**：實測 BTC 的 MA120 = 72,613，用 CSV 末日收盤（73,674）判為「站上」，
    但 2026-07-26 實際收盤 65,400 是「跌破」——**位置判定與現實相反**。
    R1-8 的原意是保護長歷史指標的計算基準（共同基準語意），
    不是要求用過期價格做當下判讀，兩者不衝突。

### R2 — Horizon 分帶：讓推理層看得見時間尺度

**User Story:** 作為推理引擎，我要知道每筆證據代表多長的觀察窗，
這樣我才不會把「5 天情緒」和「5 年高位」當成互相矛盾。

#### Acceptance Criteria

- **R2-1** WHEN 定義 `EvidenceDraft` THEN schema SHALL 包含 `window_start: str | None`、
  `window_end: str | None`、`horizon_class: HorizonClass`，其中 `HorizonClass` 為五值列舉：

  | 值 | 窗長 | 標準粒度（R7-1） | 角色（相對主視野，見 R7-3） |
  |---|---|---|---|
  | `spot` | 當下快照或最近 1 日 | **日** | 依主視野動態判定 |
  | `short` | ≤ 10 天 | **10 日** | 依主視野動態判定 |
  | `medium` | 11–30 天 | **月** | 依主視野動態判定（**預設主視野**） |
  | `long` | 31–180 天 | **季** | 依主視野動態判定 |
  | `structural` | > 180 天 | **年** | 依主視野動態判定 |

  > 角色（當前訊號／結構脈絡）**不再寫死綁定於特定帶**，改由 R7-3 依當次主視野推導。
  > 當主視野為預設的 `medium` 時，推導結果與原設計完全相同
  > （`spot`/`short`/`medium` 為當前訊號，`long`/`structural` 為結構脈絡）。

- **R2-2** WHEN collector 產生 `EvidenceDraft` THEN 該 collector SHALL 自行標註
  `horizon_class` 與 `window_start`／`window_end`，且該標註 SHALL 為決定性的
  （由實際查詢參數／資料範圍推導），SHALL NOT 交由 LLM 推斷。
- **R2-3** IF collector 未顯式標註 `horizon_class` THEN schema SHALL 套用預設值 `spot`，
  且系統 SHALL 在 execution_log 記錄一筆 `status=skipped` 的標註缺漏警示。
- **R2-4** WHEN 組裝任何推理層 prompt 的證據清單 THEN `_format_evidence_list()` SHALL
  輸出 `window`（起訖）與 `horizon`（分帶）欄位，且 SHALL 附上分帶語意說明。
- **R2-5** WHEN 執行 Step B THEN prompt SHALL 要求模型輸出三段而非兩段：
  `consistent_signals`、`contradictions`、`structural_context`。
- **R2-6** WHEN 判定 `contradictions` THEN prompt SHALL 明確約束「僅同 horizon 帶內、
  或同屬**當前訊號**（horizon ≤ 主視野，見 R7-3）的證據之間的衝突才算矛盾」。
- **R2-7** WHEN 當前訊號與結構脈絡出現方向差異 THEN 模型 SHALL 將其寫入
  `structural_context` 而非 `contradictions`，並 SHALL 以「位置關係」措辭描述
  （例：「兩週情緒轉強，但價格仍處 5 年分佈第 88 百分位，屬高位反彈而非底部啟動」）。
- **R2-8** WHEN 計算信心 THEN `structural_context` 條目 SHALL NOT 計入矛盾懲罰，
  且 SHALL 作為 `invalidation_conditions` 的輸入提示。
- **R2-9** WHERE 既有 `evidence.json`（無 horizon 欄位）被重新載入
  THEN 系統 SHALL 以預設值正常運作，SHALL NOT 拋出驗證錯誤。

### R3 — 三維可解釋信心：從「資料的信心」改為「AI 對自己這份回答的信心」

**User Story:** 作為報告讀者，我要看到 88 分是怎麼算出來的、哪些因素拉高或拉低，
而不是只看到一個「High」。

#### Acceptance Criteria

- **R3-1** WHEN 計算 Data Confidence THEN 系統 SHALL 對**六類** source_type
  （含 `derivatives`，修正 D7）各給 100/6 分，每類依三檔評分：

  | 狀態 | 得分比例 |
  |---|---|
  | 完整（達 `window_policy.md` 該類窗口要求的筆數與窗長） | 100% |
  | 部分（有資料但筆數或窗長不足） | 60% |
  | 缺失（該類零證據） | 0% |

- **R3-2** WHEN 計算 Data Confidence THEN 該計算 SHALL 為決定性的（僅依證據統計），
  SHALL NOT 呼叫 LLM。
- **R3-3** WHEN 執行 Step B THEN prompt SHALL 額外要求輸出 `direction_matrix`，
  每筆為 `{"source_type": str, "direction": -1|0|1, "basis": [evidence_ids]}`，
  且模型輸出 SHALL 限縮於 `-1|0|1` 三值，SHALL NOT 允許自由文字或連續分數。
- **R3-4** WHEN 計算 Signal Consensus THEN 系統 SHALL 僅納入**當前訊號**
  （horizon ≤ 主視野，見 R7-3）的證據所對應的 source_type，
  SHALL NOT 納入結構脈絡（避免假矛盾由此路徑復活）。
- **R3-5** WHEN 計算 Signal Consensus THEN 公式 SHALL 為**兩兩一致度**：
  `100 × (1 − mean(|dᵢ − dⱼ| for all pairs) / 2)`，夾在 0–100。
  - ✅ **2026-07-28 定案**（原暫定的線性 stdev 映射已否決）。實算 729 種組合後，
    線性映射有兩個致命傷：6 來源中 5 個同向只給 25 分、且 35.7% 的情境擠在
    0–20 分區間失去鑑別度。候選 `100×|mean|` 更差（53.9% 擠低分區，且「全部中性」
    給 0 分但那其實是完美一致）。逐案比較見 design.md §3.6.2。
  - WHEN 所有來源皆為中性（direction 全 0） THEN 分數 SHALL 為 100
    （一致無方向仍是一致），SHALL NOT 視為零共識。
- **R3-6** WHEN 計算 Evidence Strength THEN 系統 SHALL 由既有 `source_weight`
  （R12 四因子產出）與各類覆蓋度推導，SHALL NOT 引入 LLM 主觀評分。
- **R3-7** WHEN 計算 Base 信心 THEN 公式 SHALL 為
  `0.4 × DataConfidence + 0.4 × SignalConsensus + 0.2 × EvidenceStrength`。
- **R3-8** WHEN 執行 Step D THEN prompt SHALL 要求裁判輸出 `debate_adjustment`
  （整數，範圍 **−15 ~ +5**）與 `debate_adjustment_reason`（非空字串）。
- **R3-9** IF `debate_adjustment` 超出 −15 ~ +5 THEN 系統 SHALL 夾到邊界值
  並於 execution_log 記錄原始值，SHALL NOT 中斷流程。
- **R3-10** IF `debate_adjustment_reason` 為空 THEN 系統 SHALL 強制
  `debate_adjustment = 0`（無理由不得調整）。
- **R3-11** WHEN 計算最終信心 THEN 公式 SHALL 為 `Base + DebateAdjustment`，夾在 5–95。
- **R3-12** WHEN 產生報告 THEN 系統 SHALL 輸出 Confidence Breakdown 表
  （三維分數＋各自權重＋Base＋Debate Adjustment＋Final）。
- **R3-13** WHEN 產生報告 THEN 系統 SHALL 輸出「Why this confidence?」條列，
  且該條列 SHALL 由扣分項決定性反查生成（每個未滿分項目自動產生一行說明），
  SHALL NOT 由 LLM 撰寫。
- **R3-14** WHEN 計算信心 THEN 所有中間值 SHALL 寫入 execution_log 的
  `metrics`（`layer=L5_conclusion`），可逐項對帳。
- **R3-15** WHERE Step B 未能產出 `direction_matrix`（解析失敗／fallback 路徑）
  THEN 系統 SHALL 以 `SignalConsensus = 50`（中性）計算並於報告揭露該降級。

### R4 — 權重進入辯論：讓 0.3 反駁不了 0.9

**User Story:** 作為辯論參與者，我要知道哪些證據來源比較可信，
這樣我才不會用一則匿名論壇貼文去推翻交易所官方數據。

#### Acceptance Criteria

- **R4-1** WHEN 組裝證據清單 THEN `_format_evidence_list()` SHALL 輸出
  `weight`（數值）與其分級標籤（A+/A/B+/B/C/D，取自 `static/source_reputation.json`）。
- **R4-2** WHEN 組裝 `SYSTEM_PROMPT` THEN 其 SHALL 包含權重對抗規則：
  低權重證據（< 0.5）不足以單獨推翻高權重證據（> 0.8）；
  若要如此主張，SHALL 額外說明該高權重來源為何在此具體情境下不適用。
- **R4-3** WHEN 執行 Step C1/C2（辯論） THEN prompt SHALL 要求論證中引用證據時
  一併意識到權重差距，SHALL NOT 將不同權重的證據當作勢均力敵。
- **R4-4** WHEN 執行 Step D（裁判） THEN prompt SHALL 要求裁判在評估反方批評是否成立時
  一併考量雙方所引用證據的權重分佈。

### R5 — 語氣模板：可切換的表達層

**User Story:** 作為 demo 觀眾，我希望報告除了專業版之外還有一個好懂的白話版，
但不希望它變成投資喊單。

#### Acceptance Criteria

- **R5-1** WHEN 執行 CLI 或 Web UI THEN 系統 SHALL 支援 `--tone` 參數，
  值域為 `professional`（預設）與 `plain`。
- **R5-2** WHEN 切換 tone THEN 其 SHALL 僅影響報告表達層，
  SHALL NOT 影響任何推理層 JSON 輸出、證據引用或信心計算結果。
- **R5-3** 系統 SHALL NOT 模仿任何具名真實人物（含 YouTuber、分析師、名人）的
  身分、名號或個人標誌性話術。
- **R5-4** WHERE tone 為 `plain` THEN 系統 SHALL 維持與 `professional` 完全相同的
  買賣建議禁令（不得給進場價、停損點、明確買賣指示），
  SHALL NOT 因語氣放寬而鬆綁 `SYSTEM_PROMPT` 第 5 條。
- **R5-5** WHERE tone 為 `plain` THEN 表達層 SHALL 採用「先講結論、生活化比喻、
  口語短句、關鍵數字強調」的結構，且 SHALL 保留完整的證據 id 引用。

### R6 — 相容性與穩定性（跨所有需求的約束）

#### Acceptance Criteria

- **R6-1** WHEN 本規格任一新功能失敗 THEN 系統 SHALL 降級而非中斷，
  且 SHALL 在 execution_log 記錄降級原因。
- **R6-2** WHEN 完成本規格 THEN 單次執行總時長 SHALL 維持在 15 分鐘硬限之內，
  目標 10 分鐘（新增的 Binance klines 呼叫為 5 幣種各 1 次，預估增加 < 5 秒）。
- **R6-3** WHEN 完成本規格 THEN 既有 269 個測試 SHALL 全數通過
  （允許因公式變更而修改斷言，但 SHALL NOT 刪除既有測試案例）。
- **R6-4** WHEN 修改信心公式 THEN 舊的 `compute_confidence_score()` 相關測試
  SHALL 被改寫為新公式的等價驗證，SHALL NOT 直接刪除。

### R7 — 多尺度資料供給與動態主視野

> 2026-07-28 新增。來源：alanchang 決策⑥。
> 起因是隊友 vic 盤點發現 `raw_data/`（Ken 落地的衍生品／期限結構／CME COT／
> 鏈上歷史 CSV）**沒有任何一行程式讀它**，對 LLM 推理鏈一筆都沒進去（STATUS.md 第 10 項）。
> alanchang 確認這是誤會而非刻意設計，並提出更根本的需求：
> **agent 應該對同一個標的同時具備短／中／長期三種尺度的資料觀念**，
> 這樣使用者問「最近兩週」或「最近一年」時，各自都有對應尺度的原始資料可參考。

**User Story:** 作為使用者，當我問「最近一年 BTC 表現如何」時，
我希望 agent 是用年尺度的資料回答，而不是拿兩週的資料硬套；
反過來問「最近兩週」時也不該被五年的結構資料主導。

#### Acceptance Criteria

- **R7-1** WHEN 定義資料粒度 THEN 系統 SHALL 採用五檔標準粒度，並與 horizon 五帶一一對應：

  | 標準粒度 | 回看天數 | `horizon_class` |
  |---|---:|---|
  | 日 | 1 | `spot` |
  | 10 日 | 10 | `short` |
  | 月 | 30 | `medium` |
  | 季 | 90 | `long` |
  | 年 | 365 | `structural` |

- **R7-2** WHEN 分類題目 THEN 系統 SHALL 從題目文字決定性偵測時間範圍
  並據此設定該次執行的**主視野**；IF 題目未明示時間範圍 THEN 主視野 SHALL 預設為 `medium`。
  - 偵測 SHALL 為規則式（關鍵字 → 天數 → 帶），SHALL NOT 額外呼叫 LLM。
- **R7-3** WHEN 判定證據角色 THEN 系統 SHALL 依當次主視野動態推導：
  `horizon ≤ 主視野` → **當前訊號**；`horizon > 主視野` → **結構脈絡**。
  SHALL NOT 將角色寫死綁定於特定帶。
- **R7-4** WHERE `price` collector（資料來自本地 CSV，零 API 成本）
  THEN 其 SHALL 覆蓋全部五檔標準粒度，各自產出獨立的序列摘要證據。
- **R7-5** WHERE 其他 collector（受免費 API 額度與 15 分鐘時間預算限制）
  THEN 其 SHALL 盡力覆蓋（僅覆蓋必要且成本可負擔的粒度），
  且未覆蓋的粒度 SHALL 反映在 R3-1 的 Data Confidence 扣分，SHALL NOT 靜默忽略。
- **R7-6** WHEN 主視野落在某個帶 THEN 該帶 SHALL 至少有一筆證據；
  IF 該帶完全無證據 THEN 系統 SHALL 在報告明確揭露
  「本次主視野為 {帶}，但該尺度無可用證據，判斷實際依據的是 {實際有資料的帶}」。
- **R7-7** WHEN 產生報告 THEN 系統 SHALL 揭露本次的主視野與其判定依據
  （題目中的哪段文字觸發了該判定）。
- **R7-8** WHERE `raw_data/` 下已落地的歷史資料（Ken 的 prototype 產出）
  THEN 系統 SHALL 定義明確的讀取介面契約供 collector 取用；
  IF 檔案缺失或格式不符 THEN collector SHALL 降級為僅用即時 API，SHALL NOT 中斷（R6-1）。
  - **範圍註記**：`raw_data/` 的接線由 alanchang 負責（決策⑥），
    本規格只定義 agent 端需要什麼，不規範檔案產生流程。

### R8 — 訊號有效期、重要性係數與蒐集層尺度適配

> 2026-07-30 新增。來源：Ken 的「HOYA Research Agent v2」架構提案（他已看過 R7，
> 分支基準點含 Phase 8），加上 vic 的 Phase 4 code review 發現。
>
> **本條的存在意義是「把 v2 提案的價值用加法交付，而不是重寫架構」。**
> Ken 的 9 層提案若照實作等於重寫 pipeline，賽前時程無法承受；但其中四項
> 可以用「在既有位置加欄位／加參數」完成，且**這四項剛好一次解掉四個已知問題**：
>
> | 加這個 | 順便解掉 |
> |---|---|
> | `persistence`／`decay` | vic 的「Data Confidence 對 horizon 盲目」 |
> | `base_importance` 靜態表 | Ken 自己擔心的「Layer A 單獨做會把權重壓平成 3 個值」 |
> | 同上，依題型調整 | 「social 抓不到就扣 9.3 分」的六類等權問題 |
> | 主視野傳到 collector | Ken 指出的真缺口：問「過去一年」時 Reddit 仍抓 `t=week` |

**User Story:** 作為推理引擎，我要知道一筆證據的**訊號還有效多久**（而不只是它涵蓋多長的窗），
這樣我在回答「兩週後如何」時，才不會把一個 3 天後就衰減掉的訊號當成同等份量的依據。

#### 核心觀念釐清（本條的前提）

`horizon_class`（R2-1）與 `persistence`（本條）是**兩個不同的東西**，先前混為一談：

| 欄位 | 回答的問題 | funding 費率百分位的例子 |
|---|---|---|
| `horizon_class` | 這筆**觀察涵蓋多長的窗** | 90 筆 × 8h ≈ 30 天 → `medium` |
| `persistence` | 這個**訊號還有效多久** | 預測有效期約 **1–3 天** → `short` |

#### Acceptance Criteria

- **R8-1** WHEN 定義 `EvidenceDraft` THEN schema SHALL 新增
  `persistence: Persistence`（`short`／`medium`／`long`）與
  `decay: DecayPattern`（`fast`／`slow`），兩者 SHALL 由 collector 決定性標註
  （比照 R2-2 的 `horizon_class`，不交由 LLM 推斷），且 SHALL 有預設值以維持
  向後相容（R2-9 同理）。
- **R8-2** WHEN 計算 Data Confidence THEN 系統 SHALL 納入「該類證據的有效期是否
  覆蓋本次主視野」；IF 某類證據雖筆數與窗長達標、但其 `persistence` 明顯短於
  主視野 THEN 該類 SHALL NOT 判為「完整」。
  - **這條同時修掉 vic 指出的缺陷**：現行 `compute_data_confidence()` 只看
    筆數與最長窗長，完全不讀 `horizon_class`。實測：問「過去一年」時，
    19 筆全是 17 天窗的證據仍判六類「完整」拿 100 分，而同一份報告開頭卻
    寫著「⚠ 主視野無可用證據」——**報告自相矛盾**。
- **R8-3** WHEN 計算證據優先度 THEN 系統 SHALL 讀取
  `static/signal_importance.json` 的靜態重要性係數（Ken 提案的 Layer B 簡化版），
  且該表 SHALL 為人工訂定的常數，SHALL NOT 依賴歷史回測資料。
  - 介面比照回測版設計，日後要換成回測值時**只換資料不改程式**。
- **R8-4** WHEN 組裝推理層 prompt 的證據清單 THEN `_format_evidence_list()`
  SHALL 依優先度排序（高優先在前），SHALL NOT 新增獨立的 Prioritizer 層。
  - 優先度輸入：`source_weight` × `base_importance` × 主視野匹配度。
- **R8-5** WHEN orchestrator 呼叫 collector THEN SHALL 傳入本次的 `primary_horizon`；
  各 collector SHALL 盡力依該尺度調整查詢窗（例如問「過去一年」時 social 改抓
  `t=year`、news 放寬窗口），IF 該來源無法調整 THEN SHALL 維持既有行為，
  SHALL NOT 因此失敗（R6-1）。
- **R8-6** WHEN 本條任一新欄位缺失或計算失敗 THEN 系統 SHALL 退回 R7 既有行為，
  SHALL NOT 中斷 pipeline。

## 非目標（Out of Scope）

- 不改動 R12 四因子信譽公式本身（僅**使用**其產出的 `source_weight`）
- 不改動多輪辯論的收斂機制（`has_new_points`／`MAX_DEBATE_ROUNDS`）
- 不新增付費資料源；所有新增端點必須免 key
- 不以 Binance 資料取代官方 CSV 作為長歷史基準（R1-8）
- 不做具名人物風格模仿（R5-3）

### 明確不採納 Ken v2 提案的以下五項（2026-07-30 裁定）

這五項各有道理，但**都要重寫已驗證通過的層**，賽前時程無法承受。
記錄於此是為了「決定過而不做」，不是「忘了做」——賽後可重啟。

| 項目 | 不做的理由 |
|---|---|
| **Evidence Graph**（supports/contradicts 圖） | Step B 已產出扁平版（`consistent_signals`／`contradictions`／`structural_context`）。升級成圖需要新的一層與新的資料結構 |
| **Market Hypothesis 取代 Bull/Bear** | 重寫整個辯論層，而該層 2026-07-28 剛通過三題型真實驗證（零失敗）。且「Continuation vs Challenge」套在假設驗證題型上會很怪——那題型本來就有明確的待驗證陳述 |
| **Judge 不算分，只回答定性問題** | 與 R3（可解釋信心分數）直接衝突，那是需求方第三大點的明確要求。**且現行設計已經是分層的**：Judge 給定性評析＋`debate_adjustment`，決定性公式算 base——Ken 要的東西其實已經在了，需向他澄清 |
| **Factor Interpreter 全面重構** | 要求每筆證據結構化成 Direction／Reason／Importance，等於重寫全部 7 個 collector 的輸出格式 |
| **Evidence Scope／Market Regime** | 需要先做「當前是趨勢盤還是震盪盤」的 regime 判定器，那本身就是一個獨立題目 |

## 待確認事項

| # | 問題 | 對象 | 影響 | 狀態 |
|---|---|---|---|---|
| 1 | 比賽當日是否提供更新至比賽日的資料集？ | 主辦方 | 若是，R1-2 自動不觸發（R1-5 已涵蓋），無需改碼 | ⬜ 未問 |
| 2 | 若否，自行補充公開來源近期 OHLCV 是否符合規則？ | 主辦方 | 若不允許，R1-2 需移除，改為僅在報告揭露斷層 | ⬜ 未問 |
| 3 | 各類「完整」的判定門檻（R3-1 用） | Ken | 影響 Data Confidence 三檔評分的分界 | 🟡 暫用 design.md §3.6.1 暫定值 |
| 4 | Signal Consensus 公式鑑別度（R3-5） | alanchang | 線性映射會讓分數塌到底部 | ✅ **2026-07-28 定案採兩兩一致度**，逐案比較見 design.md §3.6.2 |

## 團隊決策記錄（2026-07-28）

| # | 議題 | 裁定 | 影響本規格之處 |
|---|---|---|---|
| ① | vic 實作時發現均線位置判定會與現實相反 | **同意其解法** | 正式化為 **R1-9** |
| ② | Ken 新增的子來源缺 horizon 標註 | **由 alanchang 補** | tasks.md Task 0.2；對照表見 design.md §3.2.1 |
| ③ | `price.py` 合併衝突（Ken 波動率壓縮 vs vic 重構） | **兩邊都留，alanchang 手動解** | tasks.md Task 0.1 |
| ④ | Ken 的權重公式 Layer A/B 改版 | **先做 Layer A，Layer B 保留說明不實作** | design.md ADR-4 補充；本規格僅消費 `source_weight`，不受 Layer A 改版阻塞 |
| ⑤ | Signal Consensus 公式鑑別度 | **2026-07-28 實算 729 種組合後定案採兩兩一致度** | R3-5 改寫；design.md §3.6.2 留完整選型紀錄 |
| ⑥ | `raw_data/` 未接進 agent | **確認是誤會，alanchang 處理**；並提出多尺度資料需求 | 新增 **R7** |

> 待確認事項 1、2 應併入 `STATUS.md` 待辦第 8 項「向主辦方確認比賽當日執行環境」一併詢問。
> 無論答案為何，R1-2 先做都不會白做——補齊邏輯為「有缺口才補」，主辦方若給新資料即自動不觸發。

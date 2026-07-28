# Design Document: Horizon-Aware 推理與可解釋信心

> 對應 `requirements.md`（R1–R6）。執行清單見 `tasks.md`。
> 設計拍板日：2026-07-25（alanchang 確認全部採用推薦方案）

## 1. 設計總覽

### 1.1 核心洞察

現行系統的三個症狀（辯論雙方沒信心／信心分數不可解釋／技術面描述過時市場）
**同源於一個根因：時間維度資訊在證據層被抹平。**

```
現況（有問題）：
  collector ──[丟失窗口資訊]──▶ Evidence(fetched_at only)
                                      │
                                      ▼
                            Step B 攤平比對 ──▶ 假矛盾
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                                   ▼
              辯論雙方互相讓步                  confidence 扣分
              （「都沒信心」）                  （contradiction_penalty）

修正後：
  collector ──[標註 window+horizon]──▶ Evidence(window_start/end, horizon_class)
                                            │
                                            ▼
                              Step B 分帶比對
                                 ├─▶ contradictions（同帶）──▶ 正常扣分
                                 └─▶ structural_context（跨帶）──▶ 不扣分，
                                                                   改餵 invalidation
```

### 1.2 三大改動面

| 面向 | 現況 | 目標 | 需求 |
|---|---|---|---|
| **資料面** | 技術面止於 CSV 末日；指標為單點 | 雙軌補齊至執行日；指標序列化 | R1 |
| **推理面** | 證據無尺度；權重不可見 | 證據帶 horizon＋weight 進 prompt | R2, R4 |
| **信心面** | LLM 主觀標籤 ± 資料懲罰 | 三維可複現 Base ＋ 辯論調整 | R3 |

## 2. 架構決策記錄（ADR）

### ADR-1：雙軌資料（保留官方 CSV 為基準，Binance 補缺口）

**決策**：官方 CSV 作為長歷史基準（`long`/`structural` 指標的唯一來源），
Binance 公開日線僅補「CSV 末日 → 執行日」的缺口，供 `medium` 帶指標使用。

**理由**：
1. **規則保險**——命題數據集 README 稱該 CSV 為「共同基準」。雙軌可證明長歷史基準
   100% 來自官方，僅補其未涵蓋期間；即使評審採最嚴格解讀，也站得住腳。
2. **物理必要**——命題範例題型要求分析「過去兩週」，而基準資料集止於執行日前 55 天。
   不補齊則無法回答題目。
3. **技術限制**——Binance `klines` 以 `limit=1000` 僅回溯至 2023-10-30（實測），
   不足以取代 5 年 CSV，本來就只能接續而非取代。
4. **加分項**——「主動偵測官方資料集與執行日的落差、補齊並在報告揭露接縫」
   本身即是資料嚴謹度的展示，優於默默使用過期資料。

**否決的替代方案**：
- ❌ *全面改用 Binance*：喪失 5 年歷史（波動率全歷史百分位、MA120 需要），且違背「共同基準」精神。
- ❌ *維持純 CSV，只在報告揭露落差*：技術面指標仍描述已不存在的市場，
  且無法回答「過去兩週」題型，是迴避不是解決。

**風險與緩解**：主辦方可能要求僅用官方資料 → R1-5 已設計為「有缺口才補」，
若當日提供更新資料集則自動不觸發；若明文禁止，移除 `_fetch_gap_klines()` 單一函式即可回退。

---

### ADR-2：`horizon_class` 由 collector 標註，不由 LLM 推斷

**決策**：每個 collector 在建構 `EvidenceDraft` 時自行填入
`horizon_class`／`window_start`／`window_end`。

**理由**：
1. collector 最清楚自己打了什麼端點、帶了什麼 `limit`／`interval`／`t=week` 參數，
   窗長是**已知事實**而非待推論資訊。
2. 決定性 → 可單元測試、可複現。LLM 推斷會隨機出錯，且錯誤會傳播進矛盾判定與信心計算。
3. 成本為零（不增加 LLM 呼叫）。

**否決的替代方案**：
- ❌ *讓 Step A 依 `fetched_at` 與內容推斷*：不可複現，且正是我們要修的「資訊已遺失」問題的變體。
- ❌ *在 orchestrator 依 `source_type` 統一套表*：同一 collector 內不同子來源窗長差異極大
  （如 `derivatives.py` 的 CME COT 12 週 vs 期貨到期結構當下快照），套表會製造新的錯標。

---

### ADR-3：Direction Matrix 由 Step B 的 LLM 產出，但輸出限縮為 −1/0/+1

**決策**：Signal Consensus 的方向表態由 Step B 順帶輸出，不寫死規則。

**理由**：
1. 寫死規則（如 `RSI > 70 → bearish`）在加密市場太脆——同一個 RSI 70
   在趨勢盤與震盪盤語意相反，需要上下文。
2. 輸出限縮在三值 → 隨機性極低，可複現性可接受；不給自由文字或連續分數，
   避免 LLM 用「0.73 偏多」這類無法驗證的精度製造假精確。
3. 不增加額外 LLM 呼叫（掛在既有 Step B 上）。

**否決的替代方案**：
- ❌ *純規則引擎*：脆弱，且會與辯論層的判斷產生第二套互相矛盾的方向結論。
- ❌ *獨立一次 LLM 呼叫*：增加時間成本，違反 R6-2 的 15 分鐘硬限預算。

**降級路徑**：解析失敗時 `SignalConsensus = 50`（中性），並在報告揭露（R3-15）。

---

### ADR-4：Evidence Strength 復用 `source_weight`，不引入 LLM 主觀評分

**決策**：`EvidenceStrength` 由 R12 四因子產出的 `source_weight` 與各類覆蓋度推導。

**理由**：
1. 需求方（alanchang）的核心訴求是「可解釋、可複現」。若讓 LLM 給
   「Price=90, Social=60」這類主觀分，等於在剛拆掉的主觀基底（D6）旁邊裝一個新的。
2. R12 已經投入完整的四因子信譽體系（新鮮度×來源等級×覆蓋度×dedup_penalty），
   那正是「這個訊號有多強」的既有答案，重造輪子只會產生兩套打架的權威度定義。
3. 決定性 → 可測試。

**否決的替代方案**：
- ❌ *LLM 給 0–100 強度分*：不可複現，且與 `source_weight` 語意重疊會互相矛盾。

**與 Ken「權重公式 Layer A/B 改版」的關係（2026-07-28 補充，決策④）**：

Ken 提案把四因子拆成 `w = Layer A（資料品質）× Layer B（市場影響力）`，
並把 `static/source_reputation.json` 從 8 級改 3 級。團隊裁定：
**先做 Layer A，Layer B 保留設計說明但不實作。**

對本規格的影響：
- **不阻塞**——ADR-4 只**消費** `source_weight` 的數值，不關心它怎麼算出來。
  Layer A 落地後 Evidence Strength 的分數尺度會位移，但公式不用改。
- **有一件事要注意**：Layer A 把 `social` 定為 0.5、把官方源定為 1.0，
  級距比現行 8 級表更陡。這會讓 Evidence Strength 的類別間差異放大，
  屬預期行為，但 Layer A 落地後應重跑一次 §3.6.3 的分數分佈確認合理。
- Layer B（歷史回測相關性）若未來要做，會引入「市場影響力」這個**新維度**，
  屆時需要重新檢視它與 Evidence Strength 是否語意重疊——但目前不做，不需處理。

---

### ADR-7：動態主視野與多尺度資料供給（2026-07-28 新增，決策⑥）

**決策**：主視野由**題目時間範圍動態決定**（非寫死 `medium`）；
證據的「當前訊號／結構脈絡」角色改為**相對主視野推導**；
`price` collector 覆蓋五檔標準粒度（日／10 日／月／季／年）。

**理由**：
1. **原設計有個沒被發現的假設**——把主視野寫死 `medium` 等於假設題目永遠問「兩週」。
   若現場抽到「最近一年 BTC 表現如何」，五年結構資料會被歸為「結構脈絡」而排除在
   共識投票外，**反而是最該用的資料被降級**，這是原設計會在賽場上翻車的地方。
2. **角色推導規則可以優雅泛化**：`horizon ≤ 主視野` = 當前訊號、`> 主視野` = 結構脈絡。
   當主視野 = `medium` 時，推導結果與原設計**完全相同**，是嚴格的超集，不破壞既有行為。
3. **五檔粒度與五帶天然一一對應**（日/10日/月/季/年 → spot/short/medium/long/structural），
   不需要新造分類體系。
4. **`price` 全覆蓋幾乎免費**——資料來自本地 CSV，只是多算幾個窗口的純 Python 運算，
   不增加任何 API 呼叫，不吃 15 分鐘預算。

**否決的替代方案**：
- ❌ *讓 LLM 判斷題目的時間範圍*：可規則化的事不該花 LLM 呼叫，且不可複現。
- ❌ *所有 collector 都做五檔*：news/social 本質上沒有「年」尺度的資料
  （RSS 不會給你一年前的新聞情緒），硬做會產生假資料。故 R7-5 只要求「盡力而為」，
  缺口誠實反映在 Data Confidence 扣分。

**band 邊界的微調**：`short` 由「≤ 7 天」放寬為「≤ 10 天」以容納「10 日」標準粒度。
已核對 vic 已實作的標註，此調整**不影響任何一筆現有標註**
（social 7 天仍是 `short`，news 14 天仍是 `medium`）。

---

### ADR-5：信心 = 可複現 Base ＋ 不對稱辯論調整（−15 ~ +5）

**決策**：把「可解釋公式」（需求三）與「辯論後才定案」（需求四）**分層**而非二選一。

```
Final = Base(0.4·Data + 0.4·Consensus + 0.2·Strength)  +  DebateAdjustment(−15 ~ +5)
        └────────── 決定性、可複現 ──────────┘            └─── LLM 裁判，需附理由 ───┘
```

**理由**：
1. 兩個需求本身有張力：一個要「每次跑同一套分析得到一致結果」，
   一個要「透過辯論後才知道信心」。分層讓兩者都成立且各自可稽核。
2. **範圍不對稱是刻意設計**——辯論只能大幅下修、小幅上調。
   若允許辯論大幅加分，LLM 的自我感覺良好會直接侵蝕分數公信力
   （這正是 D6 現況的失敗模式，不能換個位置重演）。
3. 無理由不得調整（R3-10）→ 強制可稽核。

**否決的替代方案**：
- ❌ *純公式，無辯論調整*：辯論層的產出對最終信心零影響，違背需求四。
- ❌ *純 LLM 自報最終信心*：即 D6 現況，不可複現。
- ❌ *對稱範圍 ±15*：見理由 2。

**已知副作用與處理**：Base 為三維加權，實務上多落在 60–85；
再扣辯論調整後最終分數會系統性低於「範例 88 分」。這是**正確的**——
88 分應該保留給資料六類齊全、方向高度一致、且辯論未發現實質漏洞的情境。
不為了好看而抬高基準。

---

### ADR-6：不做具名人物風格模仿，改做雙語氣模板

**決策**：實作 `--tone professional|plain`，`plain` 吸收科普型內容創作者的
**結構優點**（先講結論、生活化比喻、口語短句），但不掛任何人名。

**理由**：
1. **評審風險**——命題要求專業分析報告，模仿網紅語氣可能被判定不專業。
2. **人格權／歸屬風險**——掛真人名號的 AI 生成內容若出錯，責任歸屬複雜。
3. **規則衝突**——網紅語氣天然滑向「所以現在該買嗎」，但 `SYSTEM_PROMPT` 第 5 條
   明文禁止買賣建議。R5-4 明確要求 `plain` 不得放寬此禁令。
4. Demo 效果不打折——當場切換兩種語氣同樣是亮點。

---

## 3. 詳細設計

### 3.1 Schema 變更（`agent/schemas.py`）

```python
class HorizonClass(str, Enum):
    """單筆證據代表的時間尺度分帶。由 collector 決定性標註（ADR-2）。"""
    SPOT = "spot"              # 當下快照
    SHORT = "short"            # ≤7 天
    MEDIUM = "medium"          # 8–30 天（主視野）
    LONG = "long"              # 31–180 天
    STRUCTURAL = "structural"  # >180 天


# 由短到長的排序，角色推導與比較大小都以此為準（ADR-7）
HORIZON_ORDER = [SPOT, SHORT, MEDIUM, LONG, STRUCTURAL]

# 預設主視野；實際主視野由 resolve_primary_horizon() 依題目動態決定（R7-2）
DEFAULT_PRIMARY_HORIZON = HorizonClass.MEDIUM


def is_current_signal(h: HorizonClass, primary: HorizonClass) -> bool:
    """horizon ≤ 主視野 → 當前訊號；> 主視野 → 結構脈絡（R7-3）。"""
    return HORIZON_ORDER.index(h) <= HORIZON_ORDER.index(primary)
```

> **相容性**：`CURRENT_SIGNAL_HORIZONS`／`STRUCTURAL_HORIZONS` 兩個常數集合
> （vic 於 Phase 1 已實作）保留作為「主視野 = `medium`」時的預設分組，
> 但**所有新程式碼應改用 `is_current_signal()`**。當 primary = `medium` 時，
> 兩者結果完全相同，故既有測試不會失敗。

### 3.1.1 主視野判定（R7-2，決定性規則，不呼叫 LLM）

```python
# 關鍵字 → 回看天數；first-match-wins，比對順序由長詞到短詞避免「一年」被「年」搶先
QUESTION_HORIZON_KEYWORDS = [
    (r"過去一年|近一年|最近一年|12\s*個月|一整年", 365),
    (r"過去半年|近半年|最近半年|6\s*個月",         180),
    (r"過去一季|近一季|最近一季|3\s*個月|季度",      90),
    (r"過去一個?月|近一個?月|最近一個?月|30\s*天",   30),
    (r"過去兩週|近兩週|最近兩週|兩個?星期|14\s*天",  14),
    (r"過去一週|近一週|最近一週|7\s*天",             7),
    (r"今天|當前|目前|現在|即時",                    1),
]

def resolve_primary_horizon(question: str) -> tuple[HorizonClass, str]:
    """回傳 (主視野, 觸發判定的題目片段)。無命中則回 (MEDIUM, "")。"""
```

天數 → 帶的映射沿用 R2-1 的邊界（`≤1`→spot、`≤10`→short、`≤30`→medium、
`≤180`→long、其餘→structural）。回傳的片段供 R7-7 在報告揭露判定依據。

`EvidenceDraft` 新增三欄位（皆有預設值，滿足 R2-9 向後相容）：

```python
    window_start: str | None = None   # 觀察窗起點（ISO date）
    window_end: str | None = None     # 觀察窗終點；≠ fetched_at
    horizon_class: HorizonClass = HorizonClass.SPOT   # 預設 spot（R2-3）
```

> **不新增 validator 強制 window_start ≤ window_end**：部分 spot 類證據兩者皆為 None，
> 且驗證失敗會中斷 collector，違反 R6-1。改為在 `orchestrator` 分配 id 時檢查並記 log。

### 3.2 各 Collector 的 horizon 標註對照表（R2-2 實作依據）

依 `raw_data/_meta/window_policy.md` 的既有窗口設計逐項對應：

| Collector | 子來源 | window | `horizon_class` |
|---|---|---|---|
| `price` | OHLCV 近 30 日序列摘要 | `as_of-29` ~ `as_of` | `medium` |
| `price` | 技術指標 SMA/RSI/波動率/量能 | 同上 | `medium` |
| `price` | MA120 位置、波動率全歷史百分位 | CSV 首日 ~ `as_of` | `structural` |
| `price` | CoinGecko/CryptoCompare 即時報價 | None | `spot` |
| `price` | Binance 永續基差 | None | `spot` |
| `onchain` | 即時快照（區塊高度/Gas/TPS） | None | `spot` |
| `news` | RSS/HTML 近 14 天項目 | `today-13` ~ `today` | `medium` |
| `social` | Reddit `t=week` | `today-6` ~ `today` | `short` |
| `macro` | Fear & Greed 30 天百分位 | `today-29` ~ `today` | `medium` |
| `macro` | 美元匯率快照 | None | `spot` |
| `derivatives` | 費率擁擠度百分位（90 筆×8h≈30 天） | `today-29` ~ `today` | `medium` |
| `derivatives` | OI×價格四象限（30h 趨勢） | `today-1` ~ `today` | `spot` |
| `derivatives` | 多空帳戶比（30h 趨勢） | `today-1` ~ `today` | `spot` |
| `derivatives` | 期貨到期結構 | None | `spot` |
| `derivatives` | **CME COT 12 週** | `today-83` ~ `today` | **`long`** |
| `derivatives` | 選擇權 IV/Skew（30 天到期） | None | `spot` |
| `derivatives` | CEX-DEX 費率差 | None | `spot` |
| `relative` | 雙幣相對強弱 90 天位置 | `as_of-89` ~ `as_of` | `long` |

> **標註重點**：`price` 的 MA120／波動率全歷史百分位與 `derivatives` 的 CME COT
> 是最主要的假矛盾來源（D2/D4），務必正確標為 `structural`／`long`。

#### 3.2.1 Ken 於 `d8e1b15` 新增、尚未標註的子來源（2026-07-28，決策②）

vic 的 Phase 2 標註是從 `0a40297` 分岔，早於 Ken 這批 prototype 併回，
因此下列四筆合併後會吃預設值 `spot`。**由 alanchang 補標（tasks.md Task 2.11）**：

| Collector | 子來源 | 正確標註 | 錯標成 `spot` 的後果 |
|---|---|---|---|
| `price` | 波動率壓縮（20 天標準差 vs 近 90 天滾動分佈） | **`structural`** | ⚠ **最嚴重**——90 天滾動窗被當成當下訊號，正是本規格要修的那類假矛盾 |
| `macro` | 供給節奏日曆（halving／unlock 等排定事件） | `long` | 未來事件被當成當下訊號進共識投票 |
| `onchain` | BTC/ETH 歷史趨勢序列 | `medium`（依實際回看窗決定，>30 天則 `long`） | 歷史趨勢被當成即時快照 |
| `derivatives` | Coinbase 溢價（Coinbase vs Binance 現貨價差） | `spot` ✅ | 無（預設值剛好正確，仍建議顯式標註） |

> 補標時一併確認 vic 的 `tests/test_collectors_horizon.py` 是否需要新增對應斷言——
> 該測試逐 collector 比對本表，新增子來源若沒進表會被漏測。

#### 3.2.2 `price` 的五檔標準粒度（R7-4）

`price` 資料來自本地 CSV，多算幾個窗口不增加任何 API 呼叫，故要求全覆蓋：

| 標準粒度 | 回看 | `horizon_class` | 產出內容 |
|---|---:|---|---|
| 日 | 1 | `spot` | 最新一日 OHLCV 與當日漲跌 |
| 10 日 | 10 | `short` | 10 日走勢摘要＋短期動能 |
| 月 | 30 | `medium` | 30 日序列摘要（§3.4 的主要輸出） |
| 季 | 90 | `long` | 季線位置、90 日區間位置 |
| 年 | 365 | `structural` | 年度區間位置、MA120／全歷史百分位 |

其餘 collector 依 R7-5「盡力而為」，未覆蓋的粒度誠實反映在 Data Confidence 扣分。

### 3.3 缺口補齊設計（R1-2，`agent/collectors/price.py`）

```
load_ohlcv_all(coin)              → CSV rows（官方基準，2021-06-01 ~ csv_end）
        │
        ▼
csv_end = rows[-1]["date"]
gap_days = (today - csv_end).days
        │
        ├─ gap_days <= 1 ──▶ 無缺口，as_of_date = csv_end，跳過補齊（R1-5）
        │
        └─ gap_days > 1 ───▶ _fetch_gap_klines(coin, since=csv_end+1)
                                    │
                                    ├─ 成功 ─▶ 併接序列，as_of_date = klines 末日
                                    │          gap_note = "其中 {start} 起 {n} 日採
                                    │                     Binance 公開日線補齊…"
                                    │
                                    └─ 失敗 ─▶ log_subsource(SKIPPED)，as_of_date = csv_end
                                               gap_note = "⚠ 未能補齊，資料止於
                                                          {csv_end}，距執行日 {n} 天"
```

**端點**（免 key，已實測 5 幣全通）：

```
GET https://api.binance.com/api/v3/klines
    ?symbol={TICKER}USDT&interval=1d&startTime={ms}&limit=1000
```

**併接規則**：
- 以 UTC 日期為鍵，CSV 資料**優先**（同日重複時保留 CSV，維護「共同基準」語意）
- Binance 回傳的最後一筆是**當日未收盤**的 K 棒 → 必須剔除，避免半日資料污染指標
- 欄位映射：`[0]=openTime, [1]=open, [2]=high, [3]=low, [4]=close, [5]=volume`

### 3.4 序列摘要設計（R1-6/R1-7）

**取代**現行 `summarize_technical_indicators()` 的單點輸出。新增 `summarize_series()`：

```
輸入：近 30 天的指標序列（RSI14 逐日、MA20 逐日、波動率逐日、量能逐日）
輸出（每個指標一行，不含原始數列）：
  RSI14：30天前 42.1 → 現在 68.3（+26.2），單調上升；
         期間高 71.4（2026-07-19）／低 38.9（2026-06-28）；
         現值位於近30天分佈第 88 百分位
```

**方向判定**（決定性，不經 LLM）：
- 單調上升／單調下降：全程無反向且首尾差 > 序列標準差
- 震盪走高／震盪走低：首尾差 > 序列標準差但過程有反向
- 橫盤：首尾差 ≤ 序列標準差

**Token 預算**：4 個指標 × 約 60 字 ≈ 240 字/幣，較現行單點版增加約 150 字，
遠低於直接丟 30×4=120 個數字（約 800 字）。

#### 3.4.1 均線位置判定的基準日分離（R1-9，2026-07-28 決策①）

實作時發現的邊界：**均線「值」與「站上／跌破」的判定基準必須分開**。

| 項目 | 基準 | 理由 |
|---|---|---|
| 均線數值（MA20/60/120） | 官方 CSV 全歷史 | R1-8，維護共同基準語意 |
| 站上／跌破位置 | **補齊後的最新收盤價** | 用 CSV 末日收盤會判出與現實相反的結論 |

實測佐證：BTC 的 MA120 = 72,613。以 CSV 末日收盤 73,674 判為「站上」，
但 2026-07-26 實際收盤 65,400 是「跌破」。R1-8 的原意是保護長歷史指標的**計算基準**，
不是要求用過期價格做**當下判讀**，兩者不衝突。

證據文字須同時揭露兩個基準日，例如：
```
MA120=72613.44（現價跌破）（位置以 2026-07-26 收盤 65400.00 判定；
均線值依官方基準資料集計算至 2026-05-31）
```

### 3.5 Prompt 變更（`agent/reasoning/prompts.py`）

#### 3.5.1 `_format_evidence_list()`（R2-4, R4-1）

```
- id=ev-003 | type=price | weight=0.92 [A+] | horizon=medium | window=2026-06-26~2026-07-25
  | source=... | content=...
```

清單前加固定說明區塊：

```
【時間尺度說明】每筆證據標註了 horizon（觀察窗尺度）：
  spot=當下快照｜short=≤7天｜medium=8-30天（本次主判斷視野）｜long=31-180天｜structural=>180天
  medium 是主視野。long/structural 屬「結構脈絡」，用來定位當前判斷處在大週期何處，
  不應與短窗訊號當成互相矛盾。

【權重說明】weight 為來源可信度（0-1）。低權重證據（<0.5）不足以單獨推翻
  高權重證據（>0.8）；若要如此主張，必須說明該高權重來源在此情境下為何不適用。
```

#### 3.5.2 `SYSTEM_PROMPT` 新增兩條規則（R4-2）

```
7. 不同時間尺度（horizon）的證據差異不等於矛盾。短窗訊號與長窗結構的落差是
   「位置關係」，應描述為脈絡而非衝突。
8. 證據權重代表來源可信度。低權重證據不足以單獨推翻高權重證據，除非你能具體
   說明該高權重來源在此情境下不適用。
```

#### 3.5.3 `build_step_b_prompt()` 三段輸出（R2-5/R2-6/R2-7, R3-3）

```json
{
  "consistent_signals": ["..."],
  "contradictions": ["僅限同尺度或當前訊號三帶之間的真實衝突"],
  "structural_context": ["跨尺度的位置關係描述"],
  "direction_matrix": [
    {"source_type": "price", "direction": 1, "basis": ["ev-003"]}
  ]
}
```

`direction_matrix` 的 prompt 約束：
> direction 只能是 1（看多）、0（中性）、−1（看空）三個整數之一，
> 不可填小數或文字。只針對 horizon 為 spot/short/medium 的證據表態；
> 若某 source_type 在這三帶內無證據，該類別直接省略不列。

#### 3.5.4 `build_step_d_prompt()` 新增裁判調整欄位（R3-8）

```json
{
  "...既有欄位...",
  "debate_adjustment": -8,
  "debate_adjustment_reason": "反方對鏈上活躍度的批評成立，正方第二輪未有效回應"
}
```

Prompt 說明：
> debate_adjustment 是你對「這份分析報告本身」的信心調整，範圍 −15 到 +5 的整數。
> 這不是對市場的看多看空，而是「經過這場辯論，我對自己這個結論的把握變高還是變低」。
> 範圍不對稱是刻意的：辯論若揭露了實質漏洞，應大幅下修；若只是確認了原有判斷，
> 最多小幅上調。必須填寫 debate_adjustment_reason，未填則視為 0。

### 3.6 信心計算重寫（`agent/reasoning/confidence.py`）

完全取代 `compute_confidence_score()`，新介面：

```python
def compute_confidence(
    evidences: list[Evidence],
    cross_validation: dict,      # 含 contradictions / direction_matrix
    debate_adjustment: int,
    debate_adjustment_reason: str,
) -> tuple[int, dict]:
```

#### 3.6.1 Data Confidence（R3-1，決定性）

六類各佔 `100/6 ≈ 16.67` 分，三檔評分：

```python
DATA_COMPLETENESS_THRESHOLD = {
    # source_type: (完整所需最少筆數, 完整所需最短窗長天數)
    "price":       (3, 14),
    "onchain":     (2, 0),    # 快照類不要求窗長
    "news":        (5, 7),
    "social":      (3, 3),
    "macro":       (2, 14),
    "derivatives": (4, 7),
}
```

| 條件 | 得分 |
|---|---|
| 筆數 ≥ 門檻 **且** 最長窗長 ≥ 門檻 | 16.67（100%） |
| 有證據但任一未達門檻 | 10.0（60%） |
| 零證據 | 0 |

> 門檻為暫定值（requirements.md 待確認 #3），集中在此常數表，
> 校準時只改這裡不動邏輯。

#### 3.6.2 Signal Consensus（R3-4/R3-5）

```python
# 「當前訊號」依當次主視野動態判定（ADR-7 / R7-3），不是寫死三帶
dirs = [d["direction"] for d in direction_matrix
        if any(is_current_signal(e.horizon_class, primary)
               for e in evidences if e.source_type == d["source_type"])]
if len(dirs) < 2:
    consensus = 50.0          # 樣本不足以談共識，中性處理
else:
    consensus = max(0.0, min(100.0, 100 * (1 - statistics.pstdev(dirs) / 1.0)))
```

驗算（對應需求方提出的三個例子）：

| directions | pstdev | Consensus |
|---|---:|---:|
| `[1, 1, 1, 1]` | 0.00 | **100** |
| `[1, -1, 0, 1]` | 0.83 | **17** ⚠ |
| `[1, -1, -1, 1]` | 1.00 | **0** ⚠ |

> ⚠ **未決事項（2026-07-28 alanchang 裁定「晚點做，先標記」）**：
> 以 `stdev_max = 1.0` 為分母時，需求方預期的「65 / 40」與公式實得的「17 / 0」
> 落差極大——因為 4 個來源的母體標準差在 `[1,-1,0,1]` 已達 0.83，接近理論極大值 1.0。
>
> **現行決定**：暫採 `stdev_max = 1.0` 的線性映射（R3-5 原文），
> 做到 tasks.md Task 4.3 時用真實 `direction_matrix` 驗算分佈再拍板。
>
> **候選替代方案**（屆時擇一，不得自行決定）：
>
> | 方案 | `[1,1,1,1]` | `[1,-1,0,1]` | `[1,-1,-1,1]` | 特性 |
> |---|---:|---:|---:|---|
> | A. 線性 stdev（現行） | 100 | 17 | 0 | 對分歧極敏感，鑑別度集中在「幾乎全一致」 |
> | B. `100 × \|mean(dirs)\|` | 100 | 25 | 0 | 反映淨方向，但全中性 `[0,0,0,0]` 也得 0（語意錯） |
> | C. `100 × (1 − stdev/stdev_max)`，`stdev_max` 依樣本數動態算 | 100 | ~35 | 0 | 較貼近直覺，但公式較難解釋 |
>
> **不得自行改公式，須先與 alanchang 確認。**

#### 3.6.3 Evidence Strength（R3-6，決定性）

```python
# 各類的平均 source_weight，再依「有證據的類別數 / 6」做覆蓋度折減
per_type_avg = {t: mean(weights of type t) for t in present_types}
strength = (sum(per_type_avg.values()) / len(per_type_avg)) \
           * (len(present_types) / 6) * 100
```

意義：來源權威度高且類別齊全 → 分數高。完全復用 R12 四因子產出，不新造權威度定義。

#### 3.6.4 組合與夾值（R3-7/R3-9/R3-10/R3-11）

```python
base = 0.4 * data_conf + 0.4 * consensus + 0.2 * strength
adj = 0 if not reason.strip() else max(-15, min(5, int(debate_adjustment)))
final = max(5, min(95, round(base + adj)))
```

#### 3.6.5 breakdown 內容（R3-12/R3-14）

```python
{
  "data_confidence": 83.3, "data_confidence_detail": {per-type 三檔判定與理由},
  "signal_consensus": 85.0, "direction_matrix": [...], "consensus_sample_size": 4,
  "evidence_strength": 76.2, "strength_detail": {per-type 平均權重},
  "base": 82.6,
  "debate_adjustment": -5, "debate_adjustment_reason": "...",
  "final": 78,
  "why": ["✅ ...", "⚠ ...", ...],   # R3-13
}
```

#### 3.6.6 「Why this confidence?」決定性生成（R3-13）

**不呼叫 LLM。** 規則：遍歷 breakdown，每個未滿分項自動產生一行。

| 觸發條件 | 產生的說明 |
|---|---|
| 某類 Data Confidence = 0 | `⚠ {類別} 本次無可用證據，資料完整度該項得 0 分` |
| 某類 Data Confidence = 60% | `⚠ {類別} 僅 {n} 筆／窗長 {d} 天，未達完整門檻（{n_req} 筆／{d_req} 天），該項得 60%` |
| 某類 Data Confidence = 100% | `✅ {類別} 資料完整（{n} 筆，窗長 {d} 天）` |
| Consensus ≥ 80 | `✅ {n} 類來源方向一致（{方向摘要}），訊號共識高` |
| Consensus < 50 | `⚠ 來源方向分歧（{各類方向}），市場缺乏共識` |
| `debate_adjustment < 0` | `⚠ 辯論後下修 {n} 分：{reason}` |
| `debate_adjustment > 0` | `✅ 辯論後上修 {n} 分：{reason}` |
| `structural_context` 非空 | `ℹ️ 結構脈絡（不計入矛盾）：{第一條}` |

### 3.7 語氣模板（R5，`agent/report/tone.py` 新檔）

```python
TONE_PROFILES = {
    "professional": {...},   # 現況措辭，預設
    "plain": {...},
}
```

**實作方式**：`tone` 僅作用於 `build_report_markdown()` 的**章節標題與導語措辭**，
以及 Step D 的一個附加輸出欄位 `plain_summary`（僅在 `tone=plain` 時要求 LLM 額外產出）。

**不做的事**（R5-2 約束）：不改變 `market_judgment`／`facts`／`inference`／
`debate` 任何欄位內容，不改變信心計算，不改變證據引用。
→ 這保證同一次執行切換 tone 不會產生不同的分析結論。

## 4. 相容性與降級矩陣（R6-1）

| 失敗點 | 降級行為 | 揭露方式 |
|---|---|---|
| Binance klines 補齊失敗 | 用純 CSV 繼續，`as_of_date = csv_end` | 證據文字標「⚠ 未能補齊…」＋log SKIPPED |
| collector 未標 `horizon_class` | 套預設 `spot` | log 一筆標註缺漏警示 |
| Step B 未產出 `direction_matrix` | `SignalConsensus = 50` | 報告揭露該降級（R3-15） |
| Step B 未產出 `structural_context` | 視為空陣列 | 無（不影響正確性） |
| Step D 未產出 `debate_adjustment` | 視為 0 | breakdown 記 `adjustment=0, reason="裁判未提供"` |
| `debate_adjustment` 超界 | 夾到 −15/+5 | log 原始值 |
| 舊 `evidence.json`（無 horizon 欄位） | pydantic 預設值生效 | 無 |

## 5. 測試策略

| 需求 | 測試檔 | 重點案例 |
|---|---|---|
| R1-2/R1-3 | `tests/test_price_gap_fill.py`（新） | mock klines 成功/失敗/空回應；未收盤 K 棒剔除；同日 CSV 優先 |
| R1-5 | 同上 | CSV 已到今天 → 不呼叫 API（用 mock 斷言零呼叫） |
| R1-6 | `tests/test_price_series_summary.py`（新） | 四種方向判定；30 天不足時的降級 |
| R2-1/R2-9 | `tests/test_schemas.py`（擴充） | 新欄位預設值；舊 JSON 可載入 |
| R2-2 | `tests/test_collectors_horizon.py`（新） | 每個 collector 產出的 horizon 符合 §3.2 對照表 |
| R2-4 | `tests/test_prompts.py`（擴充） | `_format_evidence_list` 含 horizon/window/weight |
| R2-6/R2-8 | `tests/test_confidence.py`（改寫） | `structural_context` 不計入矛盾懲罰 |
| R3-1 | `tests/test_confidence.py` | 六類三檔評分；derivatives 已納入（D7 回歸） |
| R3-5 | `tests/test_confidence.py` | §3.6.2 三組驗算值 |
| R3-9/R3-10 | `tests/test_confidence.py` | 超界夾值；無理由強制 0 |
| R3-13 | `tests/test_confidence_why.py`（新） | 各觸發條件都產生對應行；決定性（同輸入同輸出） |
| R4-1 | `tests/test_prompts.py` | 權重與分級標籤出現在清單 |
| R5-2 | `tests/test_tone.py`（新） | 同一 ReasoningResult 兩種 tone → 證據引用與信心分數完全相同 |
| R6-3 | 全套 | `pytest -q` 269 個既有測試維持通過 |

## 6. 對既有規格的影響

- `trust-refinement-upgrade` 的 R4-5（L5 數值信心公式）**被本規格 R3 取代**。
  該條文保留作歷史記錄，`design.md §3.x` 需加註「已由 horizon-aware-confidence R3 取代」。
- R12 四因子信譽公式**不受影響**，本規格僅**消費**其產出（ADR-4）。
- `raw_data/_meta/window_policy.md` 的窗口設計成為 §3.2 對照表的權威來源，
  兩者若不一致以 `window_policy.md` 為準並回頭修正本文件。

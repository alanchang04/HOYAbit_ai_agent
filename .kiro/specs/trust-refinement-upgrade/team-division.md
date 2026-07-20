# 團隊分工現況（給 Kevin 與隊友 3 對齊用）

> 對應 `requirements.md`（R1–R11）、`design.md`、`tasks.md`（Phase 0–6 執行狀況見 tasks.md 勾選）。
> 本檔案回答：現在誰做什麼、每個人手上「已經有的」與「還缺的」分別是什麼、
> 有哪些邊界需要對齊、哪些是開放問題需要團隊一起決定。
> 完整原始碼盤點依據見 `AUDIT.md`（2026-07-18）。

## 分工總覽

| 角色 | 負責範圍 | 對應現有程式碼 |
|---|---|---|
| Kevin | 各類資料來源抓取＋資料清理 | `agent/collectors/*.py` |
| Alan（你） | 資料整理／權重設定／情緒分析／合規把關／**Web UI 四面板**／**AWS 部署與 Bedrock 驗證** | `agent/filters/*.py`、`agent/report/view_builder.py`、`webapp/`、部署文件 |
| 隊友 3 | LLM 裁判與（多輪）辯論機制 | `agent/reasoning/pipeline.py`（Step A–D） |

---

## ⚠️ 與 Ken 的架構分歧：已裁定（2026-07-20）

Ken 在 `07_流程圖迭代定案.md` 提出一套「規則驅動加權投票」架構（Signal → 票權 w
→ 五組情境敏感度分析 → 信心用查表算出），跟本規格既有的「LLM 四步辯論鏈直接產生
市場判斷」是兩套不同的產品哲學。已拍板如下，**後續設計文件與程式實作都以此為準**：

- **資料層（抓取／去重／信源分級／權重公式）**：**採用 Ken 的設計**。
  他的 Phase 1-2 定義（去重先行、`raw_count`/`deduped_count`/`dedup_rate`
  隨證據傳遞、來源等級查表、覆蓋度＝去重後獨立來源數、`w = 新鮮度 × 來源等級
  × 覆蓋度 × dedup_penalty` 四因子、拉盤話術詞庫降來源等級）取代本規格
  `design.md` §3.1（L1 信源權重）與 §3.2（L2 內容層過濾）現有的簡化版規則表。
  **這是設計層級的決定，本規格 §3.1/§3.2 內容視為過時、待改版**（見下方「還缺
  什麼」，本輪先不動程式碼）。
- **LLM 層（結論如何產生）**：**不採用 Ken 的「Phase 4/5 加權投票算結論、Phase 6
  LLM 只敘事」模式**。維持本規格既有設計：`agent/reasoning/pipeline.py` 的四步
  辯論鏈（事實→交叉驗證→正方/反方辯論→裁判）才是市場判斷與信心的產生者，
  LLM 不是純敘事工具。若要納入 Ken 的量化訊號（Signal／票值），角色只能是
  **額外的一筆證據／輸入**餵給 LLM 參考，**不能取代**四步鏈的裁判角色。
  `requirements.md` R4-5（L5 數值信心公式）與 §3 的辯論設計維持現狀不變。

---

## 1. Kevin：資料來源抓取＋資料清理

### 現在有什麼
- 五類 collector 全部完成且實測可用：`price.py`（含零成本本地技術指標 SMA/RSI/波動率）、`onchain.py`（依鏈路由 5 種鏈）、`news.py`、`social.py`、`macro.py`
- 兩個已知 bug 已修：
  - `news.py` 幣種比對改雙軌邏輯（ticker 大小寫敏感＋全名別名小寫），不再誤中 method/solution 等無關字
  - `macro.py` 在比較題型下只抓一次（不分幣種），不再產生重複證據
- 便宜升級已做：Fear & Greed 改抓近 30 日算百分位（`macro.py`）；news 命中則數量化為關注度證據（`news.py`）
- 失敗隔離機制完整：每個 collector 獨立 timeout（75 秒）＋ try/except，單一來源失敗不拖垮全流程

### 還缺什麼
- **依 `07_流程圖迭代定案.md` 的 Phase 1-2 設計實作資料層**（已裁定採用 Ken 方案，見上方「架構分歧」）：
  - `news.py` 的命中則數計算要**搬到去重之後**（目前是在 collector 內直接計數，未去重，需改）
  - 標題相似度去重（本地字串級，不用 LLM）＋同步算出 `raw_count`／`deduped_count`／`dedup_rate`，隨證據一起往下傳
  - 來源等級表 `static/source_reputation.json`（賽前信譽表＋分級理由，取代/整合 Alan 現有 `source_weights.py` 的規則表）
  - `w = 新鮮度 × 來源等級 × 覆蓋度 × dedup_penalty` 四因子權重公式（`dedup_penalty` 需獨立於覆蓋度計算，理由見 Ken 文件「新問題 A」）
  - 拉盤話術詞庫比對（Ken 設計是命中則來源等級降一級；Alan 現有 `content.py` 的 PR_TERMS 是類似構想但做法不同，這塊要跟 Ken 對一次以確定最終比對詞庫與降級方式由誰維護）
  - 最小樣本門檻防呆（去重前則數 <5 時 dedup_penalty 固定為 1，避免除零/小樣本誤判）
- 這塊的**實作歸屬（Kevin 寫 or Alan 寫）還沒定案**，只確定了設計依 Ken 的文件為準——建議 Kevin 看過 `07_流程圖迭代定案.md` 全文後跟 Alan 談一次分工
- Ken 筆記（`DATA_SOURCES.md`）中列的延伸資料源（衍生品/微結構流動性/穩定幣供給等，`07` 文件也把 derivatives／liquidity 列為新 collector）若要做，屬於這裡；優先序與風險評估已在 `AUDIT.md` §7.2、§8 列出（衍生品有地理封鎖風險，需先在部署環境實測）
- Reddit 403 的替代方案（例如改官方 OAuth API）——目前是接受並在報告誠實揭露，非必要但可選

---

## 2. Alan（你）：資料整理／權重／情緒分析／合規／UI／部署

### 現在有什麼
- **L1 信源權重**（⚠️ 待改版，見上方「架構分歧」）：`agent/filters/source_weights.py`，目前是靜態規則表（官方基準 0.95／鏈上 0.85／CoinGecko 0.80／總經 0.65／新聞 0.60／社群 0.30），已實測、但**設計上已被 Ken 的四因子公式取代**，尚未照新設計改寫。**「權重要不要做成可訓練模型」這個結論不受本次架構分歧影響、維持不變**：不建議訓練——沒有可靠標籤、且會犧牲「每個數字可解釋」這個核心賣點；Ken 的四因子公式一樣是規則式、可解釋，符合同樣的原則，只是規則更細緻
- **L2 內容層過濾**（⚠️ 待改版，見上方「架構分歧」）：`agent/filters/content.py`，目前是 PR 話術英文詞典偵測（降權）＋模板相似度（Jaccard，標記非獨立來源），純本地零 LLM 成本，已測效能 <100ms；**模板相似度這塊的角色被 Ken 的「Phase 2 去重＋dedup_penalty」取代**，PR 詞典則要跟 Ken 的拉盤話術詞庫合併成同一份
- **L5 數值信心公式**：`agent/reasoning/confidence.py`，`base(高/中/低) + 權威源占比加成 − 矛盾訊號懲罰 − 資料缺口懲罰`，公式每項都寫進 log 可對帳
- **view_builder**：`agent/report/view_builder.py`，組裝 `report_view.json` 四面板契約；今天剛修好一個缺口——L3 面板的 `removed_items` 原本永遠是空陣列，現在會正確反推「哪些證據沒被事實層引用、為什麼」（有 L2 判定就沿用該理由，沒有就標記「事實層未引用」）
- **Web UI 四面板前端**（新認領）：`webapp/templates/result.html`（報告／執行時間線／Raw Log 分頁）、`webapp/templates/view.html`（四面板：原始證據流／未過濾基準對照／信任提煉流水線／分析報告），`/view/{run_id}` 路由已接上，已用真實 dry-run 資料驗證版面正確
- **合規把關**：`.kiro/steering/product.md` 明文寫死合規紅線（禁投資建議語彙、INTACT 語意、LLM backend 限制），`tests/test_compliance.py` 用 word-boundary regex 掃過全部四面板＋baseline＋HTML 模板確保沒有 buy/sell/hold 等詞
- **Kiro 使用證據**（+10% 加分項）：`.kiro/specs/trust-refinement-upgrade/`（本規格三件套）、`.kiro/steering/`、`.kiro/hooks/run-tests.yaml`

### 還缺什麼
- **L1/L2 依 Ken 的四因子公式改版**（設計已定案，見上方「架構分歧」，程式尚未動）：`source_weights.py` 要改成吃來源等級表＋覆蓋度；`content.py` 的模板相似度邏輯要讓位給 Phase 2 去重＋`dedup_penalty`，PR 詞典要跟 Ken 的話術詞庫合併
- **F9 情緒分布分析（你說的「敏感分析」）**：目前是空佔位（`content.py` 的 `F9_STATUS = {"enabled": False}`），規格原本預留給 RAG 同伴，現在你要接手——需決定用詞典法（VADER/Loughran-McDonald 起步，純本地免 LLM）還是走 RAG／模型
- **L1/L2 實作與 Kevin「清理」的分工**：設計已依 Ken 的文件定案，但**誰寫程式**還沒定案，待跟 Kevin 對齊（見上方 Kevin 段落）
- **AWS 實際部署**（新認領）：README 已有完整 ECR push／App Runner 建立步驟，但還沒真的執行，需要 AWS CLI 存取確認
- **Bedrock 最終驗證**（新認領，`tasks.md` Phase 6，標記 blocked）：`scripts/check_llm.py` 煙測 → 3 題型端到端 → 四面板／usage 核對
- **簡報／錄影素材整理成品**：`PITCH_REFERENCE.md` 已有素材庫，但還沒做成正式簡報與錄影

---

## 3. 隊友 3：LLM 裁判與辯論機制

### 現在有什麼
- **四步推理鏈完整實作**：`agent/reasoning/pipeline.py` — 事實層（Step A）→ 交叉驗證層（Step B）→ 推論層（Step C1 正方／C2 反方單輪辯論）→ 結論層（Step D 裁判整合）
- 反方會**具體批評正方的論證**（不是各說各話）——實測 BTC vs ETH 比較分析中，反方直接點名「正方過度解讀了 BTC 量能增加 10.13% 的數據」
- 辯論任一步失敗會自動退回單模型一次產出多假設的 fallback（`build_step_c_prompt`），不會讓整條推理鏈中斷
- 已用真實 LLM（Gemini，暫代 Bedrock）驗證過 3 種題型（多源整合／假設驗證／比較分析），品質良好

> **重要（已裁定）**：Ken 的 `07_流程圖迭代定案.md` 提議「Phase 4/5 用加權投票＋
> 五組情境敏感度分析算出市場判斷與信心，Phase 6 的 LLM 只負責敘事、不算分」。
> **這個模式不採用**——四步辯論鏈才是市場判斷與信心的產生者。若 Ken 的量化訊號
> 之後要整合進來，只能是「多一筆證據餵給 Step A/C 參考」，不能取代 Step D 裁判
> 的角色。隊友 3 開發時請以此為前提。

### 還缺什麼——這是他要做的核心決定
**目前是單輪辯論**（正方一次、反方一次、裁判一次）。隊友 3 提的兩個方向我evaluate過（完整分析見對話紀錄，摘要如下）：

| 方案 | 說明 | 建議 |
|---|---|---|
| **多輪辯論**（延伸現有） | 正方→反方→正方反駁→反方再反駁→…→裁判，每多一輪 +2 次呼叫 | **建議優先採用**：建立在已驗證程式碼上、風險低；每輪都可記進 log／面板③展示，符合「信任提煉可回溯」的核心賣點；可優雅降級（時間緊迫時跑完當輪就喊停） |
| **Best-of-N＋裁判選最佳** | 產出 5 個候選答案，裁判選最好的一個 | 若採用，**建議只套用在結論層**（不要整條推理鏈跑 5 次，Gemini 額度/Bedrock 延遲都撐不住）；可平行呼叫，wall-clock 延遲可能反而較低；但被淘汰的 4 個候選預設不會被記錄，會弱化「可回溯」賣點，除非額外要求裁判解釋淘汰理由 |

若採多輪辯論，需要的改動：`pipeline.py` 的 Step C 改成迴圈＋停止條件（建議設輪數上限，例如 2-3 輪，避免吃掉太多時間預算）；`schemas.py`／`view_builder.py` 的 debate 欄位要從單一物件改成陣列以容納多輪。
兩個方案最終都要在 Bedrock 開通後重新驗證格式遵從度與延遲（`tasks.md` Phase 6）。

---

## 邊界待對齊

### 已裁定（2026-07-20）
1. ~~Kevin 的「清理」vs Alan 的 L1/L2「信任評分」~~——**設計層級已裁定**：資料層（去重／信源分級／權重公式／話術詞庫）全部採用 Ken 的 `07` 文件設計，取代 Alan 原本的簡化規則表。**實作歸屬（誰寫程式）仍待談**，見下方待辦
2. ~~LLM 是否只負責敘事~~——**否決**：維持四步辯論鏈產生市場判斷與信心，Ken 的量化訊號若要用，只能當額外證據餵給 LLM，不取代裁判角色

### 仍待對齊
1. **L1/L2 資料層改版的實作歸屬**：Kevin 寫還是 Alan 寫，或拆開寫（Kevin 做去重／信源等級表，Alan 做套用在證據上的公式與 view_builder 呈現）——建議 Kevin 看過 `07_流程圖迭代定案.md` 全文後跟 Alan 談
2. **雙幣相對指標歸屬**：`agent/collectors/relative.py`（相關係數/beta/最大回撤，純本地 CSV 運算）目前掛在 orchestrator 由 Alan 這邊維護，但概念上屬於「資料」，可視 Kevin 意願轉手或維持現狀；Ken 的 07 文件也把「CSV 再榨」列在 Phase 1 本地層，可以一併討論
3. **多輪辯論 vs Best-of-N 最終選哪個**：隊友 3 看完上表分析後決定，若選多輪辯論建議順便定輪數上限
4. **F9 情緒分析用詞典法還是 RAG**：Alan 待定，若隊友 3 或 Kevin 有 RAG 資源也可以認領走
5. **Ken 文件中「未完全收斂項目」**（`static/weights_backtest.json` 檔名統一、dedup 最小樣本門檻、dedup_penalty 分級曲線）：這些是 Ken 自己也還沒定案的細節，實作者遇到時需要跟 Ken 對一次，不要自己拍板

---

## 已完成里程碑對照（tasks.md 快速索引）

Phase 0（bug 修復＋Kiro 證據）～Phase 5（四面板前端）已全數完成並經完整程式碼審查＋實際執行驗證（198→200 個 pytest 全綠，含 3 次真實 dry-run 場景手動驗證：比較題型+baseline、degraded mode、L3 removed_items）。
Phase 6（Bedrock 最終驗證）標記 blocked，等 AWS 帳號確認後執行。

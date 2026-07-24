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
- **`news.py` 命中則數搬到去重之後**（tasks.md 7.2，R12-2）——資料層改版其餘部分
  已由 Alan 於 2026-07-21 在 `agent/filters/` 完成（見下方 Alan 段落），**只剩這一項
  在 collector 側**。Alan 已在 evidence 上備妥 `dedup_deduped_count` 欄位可直接讀取。
  ⚠️ 注意：`origin/ken` 分支對 `news.py` 有 197 行未合併改動（另有 `price.py`／
  `macro.py`／`config.py`／fixtures 與整套 `pipeline/` prototype、`raw_data/` 快照，
  共 14 個 commit），建議先合併 Ken 的分支再做這條，避免衝突
- 拉盤話術**詞庫內容**要跟 Ken 對一次（Alan 已把「命中→來源等級降一級」機制做好，
  詞庫目前沿用 `content.py` 的 PR_TERMS，最終詞庫與維護者待定）
- Ken 筆記（`DATA_SOURCES.md`）中列的延伸資料源（衍生品/微結構流動性/穩定幣供給等，`07` 文件也把 derivatives／liquidity 列為新 collector）若要做，屬於這裡；優先序與風險評估已在 `AUDIT.md` §7.2、§8 列出（衍生品有地理封鎖風險，需先在部署環境實測）
- Reddit 403 的替代方案（例如改官方 OAuth API）——目前是接受並在報告誠實揭露，非必要但可選

---

## 2. Alan（你）：資料整理／權重／情緒分析／合規／UI／部署

### 現在有什麼
- **L1 信源權重（✅ 已依 Ken 四因子公式改版，2026-07-21）**：`agent/filters/source_weights.py` 實作 `w = 新鮮度 × 來源等級 × 覆蓋度 × dedup_penalty`，來源等級查 `static/source_reputation.json`（賽前信譽表＋分級理由，並印進 report.md 附錄）；所有係數資料驅動、weight_reason 逐筆可對帳；信譽表載入失敗自動退回舊制規則表（R12-5 fallback）。**「權重要不要做成可訓練模型」結論維持不變**：不訓練——四因子公式是規則式、可解釋，符合「每個數字可解釋」的核心賣點
- **Phase 2 去重（✅ 新增，2026-07-21）**：`agent/filters/dedup.py`——news/social 依 (coin, source_type) 群組做字串級近重複偵測，算出 `raw_count`／`deduped_count`／`dedup_rate` 隨證據進 evidence.json；被剔除者標 `duplicate_of` 保留可回溯（不刪除）；<5 則小樣本不觸發 dedup_penalty（R12-3d）
- **L2 內容層過濾（✅ 已改版，2026-07-21）**：`agent/filters/content.py`——拉盤話術命中改為「來源等級降一級」（取代 ×0.5，可與 dedup_penalty 疊加、非重複扣分）；模板相似度（F10）功成身退，由 Phase 2 去重取代；PR 詞典內容仍待跟 Ken 的話術詞庫合併
- **F9 情緒分布分析（✅ 詞典法 MVP 上線，2026-07-21）**：正/負面英文詞典 word-boundary 統計，樣本取去重後敘事類證據；單向占比 ≥80% 且樣本 ≥5 標羊群/帶風向警示；觀察性指標不動權重，輸出到面板③ L2 與 execution log；之後要升級 RAG／模型法時介面已就位
- **L5 數值信心公式**：`agent/reasoning/confidence.py`，`base(高/中/低) + 權威源占比加成 − 矛盾訊號懲罰 − 資料缺口懲罰`，公式每項都寫進 log 可對帳
- **view_builder**：`agent/report/view_builder.py`，組裝 `report_view.json` 四面板契約；今天剛修好一個缺口——L3 面板的 `removed_items` 原本永遠是空陣列，現在會正確反推「哪些證據沒被事實層引用、為什麼」（有 L2 判定就沿用該理由，沒有就標記「事實層未引用」）
- **Web UI 四面板前端**（新認領）：`webapp/templates/result.html`（報告／執行時間線／Raw Log 分頁）、`webapp/templates/view.html`（四面板：原始證據流／未過濾基準對照／信任提煉流水線／分析報告），`/view/{run_id}` 路由已接上，已用真實 dry-run 資料驗證版面正確
- **合規把關**：`.kiro/steering/product.md` 明文寫死合規紅線（禁投資建議語彙、INTACT 語意、LLM backend 限制），`tests/test_compliance.py` 用 word-boundary regex 掃過全部四面板＋baseline＋HTML 模板確保沒有 buy/sell/hold 等詞
- **Kiro 使用證據**（+10% 加分項）：`.kiro/specs/trust-refinement-upgrade/`（本規格三件套）、`.kiro/steering/`、`.kiro/hooks/run-tests.yaml`

### 還缺什麼
- **跟 Ken 校準兩個暫定值**：`static/source_reputation.json` 裡的 dedup_penalty
  分級曲線與 min_sample=5 門檻（Ken 未收斂項目），校準後只需改 JSON 不改程式
- **拉盤話術詞庫與 Ken 合併**：機制已完成（降一級），詞庫內容與維護者待對齊
- **AWS 實際部署**（新認領）：README 已有完整 ECR push／App Runner 建立步驟，但還沒真的執行，需要 AWS CLI 存取確認
- **Bedrock 最終驗證**（新認領，`tasks.md` Phase 6，標記 blocked）：`scripts/check_llm.py` 煙測 → 3 題型端到端 → 四面板／usage 核對（含 tasks.md 7.8 的四面板數字對帳）
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
1. ~~L1/L2 資料層改版的實作歸屬~~——**已定（2026-07-21）**：filters 層由 Alan 實作完成；collector 側的 7.2（news 命中則數用去重後數量）歸 Kevin／Ken，`origin/ken` 已合併（見 #6），可以開始做
2. ~~雙幣相對指標歸屬~~——**已比對（2026-07-24）**：`agent/collectors/relative.py` vs `pipeline/compute_relative_strength.py` 用同一份資料（`data/` 與 `raw_data/price/` 下的 CSV byte-for-byte 相同），重疊的相對強弱百分位算法**數字實測一致**（BTC/ETH 兩邊都是 98.9%），**沒有邏輯衝突**。但 Ken 的腳本只做我們四個指標裡的一個（缺相關係數/Beta/最大回撤），且是離線批次預算全部 20 組合寫死成 CSV，不是即時計算；他自己腳本開頭也寫明「不是正式 collector，定案後才會跟 alanchang 對」。**結論：維持 `relative.py` 不動**（它是 Ken 那套邏輯的超集合），不需要整個替換；真正待對齊的是「這塊以後要不要整併進 Ken 的 collector 架構」，不是邏輯正確性問題
3. ~~多輪辯論 vs Best-of-N 最終選哪個~~——**已定（2026-07-22）**：隊友3選了多輪辯論，`origin/debate-dev` 已合併，上限 2 輪、反方自報收斂機制已用 3 種真實 Bedrock 題型驗證過（一次自然收斂、兩次跑滿上限）
4. ~~F9 情緒分析用詞典法還是 RAG~~——**已定（2026-07-21）**：詞典法 MVP 先上線（純本地零 LLM 成本），RAG／模型法列為後續升級選項，介面已就位
5. **Ken 文件中「未完全收斂項目」**：dedup 最小樣本門檻與 dedup_penalty 分級曲線已用**暫定值**實作在 `static/source_reputation.json`（$comment 有標記），需與 Ken 校準後改 JSON 定案；`static/weights_backtest.json` 檔名統一屬 Ken 的機制②③選配，尚未實作、維持待 Ken 點頭
6. ~~Ken 分支（`origin/ken`）整合~~——**已合併（2026-07-23，commit `244c7ca`）**：14 個 commit 全部併入，`requirements.txt` 有一處衝突已手動排解（雙方新增套件皆保留，互不排斥），其餘 198 個檔案自動合併乾淨。**但 #2 提到的 `relative.py` vs `pipeline/compute_relative_strength.py` 重疊、以及 #5 的暫定值校準，合併動作本身不會自動解決，仍需要實際跟 Ken 討論**

---

## 已完成里程碑對照（tasks.md 快速索引）

Phase 0（bug 修復＋Kiro 證據）～Phase 5（四面板前端）已全數完成並經完整程式碼審查＋實際執行驗證（198→200 個 pytest 全綠，含 3 次真實 dry-run 場景手動驗證：比較題型+baseline、degraded mode、L3 removed_items）。
Phase 6（Bedrock 最終驗證）標記 blocked，等 AWS 帳號確認後執行。

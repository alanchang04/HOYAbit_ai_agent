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

## 1. Kevin：資料來源抓取＋資料清理

### 現在有什麼
- 五類 collector 全部完成且實測可用：`price.py`（含零成本本地技術指標 SMA/RSI/波動率）、`onchain.py`（依鏈路由 5 種鏈）、`news.py`、`social.py`、`macro.py`
- 兩個已知 bug 已修：
  - `news.py` 幣種比對改雙軌邏輯（ticker 大小寫敏感＋全名別名小寫），不再誤中 method/solution 等無關字
  - `macro.py` 在比較題型下只抓一次（不分幣種），不再產生重複證據
- 便宜升級已做：Fear & Greed 改抓近 30 日算百分位（`macro.py`）；news 命中則數量化為關注度證據（`news.py`）
- 失敗隔離機制完整：每個 collector 獨立 timeout（75 秒）＋ try/except，單一來源失敗不拖垮全流程

### 還缺什麼
- **「資料清理」的範圍還沒明確界定**——目前 collector 只有基本的 schema 驗證與失敗隔離，沒有專門的清理步驟（去重複 API 回應、格式標準化、離群值處理）。這塊建議由 Kevin 定義範圍，並與 Alan 的 L1/L2（信任評分／PR 與模板偵測）畫清楚邊界（見下方「邊界待對齊」）
- Ken 筆記（`DATA_SOURCES.md`）中列的延伸資料源（衍生品/微結構流動性/穩定幣供給等）若要做，屬於這裡；優先序與風險評估已在 `AUDIT.md` §7.2、§8 列出（衍生品有地理封鎖風險，需先在部署環境實測）
- Reddit 403 的替代方案（例如改官方 OAuth API）——目前是接受並在報告誠實揭露，非必要但可選

---

## 2. Alan（你）：資料整理／權重／情緒分析／合規／UI／部署

### 現在有什麼
- **L1 信源權重**：`agent/filters/source_weights.py`，靜態規則表（官方基準 0.95／鏈上 0.85／CoinGecko 0.80／總經 0.65／新聞 0.60／社群 0.30），已實測。**結論：不建議做成可訓練模型**——沒有可靠標籤、且會犧牲「每個數字可解釋」這個核心賣點，維持規則表並在簡報講清楚這是刻意的設計選擇
- **L2 內容層過濾**：`agent/filters/content.py`，PR 話術英文詞典偵測（降權）＋模板相似度（Jaccard，標記非獨立來源），純本地零 LLM 成本，已測效能 <100ms
- **L5 數值信心公式**：`agent/reasoning/confidence.py`，`base(高/中/低) + 權威源占比加成 − 矛盾訊號懲罰 − 資料缺口懲罰`，公式每項都寫進 log 可對帳
- **view_builder**：`agent/report/view_builder.py`，組裝 `report_view.json` 四面板契約；今天剛修好一個缺口——L3 面板的 `removed_items` 原本永遠是空陣列，現在會正確反推「哪些證據沒被事實層引用、為什麼」（有 L2 判定就沿用該理由，沒有就標記「事實層未引用」）
- **Web UI 四面板前端**（新認領）：`webapp/templates/result.html`（報告／執行時間線／Raw Log 分頁）、`webapp/templates/view.html`（四面板：原始證據流／未過濾基準對照／信任提煉流水線／分析報告），`/view/{run_id}` 路由已接上，已用真實 dry-run 資料驗證版面正確
- **合規把關**：`.kiro/steering/product.md` 明文寫死合規紅線（禁投資建議語彙、INTACT 語意、LLM backend 限制），`tests/test_compliance.py` 用 word-boundary regex 掃過全部四面板＋baseline＋HTML 模板確保沒有 buy/sell/hold 等詞
- **Kiro 使用證據**（+10% 加分項）：`.kiro/specs/trust-refinement-upgrade/`（本規格三件套）、`.kiro/steering/`、`.kiro/hooks/run-tests.yaml`

### 還缺什麼
- **F9 情緒分布分析（你說的「敏感分析」）**：目前是空佔位（`content.py` 的 `F9_STATUS = {"enabled": False}`），規格原本預留給 RAG 同伴，現在你要接手——需決定用詞典法（VADER/Loughran-McDonald 起步，純本地免 LLM）還是走 RAG／模型
- **L1/L2 與 Kevin「清理」的邊界**：待跟 Kevin 對齊（見下方）
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

### 還缺什麼——這是他要做的核心決定
**目前是單輪辯論**（正方一次、反方一次、裁判一次）。隊友 3 提的兩個方向我evaluate過（完整分析見對話紀錄，摘要如下）：

| 方案 | 說明 | 建議 |
|---|---|---|
| **多輪辯論**（延伸現有） | 正方→反方→正方反駁→反方再反駁→…→裁判，每多一輪 +2 次呼叫 | **建議優先採用**：建立在已驗證程式碼上、風險低；每輪都可記進 log／面板③展示，符合「信任提煉可回溯」的核心賣點；可優雅降級（時間緊迫時跑完當輪就喊停） |
| **Best-of-N＋裁判選最佳** | 產出 5 個候選答案，裁判選最好的一個 | 若採用，**建議只套用在結論層**（不要整條推理鏈跑 5 次，Gemini 額度/Bedrock 延遲都撐不住）；可平行呼叫，wall-clock 延遲可能反而較低；但被淘汰的 4 個候選預設不會被記錄，會弱化「可回溯」賣點，除非額外要求裁判解釋淘汰理由 |

若採多輪辯論，需要的改動：`pipeline.py` 的 Step C 改成迴圈＋停止條件（建議設輪數上限，例如 2-3 輪，避免吃掉太多時間預算）；`schemas.py`／`view_builder.py` 的 debate 欄位要從單一物件改成陣列以容納多輪。
兩個方案最終都要在 Bedrock 開通後重新驗證格式遵從度與延遲（`tasks.md` Phase 6）。

---

## 邊界待對齊（建議三人一起拍板）

1. **Kevin 的「清理」vs Alan 的 L1/L2「信任評分」**：建議切法——Kevin 顧「資料是否乾淨」（格式正確、去重、無壞值），Alan 顧「這筆資料該被信任多少」（權重＋PR/模板/情緒的語意判斷）。若 Kevin 的清理也想做語意層判斷（例如自己先濾掉明顯業配文），要先跟 Alan 講一聲避免邏輯重複
2. **雙幣相對指標歸屬**：`agent/collectors/relative.py`（相關係數/beta/最大回撤，純本地 CSV 運算）目前掛在 orchestrator 由 Alan 這邊維護，但概念上屬於「資料」，可視 Kevin 意願轉手或維持現狀
3. **多輪辯論 vs Best-of-N 最終選哪個**：隊友 3 看完上表分析後決定，若選多輪辯論建議順便定輪數上限
4. **F9 情緒分析用詞典法還是 RAG**：Alan 待定，若隊友 3 或 Kevin 有 RAG 資源也可以認領走

---

## 已完成里程碑對照（tasks.md 快速索引）

Phase 0（bug 修復＋Kiro 證據）～Phase 5（四面板前端）已全數完成並經完整程式碼審查＋實際執行驗證（198→200 個 pytest 全綠，含 3 次真實 dry-run 場景手動驗證：比較題型+baseline、degraded mode、L3 removed_items）。
Phase 6（Bedrock 最終驗證）標記 blocked，等 AWS 帳號確認後執行。

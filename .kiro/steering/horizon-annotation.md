---
inclusion: fileMatch
fileMatchPattern: "agent/collectors/*"
---

# 時間尺度標註規範（horizon-aware-confidence R2）

新增或修改任何 collector 前必讀。對應規格：`.kiro/specs/horizon-aware-confidence/`
（requirements.md R2／design.md §3.2／tasks.md Phase 2）。
窗口設計的權威來源是 `raw_data/_meta/window_policy.md`。

## 為什麼需要這條規範

推理層若不知道每筆證據代表多長的觀察窗，會把「5 天社群情緒」和「5 年價格百分位」
當成互相矛盾的訊號（假矛盾），接著連環懲罰：辯論雙方為不存在的衝突互相讓步、
信心分數被無端扣分。這不是資料問題，是標註遺失造成的設計缺陷。

## 不可違反的約定

1. **每一筆 `EvidenceDraft` 都必須顯式標註 `horizon_class`**。
   不要依賴預設值 `spot` ——預設值是相容性保險，不是省事的藉口。
   漏標會被 `orchestrator` 記一筆警示 log。

2. **標註必須是決定性的，不得交由 LLM 推斷**（ADR-2）。
   依據是你實際打的端點參數：`limit`、`interval`、`t=week`、`days=30` 這些
   你自己傳出去的值，就是窗長的事實來源。

3. **`window_end` ≠ `fetched_at`**。前者是「這筆觀察涵蓋到哪一天」，
   後者是「我什麼時候抓的」。官方 CSV 的證據 `fetched_at` 是執行日，
   但 `window_end` 是 CSV 末日——**這兩個值不同正是本規範存在的理由**。

4. **同一個 collector 內不同子來源可以有不同 horizon**，不要為了整齊統一套同一個值。
   `derivatives.py` 是最典型的例子：CME COT 是 `long`（12 週），
   期貨到期結構是 `spot`（當下快照），兩者在同一個 `fetch()` 裡。

5. **五帶分界**（`agent/schemas.py` 的 `HorizonClass`）：

   | 值 | 窗長 | 角色 |
   |---|---|---|
   | `spot` | 當下快照 | 當前訊號 |
   | `short` | ≤ 7 天 | 當前訊號 |
   | `medium` | 8–30 天 | 當前訊號（**主視野**） |
   | `long` | 31–180 天 | 結構脈絡 |
   | `structural` | > 180 天 | 結構脈絡 |

   「當前訊號」正常參與辯論、矛盾判定與共識投票；
   「結構脈絡」只用來定位大週期位置，**不參與**上述三者。

6. **最容易標錯、後果也最嚴重的三筆**（假矛盾的主要來源，務必正確）：
   - `price.py` 的 MA120 位置、波動率全歷史百分位 → `structural`
   - `derivatives.py` 的 CME COT（12 週） → `long`
   - `relative.py` 的雙幣相對強弱（90 天位置） → `long`

7. **降級優先**（R6-1）：標註相關的任何錯誤都不得中斷 collector。
   欄位算不出來就留 `None`，pipeline 必須跑完。

## 完整對照表

逐 collector、逐子來源的標註對照見
`.kiro/specs/horizon-aware-confidence/design.md` §3.2。
新增子來源時同步更新該表與 `raw_data/_meta/window_policy.md`。

## 資料時效（R1，僅影響 `price.py`）

官方基準 CSV 止於資料集發布日（目前 2026-05-31），與執行日可能有數十天落差。
`price.py` 採**雙軌**：

- 長歷史指標（MA120、波動率全歷史百分位）→ **只用官方 CSV**，不得改用 Binance
- 近期指標（30 天序列、RSI、MA20）→ CSV ＋ Binance 公開日線補齊缺口
- 補齊失敗一律降級為純 CSV 並在證據文字標註「⚠ 未能補齊」，不得中斷

同日資料重複時 **CSV 優先**，維護「共同基準」語意。
Binance 回傳的最後一筆是當日未收盤 K 棒，**必須剔除**。

## 邊界

`agent/collectors/` 同時是 Kevin／Ken 的工作範圍，且 `origin/ken` 分支
歷來有大量 collector 改動。動工前先 `git fetch` 確認無未合併變更，
協作慣例見 `.kiro/specs/trust-refinement-upgrade/team-division.md`。

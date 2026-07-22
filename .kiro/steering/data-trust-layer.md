---
inclusion: fileMatch
fileMatchPattern: "agent/filters/*"
---

# 資料層信任評分規範（R12，設計權威：Ken《07_流程圖迭代定案.md》）

改動 `agent/filters/` 下任何檔案前必讀。對應規格：`.kiro/specs/trust-refinement-upgrade/`
（requirements.md R12／design.md §3.9／tasks.md Phase 7）。

## 不可違反的約定

1. **覆蓋度 ≠ 覆蓋率，嚴禁混用**：
   - 覆蓋度＝去重後的**獨立來源數**（L1 四因子之一，`dedup.py` 的 `distinct_sources`）
   - 覆蓋率＝collector **成功執行比例**（L5 信心公式輸入，`confidence.py`）
   - 回歸測試：`tests/test_source_weights.py::TestCoverageVsCoverageRateNotConflated`
2. **四因子公式** `w = 新鮮度 × 來源等級 × 覆蓋度 × dedup_penalty`：
   所有係數一律來自 `static/source_reputation.json`，**不得在程式碼寫死數字**。
   調整分級/曲線＝改 JSON，不改程式。
3. **dedup_penalty 與覆蓋度必須獨立計算**（R12-3c）：覆蓋度量來源多樣性，
   dedup_penalty 量單一敘事被灌水程度。看起來像重複計算——不是，理由見
   Ken 文件 Round 2「新問題 A」，不要把它們合併。
4. **拉盤話術命中＝來源等級降一級**（R12-4），不是乘 0.5。與 dedup_penalty
   降權允許同時疊加（獨立維度、非重複扣分）——這是設計，不是 bug。
5. **R12-5 fallback**：信譽表載入失敗或四因子計算出錯 → 退回
   `source_weights.py` 底部的舊制靜態規則表，log 標 `formula=legacy_fallback`，
   絕不中斷流程。舊制表與 `assign_source_weight()` 因此**不可刪除**。
6. **去重是標記不是刪除**：被去重者留在 evidence.json（`duplicate_of` 指向
   canonical、權重壓 0.05、FilterDecision verdict=removed），保持可回溯。

## 暫定值（待與 Ken 校準，不要自行改定案）

- `dedup_penalty` 的分級曲線（rate→倍率映射）：Ken 未收斂項目 #3，目前為暫定分段
- 小樣本門檻 `min_sample=5`（R12-3d）：Ken 自承拍腦袋值，賽前可用歷史資料校準

## 邊界

- `agent/collectors/`（含 news 命中則數的去重後計數，tasks.md 7.2）是
  Kevin／Ken 的範圍，且 Ken 的 `origin/ken` 分支有大量未合併的 collector
  改動——不要在這裡動 collector 程式。

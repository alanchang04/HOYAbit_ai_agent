# Macro 總經日曆待辦

> 2026-07-21 討論起頭：對照 `07_流程圖迭代定案.md` Round 4 的窗口設計表——
> Macro 建議「回顧 30-90 天＋往前看下一個排定事件（下次 FOMC/CPI）」。
> 現況 `agent/collectors/macro.py` 只有 Fear & Greed（`FNG_WINDOW=30`，
> 已符合回顧窗口）跟即時匯率快照，**完全沒有「往前看」的總經日曆**。
> `07_流程圖迭代定案.md` Phase 1 其實早就提過要新增 `calendar`（新）
> collector（賽前預快取 FOMC/CPI/解鎖日靜態 JSON），這件事還沒動工。

## 現況

- `macro.py` 只有兩條即時來源：Fear & Greed、Frankfurter 匯率
- 沒有任何「下次 FOMC 是哪天」「下次 CPI 發布是哪天」的資料

## 待處理方向（未定案，僅記錄想法）

- FOMC/CPI 排程是固定公開行事曆，適合賽前手動整理成靜態 JSON（不需要即時
  API），跟 `static/source_reputation.json` 類似的做法
- 幣種解鎖日（例如 SOL/BNB 的 vesting unlock）如果要做，來源可能要另外找

## 待 Ken 補的筆記

-

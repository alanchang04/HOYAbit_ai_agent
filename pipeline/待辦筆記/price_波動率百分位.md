# Price 歷史波動率百分位待辦

> 2026-07-21 討論起頭：對照 `07_流程圖迭代定案.md` Round 4 的窗口設計表——
> Price 技術面應該吃全歷史本地 CSV 算「歷史波動率百分位」（相對過去 5 年的
> 位置，零網路成本）。現況 `agent/collectors/price.py` 的
> `INDICATOR_WINDOW=121` 只抓約 4 個月資料，夠算 MA120，但算不出對全歷史的
> 百分位——`compute_technical_indicators()` 的 `volatility_pct` 目前只是
> 近 14 日 pstdev，不是百分位。

## 現況

- `load_ohlcv_tail(coin, data_dir, n=INDICATOR_WINDOW)` 只讀最後 121 列
- 要算百分位需要讀全部歷史列（5 年 ≈ 1825 列），跟 `MacroCollector` 的
  `compute_fng_percentile()` 邏輯類似，可能可以直接參考那段寫法

## 待 Ken 補的筆記

-

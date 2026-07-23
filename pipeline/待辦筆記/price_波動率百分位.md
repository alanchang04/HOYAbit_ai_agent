# Price 歷史波動率百分位待辦

✅ 已解決（2026-07-23）：prototype 完成並併回 `agent/collectors/price.py`
的 `compute_technical_indicators()`（新增 `compute_historical_volatility_percentile()`，
擴張視窗算全歷史百分位），真實 API 跑過 BTC 確認跟 prototype 數字一致
（vol=1.14%／percentile=5.1），`pytest -q` 231 全過。完整記錄見
`流程紀錄.md` Step 24 與「下一步」清單。尚未跟 alanchang 討論。

## 待 Ken 補的筆記

-

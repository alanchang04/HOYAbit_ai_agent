# Derivatives 正式化成 collector 待辦

> 2026-07-21 討論起頭：對照 `07_流程圖迭代定案.md` Round 4 的窗口設計表——
> Derivatives 建議窗口是近 7-30 天。現況這一類全部還停留在 `pipeline/`
> 底下的 prototype 腳本（永續基差 `fetch_realtime_price.py`＋
> `compute_perp_basis`、費率擁擠度 `fetch_funding_rate_percentile.py`、
> 跨幣費率差 `compute_cross_coin_funding_diff.py`、選擇權 IV
> `fetch_options_binance.py` 等），**還沒有正式併成
> `agent/collectors/derivatives.py`**，也就沒有統一套用這個窗口設計。

## 現況

- `pipeline/` 底下已有多個獨立 prototype，各自窗口可能不一致，需要盤點
- `07_流程圖迭代定案.md` 的最終方案流程圖裡已經把 `derivatives`（新）列為
  Phase 1 要新增的 collector（funding擁擠度/OI四象限/多空比/到期結構
  [層1]，Deribit選擇權(BTC/ETH) [層2]，Polymarket [層3]）

## 待處理方向（未定案，僅記錄想法）

- 先盤點 `pipeline/` 裡哪些 prototype 已經穩定可用，決定併入順序
- 統一套用 7-30 天窗口前，要先確認各 prototype 現在各自抓的是多長區間

## 待 Ken 補的筆記

-

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

## 2026-07-22：七項已併成正式 `agent/collectors/derivatives.py`

Ken 確認先在 `ken` 分支動手，之後再跟 alanchang 討論同步節奏（不是先討論才動手，
跟 07-20 費率擁擠度那次「先 prototype 再討論」的慣例一致，只是這次是把已經穩定
的 prototype 一次全部併成正式 collector）。

- 併入七項：費率擁擠度、OI×價格四象限、多空帳戶比背離、期貨到期結構、
  CME COT、選擇權 IV/Skew、CEX-DEX 費率差——邏輯照抄各自的 `pipeline/fetch_*.py`
  prototype，窗口不變（都已落在 window_policy.md 的 7-30 天建議範圍內）
- `SourceType` enum 新增 `DERIVATIVES`；`orchestrator.py` 的 `SOURCE_TYPES` 與
  `build_collectors()` 註冊 `DerivativesCollector`；`source_weights.py` 補
  fallback 權重 0.80（交易所/CFTC 公開數據，比照 onchain 0.85 但略低）；
  `fixtures/dry_run_evidence.json` 補 `derivatives` 區塊
- 單元測試 `tests/test_derivatives_collector.py`：七項證據各自產出、單一子來源
  失敗不影響其他子來源（跟 `price.py` 同一套隔離設計）、CME COT BNB 跳過、
  選擇權掛牌數不足跳過。`pytest -q` 196 全過
- 用 `scripts/test_collectors.py --coin BTC` / `--coin BNB` 對過真實 API：
  BTC 七項全部成功產出證據，BNB 六項（CME COT 依設計跳過，符合預期）
- **兩項刻意不併入**：跨幣費率差（雙幣比較題專用，跟 `relative.py` 一樣要兩幣
  一起算，塞不進單幣種 `fetch(coin)` 介面）、清算流（45 秒 WebSocket 監聽全市場
  一次拿五幣資料，跟其他子來源「打一次 API 拿一幣資料」模型不同，若照現有
  介面每幣各自監聽 45 秒等於浪費 5 倍時間，需要另外設計介面）
- **尚未跟 alanchang 討論**：目前只在 `ken` 分支，`derivatives.py` 是全新檔案
  沒改動他既有的 `price.py`/`onchain.py` 等，但 `schemas.py`（新增
  `SourceType.DERIVATIVES`）、`orchestrator.py`、`source_weights.py`、
  `fixtures/dry_run_evidence.json` 這四個共用檔案有改動，PR 前要先跟他過一輪

## 待 Ken 補的筆記

-

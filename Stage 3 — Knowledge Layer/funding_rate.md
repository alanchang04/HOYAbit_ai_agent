---
tags: [projects, hackathon, hoyabit, knowledge-layer, funding-rate]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer（示範：funding_rate），欄位對照 [[11流程圖模板]] Statistical Knowledge schema；references 為 2026-08-01 額外上網查證補充的公開文獻/產業資料，非編造
---

```yaml
# Stage 3 — Knowledge Layer，Statistical Knowledge 骨架（示範：funding_rate）
# 來源：11流程圖模板.md 的 Statistical Knowledge 範例。
# 這層是「這個 Factor 本身有哪些金融知識」，不是算出來的數字（跟
# factor_interpreter/feature_extraction.yaml 那份即時抓取算出來的不一樣）。
#
# 這版混合三種來源：
#   1. 流程紀錄.md「費率擁擠度」章節（Step 14）的既有 read/觀察文字
#   2. 2026-08-01 上網查證補的公開文獻/產業資料（見下方 references）
#   3. 2026-08-02 補查 supported_market_regimes／optional_inputs／conflicts
#      三個原本留空的欄位，一樣皆為搜尋當下可查到的真實連結，沒有編造
# ⚠️ minimum_horizon／maximum_horizon／persistence 這三項是產業部落格的
# 「經驗觀察」（例如「持續多日的極端費率、之後數月內出現反轉」），不是嚴謹
# 統計顯著性檢定過的數字，是概略描述，不是精確估計值，要當「方向感」看，
# 不能當回測門檻直接套用。supported_market_regimes／optional_inputs／
# conflicts 三項同樣屬於產業觀察等級，不是學術實證，標準跟上面一致。

knowledge:
  factor_id: funding_rate
  factor_name: 資金費率擁擠度（Funding Rate Percentile / Crowding）
  category: statistical

  # Time Property
  primary_horizon: 短期（永續合約每 8 小時結算一次，訊號用近 30 天/90 筆百分位排名）
  minimum_horizon: 數日（產業觀察：需連續多筆結算維持極端費率，單一筆極端讀數不足以構成訊號）
  maximum_horizon: 數週至數月（產業觀察：持續極端費率後的反轉常在數月內出現，見 references）
  persistence: 中低——費率本身每 8 小時重新結算，但其反映的「擁擠倉位」狀態可持續數日到數週才緩解或反轉

  # Scope
  supported_assets: [BTC, ETH, SOL, BNB, XRP]  # 五幣皆為 Binance USDⓈ-M 永續合約，皆可抓
  supported_market_regimes: 熊市／下跌趨勢中訊號較一致（費率下滑對應真實減倉行為）；牛市與轉折點附近訊號較不可靠——極端費率可能持續數週不觸發反轉，宜當「擁擠狀態」讀，不當「反轉時機」讀（見 Coinbase／Phemex 來源）
  supported_market_types: 永續合約（perpetual futures），非現貨

  # Data Dependency
  required_inputs: Binance USDⓈ-M /fapi/v1/fundingRate 近 90 筆歷史費率（約 30 天）
  optional_inputs: 跨交易所（如 Hyperliquid／Bybit／OKX）費率同時對照——單一交易所費率可能被該場地個別大戶扭曲，跨場地一致才是較穩健的擁擠度訊號（見下方 Hyperliquid+Binance／Sharpe.ai 來源）

  # Relationship
  confirms: open_interest（未平倉量）  # 產業共識：funding + OI 合看才能判斷「擁擠regime」——負費率＋OI攀升＝擁擠空單，正費率＋OI攀升＝擁擠多單，單看費率容易誤判（見下方 Gate Wiki／Lambda Finance 來源）
  conflicts: long_short_ratio（多空帳戶比）  # funding_rate 是「倉位大小加權」（大戶主導），long_short_ratio 是「帳戶數加權」（散戶主導），兩者可能背離——2026-04 實例：Hyperliquid 大戶大舉做多同時 funding 持續深度負值，但 Binance 帳戶比顯示散戶偏空，兩指標方向相反（見下方 CoinDesk 來源）
  independent: vol-compression（波動壓縮度）  # 流程紀錄.md 原話：費率擁擠度看「多空付費壓力方向」，vol-compression 看「波動大小」，兩者觀察不衝突，可視為獨立訊號並列（Step 14 實測結果段）

  # References（只存出處，不存評價）
  references:
    academic:
      - doi: 10.1111/mafi.70018  # Ackerer, Hugonnier, Jermann,《Perpetual Futures Pricing》, Mathematical Finance, 2026——永續合約/funding rate 定價的理論基礎
      - doi: 10.3390/math14020346  # 《The Two-Tiered Structure of Cryptocurrency Funding Rate Markets》, Mathematics, 2026——26 家交易所 funding rate 市場結構實證研究
    industry:
      - "Gate Wiki - How do futures open interest and funding rates signal crypto derivatives market trends (2026): https://web3.gate.com/crypto-wiki/article/how-do-futures-open-interest-and-funding-rates-signal-crypto-derivatives-market-trends-in-2026-20260202"
      - "Lambda Finance - Crypto Funding Rates and Open Interest: April 2026 Snapshot: https://www.lambdafin.com/articles/crypto-funding-rates-april-2026"
      - "Phemex - Bitcoin Negative Funding Rates 46 Days | Why Crowded Shorts Signal a Bottom: https://phemex.com/blogs/bitcoin-funding-rates-negative-46-days-ftx-bottom"
      - "Coinbase Institutional - A Primer on Perpetual Futures: https://www.coinbase.com/institutional/research-insights/research/market-intelligence/a-primer-on-perpetual-futures"
      - "Phemex Academy - Funding Rate Explained | How to Read Crypto Futures Funding as a Trading Signal: https://phemex.com/academy/what-is-funding-rate-in-crypto-futures"
      - "Blofin Academy - Funding + Open Interest: Simple Signals Traders Use (and Misuse): https://blofin.com/en/academy/education/funding-and-open-interest-signals"
      - "DEV Community (AlgoVaultLabs) - Hyperliquid plus Binance, a unified MCP for cross-venue funding rate signals: https://dev.to/algovaultlabs/hyperliquid-plus-binance-a-unified-mcp-for-cross-venue-funding-rate-signals-464f"
      - "Sharpe.ai - Crypto Funding Rate Tracker, 13 Exchanges, Annualized APR: https://www.sharpe.ai/products/funding-rates"
      - "CoinDesk - Bitcoin whales build long positions as funding stays deeply negative (2026-04-26): https://www.coindesk.com/markets/2026/04/26/bitcoin-whales-build-long-positions-as-funding-stays-deeply-negative"

  # Metadata
  version: 0.3
  last_updated: 2026-08-02
```

### 跟既有知識庫的關係

這份是照 [[11流程圖模板]] 的 Statistical Knowledge schema 手動研究、補齊出處寫的完整版，欄位比 `static/knowledge_lite.json` 裡 `funding_rate_pct`／`funding_rate_percentile` 兩張既有卡片豐富（多了 Time Property／Scope／Relationship／學術＋產業 references）。demo（`webapp/stage1_demo_api.py` 的 `/api/stage3/funding_rate`）目前接的是 `knowledge_lite.json` 那個較簡版本，還沒串上這份；要不要換成這份、或兩者怎麼並存，待 Ken 拍板。

### 待補

`static/knowledge_lite.json` 目前只有 10 張卡，Stage 2（`agent/research/feature_extraction.py`）實際能抽出 26 個 feature，還有 16 個缺卡（移動平均家族／波動度百分位 90d／原始市場報價／on-chain 鏈上資料四組）。Ken 之後會挑 5 個要補的，屆時逐一在這個資料夾底下開新檔案，格式比照本檔。

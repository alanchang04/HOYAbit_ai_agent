---
tags: [projects, hackathon, hoyabit, knowledge-layer, active-address]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer（示範：active_address），欄位對照 [[11流程圖模板]] Statistical Knowledge schema；references 為 2026-08-02 上網查證補充的公開文獻/產業資料，非編造；Empirical Validation 區塊沿用 [[09_權重改版草案]] 的 Internal Backtest 設計＋hash rate 那套「7 天變化率觸發→14天後方向命中率」方法論，用真實資料跑出來的，非編造
---

```yaml
# Stage 3 — Knowledge Layer，Statistical Knowledge 骨架（示範：active_address）
# 這層是「這個 Factor 本身有哪些金融知識」，不是算出來的數字（跟
# Stage 2 Feature Extraction/active_address.yaml 那份即時抓取算出來的不一樣）。
#
# ⚠️ 這份的內容特性跟 funding_rate 明顯不同，不是照抄同一套結論改個名字：
#   1. funding_rate 的產業文獻多半肯定其短期訊號價值；active_address 的
#      2026 年最新研究反而在講「這類鏈上指標的預測力正在減弱」——ETF 通過、
#      機構化之後，價格走勢跟鏈上使用量脫鉤（見下方 deepbluealpha／
#      valuethemarkets 來源），這是這個 factor 特有的、且是近期才浮現的警訊。
#   2. 學術文獻（MDPI/JRFM 2024）明確測過 Metcalfe's Law（active_address
#      的理論基礎）樣本內能解釋報酬，但樣本外幾乎沒有預測力——這跟
#      funding_rate.yaml 的 IC 示範值定位不同：active_address 現階段更適合
#      當「網路基本面背景」讀，不適合直接當短線 timing 訊號用。
#   primary_horizon／minimum_horizon／maximum_horizon 這三項因此定得比
#   funding_rate 更保守、更偏長期，是根據上述兩份實證文獻的結論調整的，
#   不是隨意套用同一個模板數字。

knowledge:
  factor_id: active_address
  factor_name: 鏈上活躍地址數（On-chain Active Addresses）
  category: statistical

  # Time Property
  primary_horizon: 中長期（結構性網路使用趨勢，非短線 timing 訊號；blockchain.info 每日一筆）
  minimum_horizon: 數週（單日跳動常見資料 revision，見 Stage 2 active_address.yaml 的異常標記，不可用單日數字判斷）
  maximum_horizon: 數月至跨週期（Metcalfe's Law 理論上對應網路價值的中長期成長趨勢，非用於捕捉短期反轉）
  persistence: 中——2026 年實證顯示 ETF 通過後價格與鏈上使用量出現「脫鉤」，這個 factor 的訊號延續性比 2021 年前的週期弱，需搭配其他訊號交叉驗證

  # Scope
  supported_assets: [BTC]  # 本文件示範資料來源＝blockchain.info（僅 BTC UTXO 鏈可用）；ETH/SOL/BNB/XRP 若要同類指標需另找對應鏈上資料源，不能直接套用同一個端點
  supported_market_regimes: 網路使用量處於成長期（adoption momentum > 1.0，見產業觀察）時訊號較清楚；機構化/ETF 主導的牛市中訊號較弱——2024 年後價格可能在鏈上活躍度停滯甚至下滑時持續上漲，宜當「基本面背景」讀，不當「進出場時機」讀（見下方 deepbluealpha 來源）
  supported_market_types: 現貨鏈上活動，非衍生品市場——跟 funding_rate（衍生品）是完全不同的資料域

  # Data Dependency
  required_inputs: blockchain.info Charts API `n-unique-addresses`（BTC，免key，每日一筆）
  optional_inputs: 市值（計算 NVM／NVT 比率需要）；hash-rate（Metcalfe's Law 常跟網路算力一起看，交叉驗證是否為真實使用成長還是位址灌水）

  # Relationship
  confirms: hash-rate（網路算力）  # 兩者常一起用來判斷「真實網路成長」還是單一指標失真，Alabi (2017) 的原始研究就是用 hash-rate 佐證 Metcalfe's Law 對鏈上網路的適用性
  conflicts: price（現貨價格走勢）  # 2026 研究明確指出：ETF 通過後價格與活躍地址數出現結構性背離（價格漲、地址數不漲甚至跌），這跟 funding_rate 的 conflicts（long_short_ratio，兩者都是衍生品市場內部指標）性質不同——這裡是「鏈上基本面」vs「價格」兩個不同層次的背離
  independent: funding_rate（資金費率擁擠度）  # 一個是現貨鏈上使用量，一個是衍生品市場倉位擁擠度，資料域不重疊，可視為獨立訊號並列

  # References（只存出處，不存評價）
  references:
    academic:
      - doi: 10.1016/j.elerap.2017.06.003  # Alabi, K.,《Digital blockchain networks appear to be following Metcalfe's Law》, Electronic Commerce Research and Applications, 2017——active address 作為網路價值代理變數的原始實證基礎
      - doi: 10.3390/jrfm17100443  # 《Bitcoin Return Prediction: Is It Possible via Stock-to-Flow, Metcalfe's Law, Technical Analysis, or Market Sentiment?》, JRFM, 2024——關鍵發現：Metcalfe's Law 樣本內能解釋報酬，但樣本外幾乎沒有預測力，是本文件把 primary_horizon 定得保守的直接依據
    industry:
      - "DeepBlueAlpha (Ethereum Whale Intelligence) - Bitcoin On-Chain Signals in 2026: 5 Metrics Analysts Are Watching: https://deepbluealpha.io/research/bitcoin-bottom-signals-2026-on-chain"
      - "ValueTheMarkets - Insights into the Recent Rise in Bitcoin Active Addresses: https://www.valuethemarkets.com/cryptocurrency/news/insights-into-the-recent-rise-in-bitcoin-active-addresses"
      - "Glassnode Research - BTC Market Pulse: Week 31 (2026): https://research.glassnode.com/btc-market-pulse-week-31-2026/"
      - "Interdax Help Center - What is the Network Value to Metcalfe (NVM) Ratio?: https://help.interdax.com/hc/en-001/articles/360014346457-What-is-the-Network-Value-to-Metcalfe-NVM-Ratio-"
      - "CryptoQuant Data Guide - NVM Ratio: https://dataguide.cryptoquant.com/network-indicators/nvm-ratio"

  # Metadata
  version: 0.2
  last_updated: 2026-08-02

# Empirical Validation（對應 09_權重改版草案.md「Empirical Validation」設計：
# 內部回測，跟上面 references 的外部文獻分開存——這裡是「我們自己資料驗證過」，
# 上面是「文獻怎麼說」）
empirical_validation:
  internal_backtest:
    method: 比照 09_權重改版草案.md「Onchain(BTC) hash rate 訊號」同一套規則——
      7 天變化率 >+5% → 方向 +1，<-5% → 方向 -1，其餘不觸發；比對 14 天後
      BTC 收盤價報酬方向
    data: blockchain.info n-unique-addresses（5年，2021-08-02~2026-07-31）×
      raw_data/price/BTC/BTC_daily_ohlcv.csv，重疊 1821 天
    trigger_rate: 0.479  # 862/1800 個有效交易日觸發，門檻可能同 hash rate 案例一樣偏鬆
    comparable_sample: 862
    hit_rate: 0.5093  # 幾乎等於丟銅板
    z_vs_random_guess: 0.545  # 二項分布近似 z 檢定，遠低於顯著門檻（|z|>1.96）
    conclusion: 跟 09 文件裡 hash rate 的 HitRate=0.499 結論一致——「地址數上升＝
      看多」這個聽起來合理的敘事，對 14 天報酬方向沒有統計上可信的預測力，
      這筆是本文件 primary_horizon 定得保守、且跟 confirms/conflicts
      不寫方向性推論的直接依據，不是只憑上面兩篇學術文獻的間接推論
    last_run: 2026-08-02
```

### 跟既有知識庫的關係

這份是跟 [[Stage 3 — Knowledge Layer/funding_rate]] 同一批（2026-08-02）新建的示範，欄位結構完全比照，但**內容結論刻意不對齊**——active_address 的近期實證（ETF 後鏈上/價格脫鉤、Metcalfe's Law 樣本外無預測力、內部回測 HitRate≈0.51 幾乎等於瞎猜）跟 funding_rate 的產業文獻論調不同，這是照 Ken 的要求「根據 data 制定不同的內容」，不是同一套模板換個 factor 名字。

`empirical_validation` 這個區塊是看了 [[09_權重改版草案]] 才補上的——09 文件明確設計了「Empirical Validation（內部回測）」要跟「Historical Support（外部文獻）」分開存，而且 09 已經示範過同一套方法論在 hash rate 上的真實跑法（HitRate=0.499）。這裡直接沿用同一套規則跑 active_address，跑出來的 0.5093／z=0.545 是真實計算結果，不是套用 hash rate 的數字改個名字。

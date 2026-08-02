---
tags: [projects, hackathon, hoyabit, knowledge-layer, price]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer（示範：price）；2026-08-02 新增，回應「Stage 2-6 六個既有 factor 都沒有一張純粹的『現貨報價』卡」這個缺口——active_address.md 自己的 conflicts 欄位早就列了 price，但這個因子本身一直沒有卡片，圖上一直是 referenced_but_no_card。欄位對照 [[11流程圖模板]] Statistical Knowledge schema；references 為 2026-08-02 上網查證補充的公開文獻/產業資料，非編造
---

```yaml
# Stage 3 — Knowledge Layer，Statistical Knowledge 骨架（示範：price）
#
# 這份只涵蓋「即時現貨報價快照」（當下價格＋24 小時漲跌幅＋24 小時成交量），
# 不是 agent/collectors/price.py 產出的全部價格證據——那支 collector 另外還會
# 產出五檔粒度區間統計、技術指標（SMA/RSI/波動率/量能）、長期結構位置、永續
# 基差，一次全部搬進 demo 的 Stage 2-6 範圍太大，2026-08-02 拍板先做「報價」
# 這張最基礎、任何 Horizon 都用得到的快照，其餘留待之後視需要再補（見下方
# 「跟既有知識庫的關係」）。

knowledge:
  factor_id: price
  factor_name: 即時現貨報價（Spot Price Quote）
  category: statistical

  # Time Property
  primary_horizon: 即時快照（Spot）——抓取當下的價格與 24 小時漲跌幅，不是某個觀察窗口算出來的統計量
  minimum_horizon: 無下限，任何時間點都可即時查詢
  maximum_horizon: 不適用——這是當下的一次性快照，不能外推成更長窗口的趨勢（要看更長趨勢請看 agent/collectors/price.py 的五檔粒度區間統計或技術指標，這裡只回答「現在多少錢、比 24 小時前變動多少」）
  persistence: 極短——下一次抓取就是全新的值，24 小時漲跌幅本身是持續滾動的窗口，不會停留

  # Scope
  supported_assets: [BTC, ETH, SOL, BNB, XRP]  # CoinGecko／CryptoCompare 五幣皆有現貨報價，皆可抓
  supported_market_regimes: 不分市場狀態皆可用——這是客觀讀數快照，不是狀態依存的解讀型訊號（跟 active_address 那種「牛市/熊市讀法不同」的訊號性質不同）
  supported_market_types: 現貨報價（CoinGecko／CryptoCompare 彙整的現貨市場加權平均價），不是永續合約 mark price——跟 funding_rate 抓的衍生品資料是不同市場

  # Data Dependency
  required_inputs: CoinGecko /simple/price（ids、vs_currencies=usd、include_24hr_change、include_24hr_vol，免 key）
  optional_inputs: CryptoCompare /data/pricemultifull 作為 CoinGecko 失敗時的備援報價來源——跟 agent/collectors/price.py 現有的容錯順序一致，demo 沿用同一順序，不是另外設計一套

  # Relationship
  confirms: volume_change_24h（24 小時成交量變化）  # 量價同步是技術分析最基礎的共識：價漲量增／價跌量縮才是健康趨勢，價量背離通常是警訊（見下方 industry 來源）
  conflicts: active_address（鏈上活躍地址數）  # 對應 [[Stage 3 — Knowledge Layer/active_address]] 自己列的 conflicts=price——牛市末期常見「價格續漲、新增地址數卻縮、籌碼在存量錢包內轉手」的背離型態，兩份文件互相對應同一條關係
  independent: cpi（美國消費者物價指數公布）  # 24 小時內的現貨價格變動是短期市場微結構訊號，跟月頻總經事件是不同時間尺度、不同成因，不假設兩者存在固定關係

  # References（只存出處，不存評價；學界對「動量訊號到底是延續還是反轉」沒有共識，兩篇都在討論這個張力，不是各自支持一個方向）
  references:
    academic:
      - doi: 10.1016/j.najef.2022.101733  # Wen, Bouri, Xu, Zhao,《Intraday Return Predictability in the Cryptocurrency Markets: Momentum, Reversal, or Both》, North American Journal of Economics and Finance, 2022——高頻現貨報價的日內可預測性實證，同時存在動量與反轉，方向會隨流動性與大事件（如 FOMC）改變，不是單一方向
      - doi: 10.1016/j.ribaf.2019.101176  # Chu, Chan, Zhang,《High Frequency Momentum Trading with Cryptocurrencies》, Research in International Business and Finance, 2020——七大加密貨幣的高頻動量策略實證，顯示動量策略在加密市場有潛力但效果隨資產而異
    industry:
      - "CoinGecko API Reference - Coin Price by IDs, Symbols, or Names（/simple/price，含 include_24hr_change／include_24hr_vol 參數）: https://docs.coingecko.com/reference/simple-price"
      - "CryptoCompare Min-API Documentation - Multiple Symbols Full Data（/data/pricemultifull，CoinGecko 失敗時備援端點）: https://min-api.cryptocompare.com/documentation?key=Price&cat=multipleSymbolsFullPriceEndpoint"

  # Metadata
  version: 0.1
  last_updated: 2026-08-02
```

### 跟既有知識庫的關係

這是六個既有 factor 之外新補的第七個。缺口不是憑空發現的：[[Stage 3 — Knowledge Layer/active_address]] 的 `conflicts` 欄位從一開始就寫著 `price`，但這個因子本身從來沒有對應卡片，Stage 6 Evidence Graph 每次跑都會把它列進 `referenced_but_no_card`——這份補上之後，那條邊終於連得上，`price` 也不再是圖上「被提到但不存在」的孤兒節點。

`agent/collectors/price.py` 實際上會產出遠多於這裡的價格證據（五檔粒度區間統計、技術指標、長期結構位置、永續基差），2026-08-02 Ken 拍板先做「即時報價」這一張——理由是它是唯一不需要任何回看窗口、任何 Horizon 查詢都能給出東西的價格證據，其餘幾種之後視需要再各自補一張，不是這份的範圍。

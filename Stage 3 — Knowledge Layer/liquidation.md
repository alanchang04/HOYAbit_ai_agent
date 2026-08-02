---
tags: [projects, hackathon, hoyabit, knowledge-layer, liquidation]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer（示範：liquidation），欄位對照 [[11流程圖模板]] Statistical Knowledge schema；references 為 2026-08-02 上網查證補充的公開文獻/產業資料，非編造
---

```yaml
# Stage 3 — Knowledge Layer，Statistical Knowledge 骨架（示範：liquidation）
# 這層是「這個 Factor 本身有哪些金融知識」，不是算出來的數字（跟
# Stage 2 Feature Extraction/liquidation.yaml 那份即時監聽的樣本不一樣）。
#
# ⚠️ 這份是三份新示範裡跟資料現實落差最大的一份，要老實面對：
#   Stage 2 已經記錄了結構性限制——我們的資料源（Binance WebSocket）只能
#   即時監聽，查不到歷史清算單，所以「我們自己回測出來的 primary_horizon／
#   persistence」在這個 factor 上**不存在**，沒有數字可以填。
#   但下面 Time Property 欄位不是留白——是改用**學術文獻對「清算連鎖」這個
#   現象本身的研究結論**來填，這是文獻上對這個現象的一般性描述，不是
#   我們自己資料驗證過的數字，兩者性質不同，要分清楚：
#     - 這裡填的是「業界／學界怎麼理解這個現象」（Knowledge，Prior）
#     - Stage 2 那份填的是「我們能不能量測到」（Feature，Fact）
#     - 兩者不一致（文獻很清楚，我們量不到）本身就是這個 factor 的知識之一
#   supported_market_regimes／confirms 這兩項可以有實質內容，因為文獻對
#   「清算前兆訊號」有具體共識（funding+OI+liquidation heatmap 三者一起看），
#   不受我們資料源限制影響——那是別人怎麼量測，不是我們怎麼量測。

knowledge:
  factor_id: liquidation
  factor_name: 清算流／連鎖清算（Liquidation Cascade）
  category: statistical

  # Time Property（來自文獻對現象本身的描述，非本專案資料驗證過的數字——見上方說明）
  primary_horizon: 極短期（分鐘級——學術實證「Anatomy of a Crypto Cascade」用逐分鐘資料分析 2025-10 崩盤，顯示連鎖清算是分鐘尺度的急速事件，非日/週尺度訊號）
  minimum_horizon: 分鐘（單次連鎖清算事件本身的展開時間）
  maximum_horizon: 不適用——連鎖清算是離散事件（discontinuous event），不是持續性趨勢，沒有「延續多久」的概念，事件結束後市場結構重置（見下方 arxiv 2607.27070：多數個案有「critical slowing down」前兆，但少數新聞驅動的外生衝擊型完全沒有前兆，兩種類型不能用同一套時間尺度描述）
  persistence: 不適用——這是事件型 factor，不是持續存在的狀態量，「持續性」問題本身對這個 factor 不成立，跟 funding_rate／active_address／cpi 三份都不同

  # Scope
  supported_assets: [BTC, ETH, SOL, BNB, XRP]  # Binance USDⓈ-M 永續合約 forceOrder 頻道涵蓋五幣，但如 Stage 2 所述，只有「當下監聽窗口」，非歷史查詢
  supported_market_regimes: 高槓桿、單邊擁擠倉位環境下風險最高（見下方 tradelink／gate wiki 來源：funding rate 持續偏高、OI 同步攀升時，清算連鎖風險上升）；低槓桿、雙邊倉位平衡的市場此 factor 訊號意義不大
  supported_market_types: 永續合約（perpetual futures）強平機制，非現貨——跟 funding_rate 同一個資料域（衍生品），可視為同源訊號

  # Data Dependency
  required_inputs: Binance USDⓈ-M 合約 WebSocket `!forceOrder@arr` 即時監聽樣本（非查詢式歷史資料，見 Stage 2 liquidation.yaml 結構性限制說明）
  optional_inputs: funding_rate（資金費率）＋ open_interest（未平倉量）——文獻明確指出三者合看才是有效的前兆訊號組合，單看清算數字本身（尤其是我們只能拿到即時監聽樣本時）訊號強度有限

  # Relationship
  confirms: funding_rate ＋ open_interest（未平倉量）  # 文獻共識：「traders spot cascade risk building up by watching open interest, funding rates, and liquidation heatmaps together, since a spike in any one on its own is a weaker signal」——這條直接呼應 [[Stage 3 — Knowledge Layer/funding_rate]] 裡 funding_rate.confirms=open_interest 那條，三者是同一組總體訊號的不同切面
  conflicts: （無已知穩定的矛盾對象，見下方說明）  # 清算多半是 funding+OI 訊號已經指出的擁擠倉位「兌現」的結果，是同向確認而非獨立對抗訊號，跟 funding_rate.conflicts=long_short_ratio 那種「兩指標可能背離」的性質不同，這裡誠實列空
  independent: cpi（總經數據）  # 文獻區分「內生擁擠倉位堆積」與「外生新聞衝擊」兩種清算連鎖類型（見 arxiv 2607.27070），後者常由總經意外事件觸發，但清算連鎖本身的機制（強平瀑布）跟 CPI 數字是否公布無直接因果關係，可視為獨立訊號並列

  # References（只存出處，不存評價）
  references:
    academic:
      - arxiv: "2607.27070"  # 《Where does the criticality live? Early-warning signals are event-heterogeneous across seven crypto-perpetual liquidation cascades》——七個 BTC 連鎖清算事件的實證，區分「內生堆積型」（有前兆）與「外生衝擊型」（無前兆）兩類
      - ssrn: "6579278"  # Lim, B.C.,《Anatomy of a Crypto Cascade: Minute-Level Evidence from the October 2025 Crash》——逐分鐘資料實證連鎖清算的展開速度與結構
    industry:
      - "Gate Wiki - What do crypto derivatives market signals reveal about future price movements: analyzing futures open interest, funding rates, and liquidation data: https://web3.gate.com/crypto-wiki/article/what-do-crypto-derivatives-market-signals-reveal-about-future-price-movements-analyzing-futures-open-interest-funding-rates-and-liquidation-data-20260126"
      - "TradeLink - Funding Rate + Open Interest: How to Spot Liquidations: https://tradelink.pro/blog/funding-rate-open-interest/"
      - "Amberdata Blog - Liquidations in Crypto: How to Anticipate Volatile Market Moves: https://blog.amberdata.io/liquidations-in-crypto-how-to-anticipate-volatile-market-moves"
      - "Mudrex Learn - What Is Liquidation Cascade In Crypto Futures Trading? (2026): https://mudrex.com/learn/what-is-liquidation-cascade-in-crypto-futures/"

  # Metadata
  version: 0.1
  last_updated: 2026-08-02
```

### 跟既有知識庫的關係

這份是跟 [[Stage 3 — Knowledge Layer/funding_rate]]／[[Stage 3 — Knowledge Layer/active_address]]／[[Stage 3 — Knowledge Layer/cpi]] 同一批（2026-08-02）新建的示範，但誠實程度上要求最高——`maximum_horizon`／`persistence` 兩項直接標「不適用」，`conflicts` 留空，都是因為這個 factor 的資料現實（只能即時監聽，無歷史）跟現象本身的學術知識（分鐘級離散事件）兜不起來，硬填一個「看起來完整」的答案會比留白更誤導。這是本輪三份新示範裡跟 Ken 說的「根據 data 制定不同的內容」對比最鮮明的一份。

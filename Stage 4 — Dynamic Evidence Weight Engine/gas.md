---
tags: [projects, hackathon, hoyabit, weight-engine, gas]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine（gas）；2026-08-02 實測，ic 為真實計算值
summary: ETH gas 的 Prior Weight——horizon=14 實測 ic=+0.0187／n=1874；⚠️ 資料源有 4021 天但價格基準只有 1888 天，樣本被交集卡住
---

```yaml
# Stage 4 — Dynamic Evidence Weight Engine（gas）
#
# ✅ ic 是 2026-08-02 用真實資料算出來的：
#     factor 序列 = etherscan.io/chart/gasprice CSV（4021 筆，2015-07-30~2026-08-01）
#     價格序列   = raw_data/price/ETH/ETH_daily_ohlcv.csv（1888 筆，2021-06-01 起）
#     算法       = 跟 active_address／hash_rate 同一套 rolling_spearman_ic

weight:
  factor_id: gas

  historical_predictability:
    ic:
      algorithm: rolling_spearman_ic
      formula: |
        IC(horizon) = spearman_corr(
          factor_value(t),           # = 當日平均 gas price（Gwei）
          forward_return(t, t + horizon)
        )  for t in [now - horizon, now]
      input: horizon
      example_run:
        horizon: 14
        sample_size: 1874           # ⚠️ 見下方「樣本被什麼卡住」
        computed_value: 0.0187
      # 同日一併算的其他 horizon：
      #   horizon=7   ic=+0.0323  n=1881   → prior_strength 0.2493
      #   horizon=14  ic=+0.0187  n=1874   → prior_strength 0.1529
      #   horizon=30  ic=+0.0379  n=1858   → prior_strength 0.2858
      # ⚠️ 注意這裡**不是單調的**（0.0323 → 0.0187 → 0.0379），跟 hash_rate 的
      # 單調變強不一樣。14 天那個凹陷沒有現成解釋，三個點也不足以判斷是真的
      # 尺度效應還是雜訊——**不要在報告裡把它講成「gas 在 14 天最沒用」**，
      # 那是過度解讀三個數字。誠實的講法：這個 factor 的 ic 在 0.02~0.04 之間
      # 波動，沒有明顯的 horizon 傾向。

  # ⚠️ 樣本被什麼卡住（這份最該記住的一件事）
  # Stage 2 抓得到 4021 天 gas 資料，但 ic 要跟價格對齊算，價格基準 CSV 只有
  # 1888 天（2021-06-01 起）。交集後 horizon=14 實際只有 1874 筆——**4021 天裡
  # 有 2100 多天沒有對應價格可比，直接被丟掉**。
  # 這推翻了「gas 是樣本最厚的 factor」這個直覺：它的可用樣本(1874)跟
  # hash_rate(1808)幾乎一樣，收縮係數 0.888 vs 0.886，差異可以忽略。
  # 教訓：判斷一個 factor 的回測樣本量，要看**它跟價格序列的交集**，不是看
  # 資料源自己宣稱涵蓋多久。

  prior_weight:
    basis: rolling_spearman_ic
    value: 0.0187                   # ＝ horizon=14 的 ic 原值
    scale: raw_ic                   # 換算：|0.0187| → 收縮 √1874/(√1874+√30)=0.888
                                    # → 1-exp(-0.0187×0.888/0.1) = 0.1529
    confidence: high                # 樣本 1874，跟 hash_rate 同一個量級。
                                    # 同樣提醒：confidence 高 ≠ 有預測力
    reason: |
      樣本 1874 天、收縮係數 0.888 幾乎不打折，數字本身可信。但 ic 只有 0.0187，
      跟 hash_rate(0.0242)／active_address(0.0041) 同屬「測過，確實很弱」那一類，
      不是「沒得測」。
      ⚠️ 另一層要注意的：這個 ic 是拿**橫跨 EIP-1559 與 L2 分流**的序列算的
      （見 Stage 3 known_limitation）。前後段分布差兩個數量級，Spearman 用的是
      排名所以不會被數值尺度直接扭曲，但「同一個排名位置在 2021 年跟 2026 年
      代表的市場狀態不同」這件事，rank correlation 也解不掉。這是這份 ic 最大的
      方法論保留，不是可以靠加樣本解決的問題。

  ####################
  # Dynamic Modifier
  ####################
  market_regime:
    classification:
  time_horizon_match:            # 比對 Stage1 horizon 與 applicable_days=[1, 60]
  cross_source_consensus:        # 讀 Stage 3 confirms(price)，今天方向是否同向；conflicts 為 null 不比
  freshness:                     # 對照 update_frequency=每日一筆

  context_modifier:
  final_weight:                  # = prior_strength × context_modifier
                                 #   prior_strength = 0.1529（horizon=14 時）
```

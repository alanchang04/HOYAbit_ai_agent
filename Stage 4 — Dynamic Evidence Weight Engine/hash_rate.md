---
tags: [projects, hackathon, hoyabit, weight-engine, hash-rate]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine（hash_rate）；2026-08-02 實測，ic 為真實計算值
summary: BTC hash_rate 的 Prior Weight——horizon=14 實測 ic=+0.0242／n=1808，樣本厚度僅次於 gas，是這輪 confidence 最高的兩份之一
---

```yaml
# Stage 4 — Dynamic Evidence Weight Engine（hash_rate）
#
# ✅ 這份的 ic 是 2026-08-02 用真實資料算出來的，不是示範值：
#     factor 序列 = blockchain.info charts hash-rate（1822 筆，2021-08-03~2026-08-01）
#     價格序列   = raw_data/price/BTC/BTC_daily_ohlcv.csv（主辦方共同基準 CSV）
#     算法       = 跟 active_address 同一套 rolling_spearman_ic

weight:
  factor_id: hash_rate

  ####################
  # Prior Weight
  ####################
  historical_predictability:
    ic:
      algorithm: rolling_spearman_ic
      formula: |
        IC(horizon) = spearman_corr(
          factor_value(t),           # = 當日算力估計值（Stage 2 抓的原始值，未換算單位）
          forward_return(t, t + horizon)
        )  for t in [now - horizon, now]
      input: horizon                # 正式運作時由 LLM 依 Stage 1 Horizon 動態給值
      example_run:
        horizon: 14
        sample_size: 1808           # 重疊區間 2021-08-03 ~ 2026-08-01
        computed_value: 0.0242
      # 同日一併算的其他 horizon（記錄下來，因為它顯示出方向性一致的尺度效應）：
      #   horizon=7   ic=+0.0075  n=1815   → prior_strength 0.0644
      #   horizon=14  ic=+0.0242  n=1808   → prior_strength 0.1929
      #   horizon=30  ic=+0.0316  n=1792   → prior_strength 0.2440
      # 解讀：ic 隨 horizon 拉長**單調變強**，跟 Stage 3 寫的「這是中長期資本支出
      # 驅動的 factor、不適合短 horizon」互相印證——這是這輪少數幾個「知識層的
      # 定性論述被回測數字支持」的案例，不是事後湊出來的解釋。
      # ⚠️ 但要誠實：即使 horizon=30，ic 也只有 0.0316，絕對強度仍然很弱，
      # 「方向對」跟「有用」是兩回事。

  prior_weight:
    basis: rolling_spearman_ic
    value: 0.0242                   # ＝ horizon=14 的 ic 原值（不預先換算，見 scale）
    scale: raw_ic                   # demo 讀到 raw_ic 會自動跑三步換算：
                                    # |0.0242| → 樣本收縮 √1808/(√1808+√30)=0.886
                                    # → 1-exp(-0.0242×0.886/0.1) = 0.1929
    confidence: high                # ⚠️ 這輪第一個標 high 的——樣本 1808，跟 active_address
                                    # 的 1807 同一個量級，遠高於 panews_sentiment(44)／etf(8)。
                                    # 注意 confidence 高指的是「這個數字可信」，
                                    # **不是**「這個 factor 有預測力」——ic=0.0242 本身很弱
    reason: |
      樣本 1808 天、五年真實歷史，收縮係數 0.886 幾乎不打折，算出來的 0.0242
      可以當成這個 factor 在 14 天 horizon 下的真實預測力估計，不是抽樣運氣。
      結論跟 active_address（ic=0.0041）方向一致：鏈上結構性指標對中短期報酬
      的線性/單調預測力都很弱。差別在 hash_rate 隨 horizon 拉長會變強（0.0075
      → 0.0242 → 0.0316），active_address 沒有這個性質，所以 hash_rate 在
      長 horizon 查詢時排序會明顯前於 active_address。

  ####################
  # Dynamic Modifier
  ####################
  market_regime:
    classification:              # rate_cutting／rate_hiking／rate_hold
  time_horizon_match:            # 比對 Stage1 horizon 與 Stage3 applicable_days=[30,365]
                                 # ⚠️ 查 2 週時 match = 14/30 = 0.47，查 1 年時 match = 1.00——
                                 # 這個 factor 是少數「長 horizon 查詢才吃得到滿分」的
  cross_source_consensus:        # 讀 Stage 3 confirms(active_address)／conflicts(price)，今天方向是否同向
  freshness:                     # 對照 update_frequency=每日一筆

  context_modifier:              # 由 LLM 根據上述線索給值，range=[0.5, 2.0]，非公式
  final_weight:                  # = prior_strength × context_modifier
                                 #   prior_strength = 0.1929（horizon=14 時）
```

## 這份跟 active_address 放在一起看才有意義

兩張卡都是 BTC 鏈上指標、樣本都是 1800 出頭、ic 都很弱，但**弱的方式不一樣**：

| | active_address | hash_rate |
|---|---|---|
| horizon=14 ic | 0.0041 | 0.0242 |
| 隨 horizon 拉長 | 沒有測 | 單調變強（0.0075→0.0242→0.0316）|
| Stage 3 宣稱的尺度 | [14, 365] | [30, 365] |
| 回測是否支持宣稱 | 不確定 | ✅ 支持 |

這個對照本身是 Stage 3「applicable_days 是人工換算、之後應由回測覆蓋」那條註記的
第一個實例——hash_rate 的回測結果跟人工換算的區間方向一致，可以視為初步驗證。

---
tags: [projects, hackathon, hoyabit, weight-engine, active-address]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine（示範：active_address）；ic 為真實計算值，非編造，算法與資料見下方
---

```yaml
# Stage 4 — Dynamic Evidence Weight Engine（示範：active_address）
# 對應 13_流程圖迭代定案v2.md Stage 4：ic 吃 Horizon 當參數的算法
# （rolling_spearman_ic），這裡不是套公式的示範殼子，是真的拿
# Stage 3 active_address.md 那份 empirical_validation 用的同一批資料
# （blockchain.info 5年 n-unique-addresses × BTC 收盤價，重疊 1821 天）
# 算出來的，horizon=14 天，跟 Stage 3 hit-rate 回測用同一個 horizon，方便對照。

weight:
  factor_id: active_address

  ####################
  # Prior Weight（來自 Knowledge，慢變動）
  ####################
  historical_predictability:
    ic:
      algorithm: rolling_spearman_ic
      formula: |
        IC(horizon) = spearman_corr(
          factor_value(t),
          forward_return(t, t + horizon)
        )  for t in [now - horizon, now]
      input: horizon                # 正式運作時由 LLM 依 Stage 1 判斷出的 Horizon 動態給值，不是寫死參數——
                                     # 每次呼叫 horizon 可能不同，ic 要跟著重新算，這裡沒有「固定 horizon=14」這回事
      example_run:                  # 這裡記錄的是「horizon=14 這個具體輸入」跑出來的一次示範結果，不是算法本身的固定值
        horizon: 14                 # 示範選這個數字是為了跟 Stage 3 hit-rate 回測對照，換一個 horizon 會算出不同的 computed_value
        computed_value: 0.0041      # 真實計算值：spearman_corr(現值, 14天後BTC報酬)，樣本數 1807，2021-08-02~2026-07-31
        # 解讀：0.0041 幾乎等於 0（IC 理論範圍 -1~1，>0.05 才算有一點參考價值），
        # 跟 Stage 3 empirical_validation.hit_rate=0.5093 是同一份資料算出來的
        # 兩個獨立指標，結論互相印證：active_address 現值對 14 天後報酬沒有
        # 統計上可信的預測力，不是抽樣運氣不好，是兩種算法都測不到訊號
    # hit_rate:                     # 見 Stage 3 empirical_validation.hit_rate = 0.5093（用觸發式二元命中率算的，跟這裡連續值算 IC 是不同方法但已在 Stage 3 記錄，這裡不重複列）
    # normalization:                # 正規化公式，待 Ken 校準，先註解
  # source_reliability:              # 待來源可信度分級表定案，先註解
  # historical_support:              # 對應 Stage 3 references 欄位怎麼轉成分數，待定，先註解

  ####################
  # Dynamic Modifier（來自今日市場，快變動——餵給 LLM 當線索，不套公式）
  ####################
  market_regime:
    classification:              # rate_cutting／rate_hiking／rate_hold 三態，資料來源＝FOMC 利率決議方向（沿用 ATR 定義）
  time_horizon_match:            # 比對 Stage1 horizon 與 Stage3 primary_horizon（中長期）的接近程度
  cross_source_consensus:        # 讀 Stage 3 Knowledge.confirms(hash-rate)／conflicts(price) 清單，今天方向是否同向
  freshness:                     # 資料時間戳距離現在多久，注意 Stage 2 已標記 blockchain.info 常有隔天補齊的 revision 現象，freshness 判斷要考慮這點

  context_modifier:              # 由 LLM 根據上述線索解釋給出，range=[0.5, 2.0]，非公式計算
  final_weight:                  # = prior_weight（極低，因 ic≈0）× context_modifier（LLM 給的數字）
                                  # ⚠️ prior_weight 本身趨近 0 時，不管 context_modifier 給多少，
                                  # final_weight 都會很小——這是這個 factor 目前的真實狀態，不是算法錯誤
```

### 這份的特殊之處

`ic: 0.0041` 是這輪三個新示範裡**唯一有真實回測數字可填**的一個（cpi 改分類成 Event Factor 沒有 ic 概念，liquidation 資料源結構性缺歷史序列算不出 ic），也是三個裡面唯一能完整示範 Stage 4 這套 `rolling_spearman_ic` 算法真的跑起來長什麼樣子的案例。跟 Stage 3 的 `empirical_validation.hit_rate=0.5093` 是同一批原始資料、兩種不同統計方法算出來的，結論互相印證：這個 factor 現階段對短期報酬沒有預測力。

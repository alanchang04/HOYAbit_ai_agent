---
tags: [projects, hackathon, hoyabit, weight-engine, liquidation]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine（示範：liquidation）；ic 結構性無法計算（資料源限制），Prior Weight 改用 Domain Knowledge 給理由（確認性訊號＋資料侷限，2026-08-02）
---

```yaml
# Stage 4 — Dynamic Evidence Weight Engine（示範：liquidation）
#
# ⚠️ 跟 cpi 那份不同類的「沒有 ic」——cpi 是分類錯誤（該用 Event Factor），
# liquidation 分類本身沒錯（歸在 Statistical/Derivatives），但 Stage 2 已經
# 記錄過根本限制：Binance 查歷史清算單的 REST API 已停用，只能即時監聽
# 固定時間窗，沒有 factor_value(t) 的歷史時間序列可以拿來算
# spearman_corr(factor_value(t), forward_return(t, t+horizon))——不是
# 分類錯誤，是資料源本身生不出這個算法要的輸入。

weight:
  factor_id: liquidation

  ####################
  # Prior Weight（ic 結構性算不出來，但比照 cpi 的做法，改用 Domain Knowledge 給有理由的 Prior Weight）
  ####################
  historical_predictability:
    ic: null  # 不適用：無歷史時間序列，rolling_spearman_ic 沒有輸入可用——
              # 待補：如果之後換一個有歷史查詢能力的資料源（例如付費的 Coinglass API），才有機會真的算出 ic
  prior_weight:
    basis: domain_knowledge          # 跟 cpi 一樣不套統計算法，但依據不同——cpi 是「事件重要性分級」，這裡是「訊號本質定位」
    value: 0.3                       # 示範值，刻意偏低
    reason: |
      liquidation 拿不到 Prior Weight 有兩個獨立理由，缺一不可：
      ① 文獻定位（見 [[Stage 3 — Knowledge Layer/liquidation]] references）：
      清算連鎖多半是 funding_rate＋open_interest 已經指出的擁擠倉位「兌現」
      的結果，本質是**確認性／落後訊號**，不是獨立領先訊號——即使資料完整，
      Prior Weight 也不該給高，因為它的資訊量大半已經包含在 funding_rate／
      open_interest 裡，重複計入等於雙重計分；
      ② 資料侷限（見 Stage 2/3）：現有資料源只能即時監聽單一窗口，樣本代表性
      本來就弱，即使真有訊號也難以用單次觀察窗確認。
      兩個理由都指向同一結論：低但非零的 Prior Weight，不是「沒有算出來所以
      給 0」，是「即使能算，本質上也不該高」。

  ####################
  # Dynamic Modifier（來自今日市場，快變動）
  ####################
  market_regime:
    classification:              # rate_cutting／rate_hiking／rate_hold（沿用 ATR 定義）
  time_horizon_match:            # 不適用：liquidation 沒有 primary_horizon 可比對（Stage 3 已標記「不適用」），這格同樣留空
  cross_source_consensus:        # 讀 Stage 3 Knowledge.confirms（funding_rate＋open_interest）今天是否同向——這格可以有實質內容，因為文獻共識不受我方資料源限制影響
  freshness:                     # 語意＝這次即時監聽窗口距現在多久（通常等於執行當下，因為沒有「查詢過去」這個選項）

  context_modifier:              # 由 LLM 根據上述線索解釋給出，range=[0.5, 2.0]，非公式計算
  final_weight:                  # = prior_weight（0.3，見上方）× context_modifier（LLM 給的數字）
```

### 為什麼 liquidation「沒有得算」，跟 cpi 是不同類的沒有

`ic: null` 這件事在 cpi／liquidation 兩份文件裡看起來一樣，但成因不同：cpi 是**分類問題**（該用 Event Factor 的 Impact Level，不是套錯算法），liquidation 是**資料源問題**（Binance 查歷史清算單的 REST API 已停用，`factor_value(t)` 這個算法輸入的歷史序列根本生不出來，換哪種統計方法都一樣算不出來）。但兩者的解法一致：不算 ic 不代表 Prior Weight 只能是 null，改用 Domain Knowledge 給一個有明確理由的值——liquidation 這裡給低分（0.3）的理由本身也是雙重的（確認性訊號＋資料侷限），不是隨便挑一個「看起來合理」的數字。

---
tags: [projects, hackathon, hoyabit, weight-engine, cpi]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine（示範：cpi）；Event Factor 不算 ic，Prior Weight 拍板改由 Stage 3 的 impact_level 分級推導（Ken 2026-08-02 定案）
---

```yaml
# Stage 4 — Dynamic Evidence Weight Engine（示範：cpi）
#
# ⚠️ 這份沒有 ic 數字可填，不是懶得算，是 13_流程圖迭代定案v2.md 現有的
# Stage 4 設計（historical_predictability.ic = rolling_spearman_ic）
# 本身建立在「factor 是連續數值，每天都有值」這個假設上——ATR／funding_rate／
# active_address 三個示範都符合，但 cpi 在 Stage 3 已經改分類成 Event
# Factor（一個月一次的離散事件，見 [[Stage 3 — Knowledge Layer/cpi]]），
# `factor_value(t)` 這個算法輸入對 cpi 不成立：沒有「每天的 cpi 值」可以
# 拿來跟每天的 forward_return 配對算 spearman 相關係數。
#
# 09_權重改版草案.md 的 Event Factor Interpreter 給的量化方式是 Impact Level
# （Domain Knowledge 分級），不是 IC/HitRate——Ken 拍板：Event Factor 本來
# 就不需要算 ic，Prior Weight 直接從 Stage 3 的 impact_level 分級推導出來，
# 不用另外設計一套算法，也不用等 ic 有沒有數字。

weight:
  factor_id: cpi

  ####################
  # Prior Weight（Event Factor 不算 ic，直接從 impact_level 推導，附理由）
  ####################
  historical_predictability:
    ic: null  # 不適用：cpi 是離散事件，非連續數值，rolling_spearman_ic 的輸入假設不成立——這是分類上的必然，不是缺口
  prior_weight:
    basis: impact_level            # 沿用 Stage 3 event_class 分級，不套統計算法
    impact_level: Very High        # 沿用 [[Stage 3 — Knowledge Layer/cpi]] 的 event_class 分級，跟 FOMC 同級
    value: 0.8                     # 示範映射：Very High→0.8／Medium→0.5／Low→0.2（人工分級對照表，非回測值）
    scale: relative_strength         # 2026-08-02 拍板：這格宣告「上面那個 value 是哪把尺上的數字」。
                                     # relative_strength ＝ 已經是 [0,1] 的**IC 等價強度**，直接拿去排序，
                                     # 不再換算、也不做樣本收縮（人工判斷沒有「樣本數」這個東西）。
                                     # ⚠️ 語意重新定義（數字沒改）：這個分數從此讀作「相當於 |ic| 多強」，
                                     # 不是一個抽象的重要性分點——這樣它才跟 ic 型的權重可比。
                                     # ⚠️ 已知不對稱：ic 型會因樣本不足被打折，這型不會。不補一個折減係數
                                     # 去「平衡」（那等於重新引入分組，跟排序拍板打架），改成把 basis
                                     # 帶到卡片上讓人看得到來源，並記進 13 待處理
    reason: |
      CPI 是排定時程的總經系統性事件，公布當下對全市場（不限特定幣種）都有
      直接的流動性／風險偏好衝擊——這件事本身有高度學術與產業共識（見 Stage 3
      references），有共識的是「CPI 公布會造成顯著市場反應」，沒有共識的是
      「反應方向」。Prior Weight 量的是前者（這個 factor 重不重要、值不值得
      關注），不是後者（漲跌方向），所以學界對方向意見分歧不影響這裡給高分——
      這正是 Prior Weight 跟「預測準不準」脫鉤、只回答「重要性」的設計本意。

  ####################
  # Dynamic Modifier（來自今日市場，快變動——事件也有「今天的情境」，LLM 判斷）
  ####################
  market_regime:
    classification:              # rate_cutting／rate_hiking／rate_hold（沿用 ATR 定義）——CPI 本身就是這條傳導鏈的上游輸入，這裡用法上要注意別讓同一件事互為因果
  time_horizon_match:            # 比對 Stage1 horizon 與 Stage3 reaction_window（公布當下~2-3日）／expected_duration（數週至數月）的雙尺度定義，比 Statistical Factor 單一 primary_horizon 複雜
  cross_source_consensus:        # 讀 Stage 3 Knowledge.usually_affects（FOMC／DXY／美債殖利率）今天是否同向
  freshness:                     # 對 Event Factor，freshness 語意改成「距上次公布多久」（見 Stage 2 cpi.yaml 的 hours_since_event），不是「資料多新鮮」

  context_modifier:              # 由 LLM 根據上述線索解釋給出，range=[0.5, 2.0]，非公式計算
  final_weight:                  # = prior_weight（0.8，見上方）× context_modifier（LLM 給的數字）
```

### Event Factor 的 Prior Weight 怎麼定案的

13 的 Stage 4 原本只示範過 Statistical Factor（ATR／funding_rate／active_address），套 `historical_predictability.ic` 這格對 Event Factor（cpi）不成立。這輪 Ken 拍板：**Event Factor 不需要 ic，Prior Weight 直接從 Stage 3 的 `impact_level` 分級推導**（Very High→0.8 示範映射），Modifier 段落照舊交給 LLM 判斷——不是另外設計一套全新機制，是把 09_權重改版草案.md 已經定義好的「Event Factor 用 Impact Level，不用 IC/HitRate」直接接進 Stage 4 的 Prior Weight 位置。

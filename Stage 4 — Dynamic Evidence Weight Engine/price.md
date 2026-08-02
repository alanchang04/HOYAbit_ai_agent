---
tags: [projects, hackathon, hoyabit, weight-engine, price]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine（示範：price）；ic 本質上不適用（快照沒有可回測的歷史序列），Prior Weight 改用 Domain Knowledge 給理由，2026-08-02
---

```yaml
# Stage 4 — Dynamic Evidence Weight Engine（示範：price）
#
# ⚠️ 這份「沒有 ic」的成因，跟 cpi／liquidation 都不一樣：
#   cpi         → 分類問題（該用 Event Factor 的 Impact Level，不是套錯算法）
#   liquidation → 資料源問題（歷史清算單 API 已停用，無歷史序列可用）
#   price       → 本質問題——「即時報價快照」定義上就只有一個值，不是一段可以
#                 拿來跟 forward_return 逐日配對算 spearman 相關係數的時間序列。
#                 就算硬是把「連續多天抓到的報價」串成序列，那其實就是在用
#                 「今天的價格變化」預測「今天之後的價格變化」，跟自變數/依變數
#                 高度重疊，算出來的 ic 沒有意義，不是「數字算不出來」而是
#                 「這樣算出來的數字沒有解讀空間」，所以刻意不做。

weight:
  factor_id: price

  ####################
  # Prior Weight（本質上不適用 ic，改用 Domain Knowledge 給有理由的 Prior Weight）
  ####################
  historical_predictability:
    ic: null  # 不適用：即時快照沒有「同一 factor 的獨立歷史序列」可跟 forward_return 配對，見上方說明
  prior_weight:
    basis: domain_knowledge
    value: 0.35                      # 示範值，刻意給中等偏低——見下方 reason 的兩個理由
    scale: relative_strength         # 跟 cpi／liquidation 同一把尺：[0,1] 的 IC 等價強度，直接拿去排序
    reason: |
      給 0.35（介於 liquidation 0.3 與 cpi 0.8 之間）有兩個獨立理由：
      ① 學術定位（見 [[Stage 3 — Knowledge Layer/price]] references）：文獻對「短期價格
      變動本身能不能預測後續報酬」沒有共識——高頻加密貨幣市場同時存在動量與反轉，方向
      隨流動性、大事件（如 FOMC）而變。這跟 cpi 不一樣：cpi 是「重要性有共識、方向沒
      共識」，這裡連「這是不是一個穩定訊號」本身都有爭議，效率市場的立場是短期價格
      變動接近隨機游走，不該給太高的分數；
      ② 它的主要價值不是當方向預測器，是當**事實錨點**——這是全部 factor 裡唯一「不管
      查詢的 Horizon 多長、任何時刻都能給出具體數字」的一個，補上其他 factor（衍生品／
      鏈上／總經，全部都是間接訊號）唯一缺的「現貨本身現在多少錢」這塊事實基礎。這個
      基礎功能有價值，但價值形式是「grounding」不是「predicting」，不該套用 predicting
      型的高分邏輯，所以给中等而非高分。

  ####################
  # Dynamic Modifier（來自今日市場，快變動）
  ####################
  market_regime:
    classification:              # rate_cutting／rate_hiking／rate_hold（沿用 ATR 定義）
  time_horizon_match:            # 比對 Stage 1 Horizon 跟 Stage 3 primary_horizon（即時快照，無固定觀察窗）——
                                  # 報價本身沒有「查詢窗口太短/太長」的問題（任何時刻都查得到），但拿它論證
                                  # 長 Horizon 的走勢時，一個時間點的效力會遞減，LLM 判斷時應反映這點
  cross_source_consensus:        # 讀 Stage 3 Knowledge.conflicts（active_address）／confirms（volume_change_24h）
                                  # 今天是否同向——這格可以有實質內容，因為 active_address 是本專案真的有卡片的 factor
  freshness:                     # 語意＝這次抓取距現在多久——即時報價幾乎恆等於 0（抓了就是最新），跟 cpi
                                  # 「距上次公布多久」的語意相反，這格幾乎不會是扣分項

  context_modifier:              # 由 LLM 根據上述線索解釋給出，range=[0.5, 2.0]，非公式計算
  final_weight:                  # = prior_weight（0.35，見上方）× context_modifier（LLM 給的數字）
```

### 為什麼「沒有 ic」這裡是第三種成因

`ic: null` 在 cpi／liquidation／price 三份文件裡看起來一樣，但成因三種都不同：cpi 是**分類問題**（該用 Event Factor 的 Impact Level）、liquidation 是**資料源問題**（歷史 API 已停用）、price 是**本質問題**（快照定義上就沒有可回測的獨立歷史序列——硬做等於拿自己預測自己）。三者的解法一致：不算 ic 不代表 Prior Weight 只能是 null，改用 Domain Knowledge 給一個有明確理由的值。price 給 0.35，理由跟 liquidation 一樣是雙重的，但內容不同：liquidation 的兩個理由都是「扣分」（確認性訊號＋資料侷限），price 的兩個理由一個扣分（學術上訊號本身有爭議）、一個是重新定位價值形式（不是預測器，是事實錨點）——中等分數反映的是「功能不同，不是強度不夠」。

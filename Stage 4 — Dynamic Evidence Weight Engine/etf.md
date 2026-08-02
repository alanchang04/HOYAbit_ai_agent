---
tags: [projects, hackathon, hoyabit, weight-engine, etf]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine（示範：etf）；ic 為真實計算值，樣本數是這輪目前最小的一份，confidence 判定比 panews_sentiment 更低
---

```yaml
# Stage 4 — Dynamic Evidence Weight Engine（示範：etf）
#
# ⚠️ 樣本數是這輪四份「真的算過 ic」的示範裡最小的：
#   - active_address：1807 天（5 年真實歷史）
#   - panews_sentiment：44 天
#   - etf：**8 天**（bitbo.io 免費頁面只給 9 個交易日，horizon=1 天損失 1 筆）
#   8 個樣本點算出來的相關係數統計上幾乎沒有意義，比 panews_sentiment 的
#   confidence=low 還要更不可信——這裡如實延續同一套 confidence 標記機制，
#   不因為 Stage 3 的文獻證據很強（$100M→53bp）就放鬆這裡的標準。文獻證據強
#   是「別人的大樣本研究」，不代表「我們這裡用 8 筆免費資料算出來的數字」也一樣強。

weight:
  factor_id: etf

  ####################
  # Prior Weight（來自 Knowledge，慢變動——樣本數是這輪最小，信賴度也最低）
  ####################
  historical_predictability:
    ic:
      algorithm: rolling_spearman_ic
      formula: |
        IC(horizon) = spearman_corr(
          factor_value(t),           # = 當天 ETF Totals 淨流量（Stage 2 抓的原始值，非正規化）
          forward_return(t, t + horizon)
        )  for t in [now - horizon, now]
      input: horizon                # 正式運作時由 LLM 依 Stage 1 Horizon 動態給值，同 active_address／panews_sentiment 的設計
      example_run:
        horizon: 1                  # 樣本天數太少，只能用最短 horizon（1 天），換取還能有幾組可比對點數
        sample_size: 8              # ⚠️ 這輪四份 ic 示範裡最小，遠低於 active_address 的 1807、也低於 panews_sentiment 的 44
        computed_value: 0.0714
        # 解讀：0.0714 數值上比 active_address 的 0.0041 更接近「有點訊號」的
        # 門檻，但 8 個樣本的抽樣誤差遠超過這個數字本身——這裡完全不能拿來
        # 跟 Stage 3 引用的學術文獻（$100M→53bp、解釋 21% 日報酬變異）互相佐證，
        # 那是別人用完整歷史資料做的正式回測，這裡只是免費資料源天花板下
        # 湊出來的示範值，兩者不是同一個層級的證據
  prior_weight:
    basis: rolling_spearman_ic       # Statistical Factor 沿用同一套填法（ic 原值，不套正規化——同 active_address／panews_sentiment，正規化公式仍是全域待拍板提案，非本文件決定）
    value: 0.0714                    # ＝ ic 原值
    confidence: very_low             # ⚠️ 這輪新增的第二個信賴度層級——比 panews_sentiment 的 low 更低，因為樣本數只有一半（8 vs 44）
    reason: |
      ic 算出來是 0.0714，但樣本數只有 8 天，是這輪目前算過 ic 的四個
      factor 裡最小的，統計上幾乎不能算「算出來的訊號」，更接近「湊出來的
      數字」。confidence 標成 very_low（不是 low）是為了跟 panews_sentiment
      的情況區分開——44 天雖然也不夠，但至少是「量少但方法論在跑」，8 天已經
      逼近「這個數字本身不該被引用」的門檻。建議：這個 factor 要嘛之後換一個
      有更長免費歷史的資料源重跑，要嘛在 Evidence Card／報告措辭上明確標注
      「樣本量不足以下結論，僅供參考 Stage 3 文獻佐證的方向」。

  ####################
  # Dynamic Modifier（來自今日市場，快變動——餵給 LLM 當線索，不套公式）
  ####################
  market_regime:
    classification:              # rate_cutting／rate_hiking／rate_hold（沿用 ATR 定義）
  time_horizon_match:            # 比對 Stage1 horizon 與 Stage3 primary_horizon（短期，當日至10個交易日）的接近程度
  cross_source_consensus:        # 讀 Stage 3 Knowledge.confirms(price)／conflicts(active_address) 清單，今天方向是否同向——⚠️ conflicts 指向 active_address 但那份自己的 conflicts 沒有指回來，是單向關係，見 Stage 3 說明
  freshness:                     # bitbo.io 為每交易日更新，freshness 判斷門檻可比照 active_address（日頻）

  context_modifier:              # 由 LLM 根據上述線索解釋給出，range=[0.5, 2.0]，非公式計算
  final_weight:                  # = prior_weight（0.0714，confidence=very_low）× context_modifier
                                  # ⚠️ 這個 factor 的 final_weight 現階段最不該被拿來跟其他 factor 直接比大小——
                                  # 不是因為算法錯，是因為輸入樣本量結構性太小，這是資料源天花板問題，
                                  # 不是這份文件或算法能單獨解決的
```

### 這份把「confidence 分級」這件事又往前推了一步

panews_sentiment 那份第一次發現 Evidence Weight 需要一個 confidence 標記（見該文件），但只有 `low` 一個等級。這份實測樣本數只有 8（比 panews_sentiment 的 44 還少一半以上），如果還是標 `low`，會讓人以為它跟 panews_sentiment 同等可信——但兩者的可信度差距其實跟 active_address vs panews_sentiment 的差距一樣大，甚至更大。這裡先示範性加了 `very_low` 這個分級，但**這不是這份文件能拍板的事**——confidence 到底該分幾級、每級的樣本數門檻怎麼定，需要回報給 [[13流程圖迭代定案v2]] 統一設計，不能讓每個 factor 自己發明自己的分級標準。

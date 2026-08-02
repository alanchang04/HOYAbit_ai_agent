---
tags: [projects, hackathon, hoyabit, weight-engine, bnb-burn]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine（bnb_burn）；2026-08-02 新增
summary: BNB bnb_burn 的 Prior Weight——走 impact_level（同 cpi），Medium→0.5；理由是「事前可預期」不是「不重要」
---

```yaml
# Stage 4 — Dynamic Evidence Weight Engine（bnb_burn）
#
# Event Factor 路徑，跟 cpi 同一條：不算 ic，用 Stage 3 的 impact_level 分級推導。

weight:
  factor_id: bnb_burn

  historical_predictability:
    ic: null
    ic_null_reason: |
      Event Factor 不算 ic（13 拍板：ic 那套算法建立在「factor 是連續數值、
      每天都有值」的假設上，只適用 Statistical Factor）。
      ⚠️ 這個 factor 還多一層：季頻，一年 4 個點，就算完整 36 期歷史都拿得到
      也只有 36 筆跨 9 年，本質上不可能做逐日 forward_return 對齊。
      所以這不是「資料源限制導致暫時算不了」，是這件事本身就不適用 ic。

  prior_weight:
    basis: impact_level             # 沿用 Stage 3 event_class 分級，不套統計算法（同 cpi）
    value: 0.5                      # 示範映射：Very High→0.8／Medium→0.5／Low→0.2
                                    # （13 定的人工分級對照表，非回測值）
    scale: relative_strength        # 數字不換算，語意讀作「IC 等價強度」；不做樣本收縮
    weight_direction: 不適用        # [0,1] 恆正
    confidence: 不適用              # confidence 這個欄位是為「算得出數字但樣本不足」設計的
                                    # （panews low／etf very_low），人工分級沒有樣本這回事
    reason: |
      給 Medium(0.5) 而不是 cpi 的 Very High(0.8)，**不是因為銷毀不重要，
      是因為它事前可預期**（見 Stage 3 predictability_caveat）：

      - cpi：數字公布前沒人知道 → 意外本身是衝擊來源 → 0.8
      - bnb_burn：機制透明、時程固定、金額可事先估算 → 效率市場下應已 price in
        → 真正的訊號只剩「實際 vs 預期」的差額，而本專案**沒有市場預期的資料源**
        → 算不出差額 → 0.5

      這個值反映的是「它是一件確實發生、可量化、對供給有直接影響的事」，
      同時扣掉「但市場早就知道了」那一塊。

      ⚠️ 要標示的不對稱（13 已知、無解）：這個 0.5 是人工給的，不做樣本收縮，
      所以它會穩定排在 BNB 那張 funding_rate 卡（現場算 ic，實測 BTC 是 0.55 級距
      但 BNB 沒跑過）跟其他 relative_strength 卡之上。一個「拍腦袋的 0.5」贏過
      「測了 1800 天的 0.19」（見 hash_rate），13 已記錄這條無解，這裡只是又一個實例。

  ####################
  # Dynamic Modifier
  ####################
  market_regime:
    classification:
  time_horizon_match:            # 比對 Stage1 horizon 與 applicable_days=[0, 90]
                                 # ⚠️ 提醒：那是 reaction_window[0,3] 與
                                 # expected_duration[0,90] 兩段**不連續**尺度的聯集，
                                 # match=1.00 不代表該 horizon 上強度相同（同 cpi 的問題）
  cross_source_consensus:        # ⚠️ 完全用不上——Event Knowledge 沒有 confirms／conflicts／
                                 # independent 三格（13 缺口 2），沒有比對對象
  freshness:                     # ✅ 這條對它特別關鍵且特別好判斷：季頻事件，
                                 # 距離上次銷毀超過 ~100 天就代表下一期快到了／資料過期，
                                 # 判斷門檻跟日頻 factor 完全不同尺度

  context_modifier:              # 由 LLM 給，range=[0.5, 2.0]
  final_weight:                  # = 0.5 × context_modifier
```

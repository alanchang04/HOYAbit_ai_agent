---
tags: [projects, hackathon, hoyabit, weight-engine, snapshot, orderbook]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine（示範：orderbook_depth）；Snapshot Factor 不算 ic（沒有歷史序列，且本質上是狀態量不是預測量），Prior Weight 走 Domain Knowledge。⚠️ 給的 0.35 是**待 Ken 校準的示範值**，理由寫在下面但沒有文獻或回測支撐
---

```yaml
# Stage 4 — Dynamic Evidence Weight Engine（示範：orderbook_depth）
#
# ⚠️ 這是第三種「沒有 ic」，跟前兩種都不同，三者不要混為一談：
#   cpi          → **分類問題**：Event Factor 本來就不該套 ic（離散事件沒有每天的值）
#   liquidation  → **資料源問題**：現象有歷史，但查歷史的 REST 已停用（再加上本環境
#                   連合約 WebSocket 都收不到 frame，見該份 2026-08-02 註記）
#   orderbook_depth → **本質問題**：盤口深度是「當下狀態」，不是可跨時間配對的序列。
#                   Binance 沒有歷史盤口端點不是缺陷，是「歷史盤口」本來就要自己錄。
#                   即使真的自己錄了幾個月、算得出 ic，那時它也已經變成另一型 factor
#                   （Statistical）了，不是這一型。

weight:
  factor_id: orderbook_depth

  ####################
  # Prior Weight（Domain Knowledge——沒有 ic 可算，也不是「算不出來」，是不適用）
  ####################
  historical_predictability:
    ic: null  # 不適用：無歷史盤口序列，且 factor_value(t) 對「狀態量」的語意本來就不成立

  prior_weight:
    basis: domain_knowledge
    value: 0.35
    scale: relative_strength         # 值已經是 [0,1] 的 IC 等價強度，不再換算、不做樣本收縮
                                     # （人工判斷沒有樣本數的概念，見 13 的換算拍板）
    reason: |
      ⚠️ 這個 0.35 是**示範值，待 Ken 校準**——它不是回測出來的，也還沒有文獻支撐
      （Stage 3 那份的 references 目前是空的，這是已知缺口，不是漏寫）。
      給這個數字的三條理由，一併寫出來讓人有東西可以反駁：
      ① 給得比 liquidation（0.3）高一點：至少每次執行都拿得到真實、完整的觀測值，
         而 liquidation 在本環境是結構性的 0（收不到任何 frame）。「測得到」本身
         就比「測不到」值錢。
      ② 但不該高太多：市場微結構的常識是盤口失衡對**分鐘級以內**的價格變動有解釋力，
         尺度一拉到日／週就衰減得很快。而 Stage 1 判出來的 Horizon 通常是天以上，
         這個 factor 在多數查詢裡是「背景狀態」不是「方向訊號」。
      ③ 掛單可撤：深度數字是「宣稱的流動性」不是「保證吃得到的流動性」（spoofing／
         冰山單），這層折扣在給值時就該算進去，不是等下游自己判斷。
      校準方向：如果之後補上文獻、或自建了幾個月的盤口序列真的算出 ic，這格就該
      改成 basis: rolling_spearman_ic 並移除這段理由——那時它就不是 Snapshot 型了。

  ####################
  # Dynamic Modifier（來自今日市場，快變動——餵給 LLM 當線索，不套公式）
  ####################
  market_regime:
    classification:              # rate_cutting／rate_hiking／rate_hold（沿用既有定義）
  time_horizon_match:            # ⚠️ 這格對 Snapshot 型要特別小心：Stage 3 沒有 primary_horizon
                                 # （那個概念對它不成立），能比的是 validity_window（秒級）。
                                 # 拿「秒級」去比對查詢的「2 週」，差距永遠是最大值，
                                 # 會讓 modifier 被機械式壓到下限——這不是判斷，是單位錯置。
                                 # 正確的讀法是「這張快照多快過期」，不是「這個訊號適用多長」
  cross_source_consensus:        # 讀 Stage 3 Knowledge.confirms（funding_rate＋open_interest）今天是否同向
  freshness:                     # 這型 factor 的 freshness 恆等於「剛剛」——快照就是這次打 API 拿的。
                                 # 反過來說它也**最容易過期**，兩件事要分清楚

  context_modifier:              # 由 LLM 根據上述線索解釋給出，range=[0.5, 2.0]，非公式計算
  final_weight:                  # = prior_strength（0.35，Domain Knowledge 直接就是 [0,1] 強度）× context_modifier
```

### 這份要提醒的兩件事

**一、`time_horizon_match` 這條線索在 Snapshot 型上是壞的。** 其他 factor 比的是「查詢 Horizon vs 這個 factor 擅長的時間尺度」，兩邊都是「訊號適用多長」。Snapshot 型只有「這個數字多快過期」（秒級），拿去跟「2 週」比，落差永遠是最大值，LLM 會機械式地把 modifier 壓到下限 0.5——但那個判斷沒有意義：不是「這個 factor 不適合 2 週的查詢」，是「快照的有效期」跟「訊號的適用尺度」根本是兩個問題。這是新開第四型之後暴露出來的 Stage 4 缺口，先記錄，這輪沒動 modifier 的 prompt。

**二、Prior Weight 的 0.35 目前是全專案最沒有支撐的一個數字。** cpi 的 0.8 來自 09 已有的 impact_level 分級表、liquidation 的 0.3 有文獻定位（確認性訊號）加資料侷限兩條理由、其他幾個是真的算出來的 ic。這個 0.35 只有「合理推論」，Stage 3 的 references 還是空的。**不要在 pitch 或報告裡把它跟其他數字並列當成同等基礎的東西**——它現在的角色是「先有個能跑的位置」，不是結論。

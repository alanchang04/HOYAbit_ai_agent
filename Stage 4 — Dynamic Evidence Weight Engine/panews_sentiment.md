---
tags: [projects, hackathon, hoyabit, weight-engine, sentiment, panews]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine（示範：panews_sentiment）；ic 為真實計算值但樣本數過小，不可當定論，理由見下方
---

```yaml
# Stage 4 — Dynamic Evidence Weight Engine（示範：panews_sentiment）
#
# ⚠️ 這份的 ic 是真的算出來的，但**信賴度明顯低於** active_address 那份，
# 要老實標注，不能讓兩個都叫 ic 的數字看起來一樣可信：
#   - active_address：1807 天樣本，5 年歷史，統計檢定力足夠
#   - panews_sentiment：只有 44 天可比對樣本（Stage 2 只抓了 47 天），
#     這種樣本數算出來的 ic 本質上接近雜訊，正負號、大小都可能只是抽樣運氣，
#     不是「這個 factor 真的有 0.051 的預測力」這種可以下定論的陳述

weight:
  factor_id: panews_sentiment

  ####################
  # Prior Weight（來自 Knowledge，慢變動——但這次樣本數不足，見上方警告）
  ####################
  historical_predictability:
    ic:
      algorithm: rolling_spearman_ic
      formula: |
        IC(horizon) = spearman_corr(
          factor_value(t),           # = 當天 sentiment_score（Stage 2 簡化版關鍵字計分）
          forward_return(t, t + horizon)
        )  for t in [now - horizon, now]
      input: horizon                # 正式運作時由 LLM 依 Stage 1 Horizon 動態給值，同 active_address 的設計
      example_run:
        horizon: 3                  # 樣本天數少，用短 horizon 換取多一點可比對點數，這是示範的權宜選擇，非算法固定值
        sample_size: 44             # ⚠️ 遠低於 active_address 的 1807，統計檢定力嚴重不足
        computed_value: 0.051
        # 解讀：0.051 本身數值上比 active_address 的 0.0041 更接近「有點訊號」
        # 的門檻（見 Stage 3 references 提到的一般標準：IC>0.05 略有參考價值），
        # 但**不能因此就說這個 factor 比 active_address 更有預測力**——44 個
        # 樣本的抽樣誤差遠大於這個差距本身，這個數字現階段只能證明「算法跑得
        # 通」，不能證明「訊號真實存在」，要拉長歷史（09 文件說可以回溯到
        # 2023-01-14）重跑才有資格下結論
  prior_weight:
    basis: rolling_spearman_ic       # ⚠️ 2026-08-02 拉齊（原本寫 `ic_normalized`）：原註解說「沿用跟
                                     # cpi/liquidation 一致的正規化公式」，這句跟事實不符——cpi 的 0.8 來自
                                     # impact_level 人工分級、liquidation 的 0.3 來自 Domain Knowledge，
                                     # 兩份都沒有套任何正規化公式；13 也還把 `normalization` 留在註解／
                                     # 待 Ken 校準狀態，沒有這條「既有公式」可以沿用。
                                     # 實作以 demo 的 `_resolve_prior_weight()` 為準：Statistical Factor
                                     # 的 Prior Weight **就是 ic 原值**（程式註解原話），這份跟著同一套填法，
                                     # 才不會出現「一個 factor 用 ic 原值、一個用轉換後的分數」混在同一個排序鍵裡
    value: 0.051                     # ＝ ic 原值（見上方 example_run.computed_value），跟 active_address 那份同一套填法
    confidence: low                  # ⚠️ 這個欄位是這次新加的——樣本數不足時，即使算出一個數字，也要標注信賴度，不能讓下游把它當成跟 active_address／cpi 同等可信的數字直接拿去排序
    reason: |
      ic 算出來是 0.051，但樣本數只有 44 天，遠低於統計上可信的門檻。
      在樣本數補齊之前，這個 prior_weight 不該被當成穩定結論使用——
      建議下游（Stage 5 排序／Stage 8 辯論）看到 confidence=low 的
      Evidence Weight 時，要嘛額外標注「樣本不足，僅供參考」，要嘛暫時
      不讓它跟其他 confidence 正常的 factor 直接比大小排序。
      ⚠️ 注意這條建議跟 2026-08-02 Ken 的排序拍板（**一律照 evidence_weight 排序**，
      不因來源不同而分組）方向相反——`confidence` 要不要真的影響排序，是待拍板的
      新問題（見文末），在拍板前排序仍照權重單鍵走，不因 confidence=low 另眼相看。

  # 正規化提案（原 `ic_normalized` 的構想保留在這裡，但明確標成「尚未拍板、demo 不會套用」）
  proposed_normalization:
    formula: "clip(0.5 + ic / (2 × ic_ref), 0, 1)，ic_ref=0.1"
    value_if_applied: 0.755          # 0.5 + 0.051/0.2
    status: 提案；13 的 `normalization` 仍是註解狀態，demo 不套用，勿當定案引用
    why: |
      ic 的值域是 [-1, 1]（相關係數），cpi 的 0.8／liquidation 的 0.3 是 [0, 1] 的
      重要性分數——13 拍板讓三種來源共用同一個 evidence_weight 概念時，就已經接受了
      這個尺度不一致（Ken 2026-08-02 再次拍板：一律照權重排序，不另設規則）。
      這條公式是想從根本解掉它，但**要全部 factor 一起套才有意義**：active_address
      的 ic=0.0041 套下去會變成 0.5205，不再是現在文件裡寫的「趨近 0、結構性排後段」，
      Stage 4／Stage 5 兩層的多份文件結論都要跟著改寫。屬於全域設計決定，
      不是單一 factor 的文件能自己決定的，待 Ken 拍板。

  ####################
  # Dynamic Modifier（來自今日市場，快變動——餵給 LLM 當線索，不套公式）
  ####################
  market_regime:
    classification:              # rate_cutting／rate_hiking／rate_hold（沿用 ATR 定義）
  time_horizon_match:            # 比對 Stage1 horizon 與 Stage3 primary_horizon（短期但 regime-dependent）的接近程度
  cross_source_consensus:        # 讀 Stage 3 Knowledge.confirms(news) 清單，今天方向是否同向
  freshness:                     # PANews 更新頻率快（近乎即時），freshness 判斷門檻應該比月頻的 cpi、甚至日頻的 active_address 都嚴格

  context_modifier:              # 由 LLM 根據上述線索解釋給出，range=[0.5, 2.0]，非公式計算
  final_weight:                  # = prior_weight（0.051 ic 原值，confidence=low）× context_modifier
                                  # ⚠️ 跟 active_address 同一個狀況：prior 很小時 context_modifier 拉不動，
                                  # 這張卡在純權重排序下會落在後段——這是 ic 原值填法的必然結果，
                                  # 若之後拍板採用 proposed_normalization，這句要跟著改寫
```

### 這份新增的 `confidence` 欄位，是這輪才發現需要的

前三個示範（active_address／cpi／liquidation）的 Prior Weight 要嘛有足夠樣本支撐（active_address 1807 天），要嘛乾脆是 Domain Knowledge 判斷（cpi／liquidation，不依賴樣本數）。panews_sentiment 是第一個「有算出數字，但樣本數明顯不夠」的案例——`ic=0.051` 看起來比 active_address 的 `ic=0.0041` 更像有訊號，但這個印象本身就是誤導，因為 44 個樣本的雜訊遠大於這個差距。這代表 Prior Weight 的欄位設計除了「數值」跟「理由」，可能還需要一個「這個數值有多可信」的標記——這是這輪新發現、值得回報給 [[13流程圖迭代定案v2]] 的一個結構性缺口，不是這份文件自己能決定的事。

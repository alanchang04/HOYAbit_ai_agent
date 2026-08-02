---
tags: [projects, hackathon, hoyabit, evidence-card, etf]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（示範：etf）；組裝 Stage 2 Fact／Stage 3 Knowledge／Stage 4 Weight 三層真實輸出，非編造
---

```yaml
# Stage 5 — Evidence Card（示範：etf）
# 組裝 Stage 2 Fact／Stage 3 Knowledge／Stage 4 Weight 三層輸出成統一卡片，
# 命名規則沿用這批卡片的暫行格式 {FACTOR}_{COIN}（跟 demo 的
# `_evidence_id()` 一致，13 正文的命名規則本身仍待拍板）。

evidence:
  evidence_id: ETF_BTC
  category: statistical              # 沿用 Stage 3 Knowledge 的類型分類

  fact:                              # = Stage 2 Feature Extraction 的原始事實（示範 run：2026-07-17~2026-07-30，bitbo.io）
    current_value: 333.0             # 百萬美元，最新一個交易日（2026-07-30）
    previous_value: -88.6
    delta: 421.6
    sample_size: 9                   # ⚠️ 資料源天花板，見 Stage 2 說明

  features:                          # 完整版見 Stage 2 — Feature Extraction/etf.yaml
  knowledge:                         # 完整版見 Stage 3 — Knowledge Layer/etf
  evidence_weight: 0.0714            # = Stage 4 的 prior_weight（ic 原值，confidence=very_low，尚未乘 context_modifier）

  source_reliability:                # Stage 4 目前也還沒定（先註解掉），這裡跟著留白，不重複造一套新標準
  historical_support:                # 同上，待來源可信度分級表定案後一起補
  primary_horizon:                   # = Stage 3 Knowledge.primary_horizon（短期，當日至10個交易日，雙向回饋迴圈使其不是單純的領先訊號）
  persistence:                       # = Stage 3 Knowledge.persistence（中，但依附於價格回饋迴圈，非獨立延續性）

  related_evidence:                  # = Stage 3 Knowledge 的 confirms／conflicts／independent
    confirms: [price]
    conflicts: [active_address]      # ⚠️ 單向關係：active_address 卡片自己的 conflicts 指向 price，不是指回 etf，Stage 6 Graph 不會畫出雙向邊，見 Stage 3 etf.md 說明
    independent: [liquidation]

  traceability: bitbo.io ETF flow 頁面（HTML table 解析，非 JSON API，見 Stage 2 已知限制）

  # ⚠️ Confidence 標記（沿用 panews_sentiment 那份新增的機制，這裡再往下加一級）：
  confidence: very_low   # 樣本數只有 8-9 天，是這輪目前最低的信賴度——這張卡的
                          # evidence_weight 數字本身不該被當成跟 active_address／
                          # funding_rate 同等可信直接排序比較，但排序邏輯目前
                          # （13 拍板：一律照 evidence_weight）仍不因 confidence
                          # 分組，這張卡在純權重排序下的實際名次因此可能失真

prioritization:
  ranking_key: evidence_weight      # 13 拍板：純照 evidence_weight，跟其他五張一致
  ranking_transform: abs            # 2026-08-02 Ken 補充拍板：排序鍵不變（evidence_weight），
                                    # 但比大小時取絕對值。這張卡的 ic=0.0714 是正值，取絕對值
                                    # 對它沒有影響（跟 funding_rate 的 ic=-0.55 那種情況不同），
                                    # 但六張卡的排序轉換方式要一致，不能只有這張不宣告——
                                    # 缺這格會被 `python -m webapp.stage_specs` 自我檢查抓出來
                                    # （2026-08-02 實測踩過，這裡補上不是預防性寫的）
  evidence_coverage: null           # 定義未拍板，不生成
  weight_direction: 同向訊號         # ic 為正值：factor 越高、後續報酬方向越同向。跟 funding_rate
                                    # 的「反向訊號」相對，這格才有意義——單看 evidence_weight 的正負號
                                    # 也看得出來，這裡明寫一次方便直接讀，不用自己判斷正負號
```

### Stage 5 這輪確認：`confidence` 分級需要統一設計，不只是 panews_sentiment 的個案

這是這輪第二張需要 `confidence` 標記的卡片，而且比 panews_sentiment 更極端（8-9 天 vs 44 天）。兩張卡都用同一個「一律照 evidence_weight 排序」規則，意味著現在 Stage 5 排序結果裡，可能有兩張樣本數嚴重不足的卡片（etf／panews_sentiment）夾在 active_address（1807 天樣本）之類的卡片中間，純看 `evidence_weight` 數字大小完全看不出這個差異。**這不是個別 factor 文件能解決的**，需要回報給 [[13流程圖迭代定案v2]]：`confidence` 到底要不要真的影響排序（例如同層先比 confidence 再比 weight，或是低 confidence 一律標注但不改變排序名次，只在呈現時加警示），這是待拍板的問題，這兩張卡先如實記錄現況。

---
tags: [projects, hackathon, hoyabit, evidence-card, bnb-burn]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（bnb_burn）；2026-08-02 新增
summary: BNB bnb_burn 的 Evidence Card——第二張 Event 型卡片；⚠️ 它讓 BNB 成為唯一有兩個孤立節點的幣
---

```yaml
# Stage 5 — Evidence Card ＋ Prioritization（bnb_burn）
#
#   fact       ← Stage 2 — Feature Extraction/bnb_burn.yaml
#   knowledge  ← Stage 3 — Knowledge Layer/bnb_burn.md
#   weight     ← Stage 4 — Dynamic Evidence Weight Engine/bnb_burn.md（impact_level 0.5）

evidence:
  evidence_id: BNB_BURN_BNB         # ⚠️ {FACTOR}_{COIN} 暫行規則機械套用的結果，
                                    # 讀起來重複但**不特例處理**——13 拍板暫行規則統一，
                                    # 為單一 factor 破例會讓規則失去意義。
                                    # 正式命名規則定案時一併處理
  category: event                   # ← Stage 3 knowledge.category（第二張 Event 卡，第一張是 cpi）

  ####################
  # fact ← Stage 2（Event 型：事件本身＋事件的數值，不是 percentile/z_score 那組）
  ####################
  fact:
    burn_index:                     # 期數（實測最新 35）
    burned_amount_bnb:              # 實測 35th = 1,569,307.34 BNB
    remaining_supply_bnb:           # 實測 35th = 134,786,916.53 BNB
    burn_date:                      # 實測 35th = 2026-04-15 11:55 UTC
    delta_vs_previous:              # 實測 = +197,503.57 BNB（vs 34th 的 1,371,803.77）
    # ⚠️ percentile 整格不生成——只有兩期資料，算百分位沒有意義
    # （比照 13 拍板「卡片 schema 有、但這次填不出來的格子整格不產生不留 null」）

  features:                         # 完整欄位見 Stage 2 bnb_burn.yaml
  knowledge:                        # 完整內容見 Stage 3 bnb_burn.md

  ####################
  # evidence_weight ← Stage 4
  ####################
  evidence_weight:                  # = 0.5 × context_modifier
                                    #   basis = impact_level（Medium→0.5）
                                    #   ⚠️ 給 0.5 不是 0.8 的理由是「事前可預期」，
                                    #   不是「不重要」——見 Stage 4 reason

  source_reliability: null
  historical_support: null
  primary_horizon:                  # ⚠️ 整格不生成——Event 型沒有這個欄位（同 cpi）
  persistence:                      # ⚠️ 同上，整格不生成
  applicable_days: [0, 90]          # ← Stage 3 頂層那格（取代上面兩格；兩段不連續尺度的聯集）

  ####################
  # related_evidence ← Stage 3
  ####################
  related_evidence:
    confirms: null                  # ⚠️ Event Knowledge 沒有這三格（13 缺口 2），誠實留 null
    conflicts: null
    independent: null

  traceability: BNB Chain Blog 文章內文 HTML 解析（免key；2026-08-02 實測只回溯得到 35th／34th 兩期，30th/25th 是空殼頁）

prioritization:
  ranking_key: evidence_weight
  ranking_transform: abs
  evidence_coverage: null
  expected_rank: 第二              # prior_weight 0.5 在 BNB 的 7 張卡裡僅次於 cpi(0.8)，
                                   # 高於 price／orderbook_depth(0.35)。
                                   # funding_rate 現場算不可預測
```

## ⚠️ 這張卡讓 BNB 成為唯一有兩個孤立節點的幣

它跟 cpi 一樣是 Event 型 → Event Knowledge 沒有 `confirms`／`conflicts`／`independent`
三格 → **在 Evidence Graph 上不會發出任何邊**。而且跟 cpi 不同的是，cpi 至少有三張卡
（price／momentum／orderbook_depth）的 `independent` 指向它，所以 cpi 不孤立；
**沒有任何一張卡指向 bnb_burn**，它是真的孤立。

加上 `panews_sentiment` 本來就孤立，BNB 的圖上有兩個孤立節點——七張卡裡有兩張
完全不受 Stage 8 `DEBATE_GRAPH_RULE` 保護。這是 13 缺口 2（Event Factor 沒有對稱
關係欄位）第二次咬人，第一次是 cpi。**兩次都出現代表這不是個案，是 schema 缺陷**，
建議提高該缺口的優先序。

---
tags: [projects, hackathon, hoyabit, evidence-card, gas]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（gas）；2026-08-02 新增
summary: ETH gas 的 Evidence Card——ETH 唯一一張「這條鏈自己發生的事」的證據卡；percentile 有結構性陷阱要在卡片上標
---

```yaml
# Stage 5 — Evidence Card ＋ Prioritization（gas）
#
#   fact       ← Stage 2 — Feature Extraction/gas.yaml
#   knowledge  ← Stage 3 — Knowledge Layer/gas.md
#   weight     ← Stage 4 — Dynamic Evidence Weight Engine/gas.md（實測 ic 寫在檔案裡）

evidence:
  evidence_id: GAS_ETH
  category: statistical

  ####################
  # fact ← Stage 2
  ####################
  fact:
    current_value:                  # 當日平均 gas price（Gwei；原始 Wei 已在 Stage 2 換算）
    percentile:                     # ⚠️⚠️ 這格是這張卡最容易誤導人的一格——
                                    # 母體若取全段（4021 天），現值幾乎必然落在極低百分位，
                                    # 但那反映的是 EIP-1559 + L2 分流造成的**結構性改變**，
                                    # 不是「現在鏈上很冷」。卡片顯示這格時**必須**同時顯示 window，
                                    # 且 window 跨越 2021 年時要加註「跨結構性斷點，percentile 不可直接解讀」
    trend:                          # 由整段窗口前半／後半均值比較判讀出來的方向敘述

  features:                         # 完整欄位見 Stage 2 gas.yaml
  knowledge:                        # 完整內容見 Stage 3 gas.md

  ####################
  # evidence_weight ← Stage 4
  ####################
  evidence_weight:                  # = prior_strength × context_modifier
                                    #   prior_weight.raw_value = 0.0187（horizon=14 實測 ic）
                                    #   prior_strength = 0.1529
    # 其他 horizon：7 天 0.2493／30 天 0.2858。⚠️ 非單調（見 Stage 4），
    # 不要把 14 天那個凹陷解讀成「這個尺度沒用」

  source_reliability: null
  historical_support: null
  primary_horizon:                  # ← Stage 3＝短中期，applicable_days [1, 60]
  persistence:                      # ← Stage 3＝中低（尖峰數小時到數日；背景水位可持續數週）

  ####################
  # related_evidence ← Stage 3
  ####################
  related_evidence:
    confirms: price                 # ✅ 連得上
    conflicts: null                 # Stage 3 誠實列空
    independent: cpi                # ✅ 連得上

  traceability: etherscan.io/chart/gasprice CSV 匯出（免key，日頻；2026-08-02 實測 4021 筆，2015-07-30~2026-08-01）

prioritization:
  ranking_key: evidence_weight
  ranking_transform: abs
  evidence_coverage: null
  expected_rank: 中段               # prior_strength 0.1529（horizon=14），
                                    # 在 ETH 的 7 張卡裡會排在 cpi(0.8)／orderbook_depth(0.35)／
                                    # price(0.35) 之後、funding_rate 之前後不定
```

## 這張卡對 ETH 的意義

ETH 的另外 6 張卡沒有一張是**這條鏈自己的**證據——funding_rate／price／momentum／
orderbook_depth 全是交易所資料（五幣通用），cpi 是總經，panews 是輿情。gas 補回來的
是「Ethereum 網路本身現在忙不忙」，這在寫報告時是完全不同性質的一句話。

⚠️ 但要誠實標示：`ic=0.0187` 代表它**對報酬的預測力很弱**。它的價值在敘事完整度
（讓報告講得出鏈上狀態），不在排序名次。這兩件事在這個系統裡是分開的——
排序照 `evidence_weight`，敘事價值不進排序，13 已拍板不為此另設規則。

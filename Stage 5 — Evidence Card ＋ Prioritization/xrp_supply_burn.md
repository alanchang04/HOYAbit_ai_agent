---
tags: [projects, hackathon, hoyabit, evidence-card, xrp-supply-burn]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（xrp_supply_burn）；2026-08-02 新增
summary: XRP xrp_supply_burn 的 Evidence Card——全專案 prior_weight 最低（0.2）、回看範圍最短（40 秒）的一張；價值在敘事不在排序
---

```yaml
# Stage 5 — Evidence Card ＋ Prioritization（xrp_supply_burn）
#
#   fact       ← Stage 2 — Feature Extraction/xrp_supply_burn.yaml
#   knowledge  ← Stage 3 — Knowledge Layer/xrp_supply_burn.md
#   weight     ← Stage 4 — Dynamic Evidence Weight Engine/xrp_supply_burn.md（domain_knowledge 0.2）

evidence:
  evidence_id: XRP_SUPPLY_BURN_XRP  # ⚠️ {FACTOR}_{COIN} 機械套用，讀起來重複；
                                    # 同 BNB_BURN_BNB，不為單一 factor 破例
  category: snapshot

  ####################
  # fact ← Stage 2
  ####################
  fact:
    total_supply_xrp:               # 實測 99,985,632,191.46 XRP
    destroyed_this_ledger_drops:    # 實測 -544 drops（約 0.000544 XRP）
    ledger_index:                   # 實測 106,013,770
    close_time_human:               # 實測 2026-08-02T05:10:11.000Z
    destroyed_in_window_drops:      # 這 10 個帳本（約 40 秒）合計
    # ⚠️ percentile／z_score 整格不生成——10 個帳本、40 秒，算百分位沒有意義
    # （比照 13 拍板「填不出來的格子整格不產生不留 null」）
    # ⚠️ 卡片顯示 total_supply 時**必須**附上變化速率的量級說明，
    # 否則「999.86 億枚、正在減少」這句話會讓人以為是有意義的供給收縮

  features:                         # 完整欄位見 Stage 2 xrp_supply_burn.yaml
  knowledge:                        # 完整內容見 Stage 3 xrp_supply_burn.md

  ####################
  # evidence_weight ← Stage 4
  ####################
  evidence_weight:                  # = 0.2 × context_modifier
                                    #   basis = domain_knowledge（ic 結構性算不出）
                                    #   ⚠️ 0.2 是全專案最低的 prior_weight

  source_reliability: null
  historical_support: null
  primary_horizon:                  # ⚠️ 整格不生成——Snapshot 型沒有這個概念
  persistence:                      # ⚠️ 同上
  validity_window: 約 4 秒          # ← Stage 3（取代上面兩格）

  ####################
  # related_evidence ← Stage 3
  ####################
  related_evidence:
    confirms: null
    conflicts: null
    independent: cpi                # ✅ 唯一連得上的一條

  traceability: XRPScan /api/v1/ledger（免key，每日 10,000 次額度；2026-08-02 實測只回最近 10 個帳本≈40 秒，且回傳結構與 2026-07 文件記載不同）

prioritization:
  ranking_key: evidence_weight
  ranking_transform: abs
  evidence_coverage: null
  expected_rank: 最後               # prior_weight 0.2 是全專案最低，穩定墊底。
                                    # 這是刻意的——13「不刪除只排序」，所以用低權重
                                    # 讓它留在卡片列表裡但不干擾前段
```

## 這張卡是「不刪除只排序」這條拍板的壓力測試

13 拍板「算不出權重的不刪除，只排序」。這張卡把那條規則推到極限：它的資料是真的、
可查證的、XRP 獨有的，但**量級上明確不可能影響價格**（10 天銷毀佔總量 0.0000012%）。

換成「有 applicable: false 就刪掉」的設計，這張卡會被刪；照 13 現行拍板，它留著並靠
0.2 的權重沉底。兩種做法在**排序輸出**上結果一樣（都在最後），差別在**報告能不能引用**
——留著才講得出「XRP 有協議層通縮機制」這句話。

⚠️ 所以這張卡實際上支持了 13 現行的拍板：低權重 + 不刪除，比直接刪掉更有用。
這點值得回寫進 13 當作那條拍板的一個正面實例，但**我沒有動 13**，等 Ken 決定。

---
tags: [projects, hackathon, hoyabit, evidence-card, tps]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（tps）；2026-08-02 新增
summary: SOL tps 的 Evidence Card——資訊量最低的一張，價值在尾部事件而非日常值；13 沒有「條件式證據」的狀態可標
---

```yaml
# Stage 5 — Evidence Card ＋ Prioritization（tps）
#
#   fact       ← Stage 2 — Feature Extraction/tps.yaml
#   knowledge  ← Stage 3 — Knowledge Layer/tps.md
#   weight     ← Stage 4 — Dynamic Evidence Weight Engine/tps.md（domain_knowledge 0.25）

evidence:
  evidence_id: TPS_SOL
  category: snapshot

  ####################
  # fact ← Stage 2
  ####################
  fact:
    current_value:                  # 最新窗 TPS（含投票交易）
    current_value_non_vote:         # ⚠️ 這格一定要一起給——numTransactions 含 Solana
                                    # 共識的投票交易且佔比很高，只講總 TPS 會嚴重高估
                                    # 「使用者實際活動」。報告引用時必須說明用哪一個
    percentile:                     # ⚠️ 母體只有這 12 小時（實測 421 窗≈7 小時），
                                    # **不是**相對歷史。卡片顯示這格時必須同時標母體範圍，
                                    # 不能只寫「百分位 87」讓人誤以為是相對五年歷史
    trend:

  features:                         # 完整欄位見 Stage 2 tps.yaml
  knowledge:                        # 完整內容見 Stage 3 tps.md

  ####################
  # evidence_weight ← Stage 4
  ####################
  evidence_weight:                  # = 0.25 × context_modifier
                                    #   basis = domain_knowledge（ic 結構性算不出）
                                    #   ⚠️ 0.25 是目前所有 factor 裡最低的 prior_weight

  source_reliability: null
  historical_support: null
  primary_horizon:                  # ⚠️ 整格不生成——Snapshot 型沒有這個概念
                                    # （同 orderbook_depth，13 拍板「填不出來的格子整格不產生」）
  persistence:                      # ⚠️ 同上，整格不生成
  validity_window: 60 秒            # ← Stage 3 knowledge.validity_window（取代上面兩格）

  ####################
  # related_evidence ← Stage 3
  ####################
  related_evidence:
    confirms: null                  # Stage 3 誠實列空
    conflicts: null                 # Stage 3 誠實列空
    independent: cpi                # ✅ 唯一連得上的一條

  traceability: Solana 公開 RPC getRecentPerformanceSamples（免key；2026-08-02 實測上限 720 窗×60 秒＝12 小時，實得 421 窗）

prioritization:
  ranking_key: evidence_weight
  ranking_transform: abs
  evidence_coverage: null
  expected_rank: 最後段             # prior_weight 0.25 是最低的，除非 context_modifier
                                    # 拉到接近 2.0（例如真的偵測到網路異常），否則穩定墊底
```

## ⚠️ 這張卡暴露了一個 13 沒定義過的狀態

它是本專案第一張**條件式證據**：平常不該進報告（平穩的 3000 TPS 不說明任何事），
異常時是強證據（SOL 的核心風險敘事就是網路穩定性）。

但 13 對 Stage 5 只定義了兩種狀態——「算得出權重就排序」與（幣種模板新增的）
「對這個幣不適用就不生成」。**沒有「這次數值正常所以不值得講」這種狀態**。
目前只能照一般卡片處理：照樣生成、照樣排序、靠 0.25 的低權重讓它自然沉底。

要不要為這類 factor 補一個 `notable_only: true` 之類的狀態，待 Ken 拍板。
這條跟 13 待處理清單裡的第 5 條（不適用狀態）性質相近但不同——那條是「不該存在」，
這條是「存在但這次不值得講」。

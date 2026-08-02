---
tags: [projects, hackathon, hoyabit, evidence-card, price]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（示範：price）；2026-08-02 新增，補上 active_address.md 早就引用、但一直沒有卡片的 price 節點
---

```yaml
# Stage 5 — Evidence Card ＋ Prioritization（示範：price）
#
# 這張卡跟 liquidation 那張同一種「沒有 percentile／trend」的空格模式，但成因
# 是本質性的（快照定義上沒有母體），不是資料源限制——跟 [[Stage 4 — Dynamic
# Evidence Weight Engine/price]] 講的「ic 不適用」是同一件事的兩個層面。

evidence:
  evidence_id: PRICE_BTC            # 沿用 demo 的 {FACTOR}_{COIN} 格式
  category: statistical             # ← Stage 3 knowledge.category

  ####################
  # fact ← Stage 2（一次性快照，不是回看窗口的統計量）
  ####################
  fact:
    current_value:                  # 現貨報價（USD），Stage 2 輸出
    change_24h_pct:                 # 24 小時漲跌幅（%），CoinGecko／CryptoCompare 端點自帶，非本專案計算
    volume_24h_usd:                 # 24 小時成交量（USD）
    # ⚠️ 沒有 percentile、沒有 trend，而且是刻意不放這兩個 key，不是放 null：
    # 兩者都需要同一 factor 的歷史時間序列當母體／比較基準，快照這個 factor
    # 結構性沒有。放 null 會讓下游以為「這次剛好沒算出來」，整格不存在才傳達得出
    # 「這個概念對這個 factor 不成立」——跟 liquidation 那張卡同一個原則

  features:                         # 完整欄位見 Stage 2 price.yaml，卡片不重抄
  knowledge:                        # 完整內容見 Stage 3 price.md，卡片不重抄

  ####################
  # evidence_weight ← Stage 4 的 final_weight（ic 本質不適用，走 Domain Knowledge）
  ####################
  evidence_weight:                  # = prior_weight 0.35（Domain Knowledge，雙重理由：學術訊號本身有爭議＋
                                    #   價值形式是事實錨點不是預測器）× context_modifier

  source_reliability: null          # Stage 4 未定案，跟著留白，不重複造一套新標準
  historical_support: null          # 同上
  primary_horizon:                  # ← Stage 3 knowledge.primary_horizon＝即時快照（Spot），無固定觀察窗
  persistence:                      # ← Stage 3 knowledge.persistence＝極短（下一次抓取就是全新的值）

  ####################
  # related_evidence ← Stage 3 的 confirms／conflicts／independent（Stage 6 Evidence Graph 的邊）
  ####################
  related_evidence:
    confirms: volume_change_24h     # ← Stage 3（量價同步是技術分析最基礎的共識，價量背離是警訊）
    conflicts: active_address       # ← Stage 3（跟 [[Stage 3 — Knowledge Layer/active_address]] 自己列的
                                    #   conflicts=price 互相對應，同一條關係兩邊都寫了）
    independent: cpi                # ← Stage 3（不同時間尺度、不同成因的訊號，不假設固定關係）
    # ⚠️ 這張卡跟另外幾張最大的不同：conflicts 指向的 active_address 是本專案真的有卡片
    # 的 factor，邊接得上，price 不會是孤立節點——這正是新增這張卡的直接動機：
    # active_address.md 的 conflicts=price 這條關係，在這張卡出現之前，Stage 6 每次
    # 都只能列進 referenced_but_no_card，現在終於連得上一條真的邊

  traceability: CoinGecko /simple/price（免key，即時報價；失敗退 CryptoCompare /data/pricemultifull 備援）

prioritization:
  ranking_key: evidence_weight      # 13 拍板：純照 evidence_weight
  ranking_transform: abs            # 跟其他卡片一致：比大小時取絕對值。這張卡的 prior_weight 是
                                    # domain_knowledge 型（[0,1] 恆正），取絕對值對它不改變任何東西——
                                    # 這種卡本來就沒有「方向」這個概念（見 [[Stage 4 — Dynamic Evidence
                                    # Weight Engine/price]]）
  evidence_coverage: null           # 定義未拍板，不生成
  expected_rank: 中段               # prior 0.35 略高於 liquidation（0.3）、低於 cpi（0.8），
                                    # 介於「有理由的中等重要性」跟「高重要性」之間
```

### 為什麼要補這張卡

這是七張示範卡裡唯一一張**動機來自另一張卡本身**的：[[Stage 3 — Knowledge Layer/active_address]] 從一開始就把 `conflicts` 欄位填成 `price`（現貨價格走勢），但這個因子本身遲遲沒有對應卡片——每次 Stage 6 畫圖，這條關係都只能落在 `referenced_but_no_card` 裡，變成一條「知道存在、但連不上任何節點」的懸空關係。這張卡補上之後，那條邊終於連得上，`price` 也從「被提到但不存在的名字」變成圖上一個真實節點，而且一出現就不是孤立節點（透過 `conflicts=active_address` 直接連上）。

跟 liquidation 那張一樣，這張卡也是「空格多」的一張，但空格成因是**本質性**的：即時快照定義上沒有可回測的獨立歷史序列，不是資料源限制，也換不了資料源解決——這是 `price` 這個 factor 的本質特性，往後如果要補 percentile／trend 這類欄位，得改抓 `agent/collectors/price.py` 已經在算的五檔粒度區間統計或技術指標，是另一張獨立的卡，不是把這張卡的空格填滿。

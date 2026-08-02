---
tags: [projects, hackathon, hoyabit, evidence-card, hash-rate]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（hash_rate）；2026-08-02 新增
summary: BTC hash_rate 的 Evidence Card——本專案第一張讓 related_evidence 形成雙向 confirms 的卡片，三格關係全部連得上
---

```yaml
# Stage 5 — Evidence Card ＋ Prioritization（hash_rate）
#
#   fact       ← Stage 2 — Feature Extraction/hash_rate.yaml
#   knowledge  ← Stage 3 — Knowledge Layer/hash_rate.md
#   weight     ← Stage 4 — Dynamic Evidence Weight Engine/hash_rate.md（實測 ic 寫在檔案裡）

evidence:
  evidence_id: HASH_RATE_BTC        # {FACTOR}_{COIN} 暫行規則
  category: statistical             # ← Stage 3 knowledge.category

  ####################
  # fact ← Stage 2
  ####################
  fact:
    current_value:                  # 當日算力估計值（原始尺度，未換算單位）
    percentile:                     # 母體＝這次抓取的 window，卡片顯示時要一起顯示 window
    trend:                          # 由整段窗口前半／後半均值比較判讀出來的方向敘述
    # ⚠️ 單日 delta 不放進 fact 的解讀欄位：算力是從出塊速度回推的估計量，
    # 單日波動有相當比例來自出塊運氣，不是礦機真的上下線。要看方向請看 trend／slope_30d

  features:                         # 完整欄位見 Stage 2 hash_rate.yaml，卡片不重抄
  knowledge:                        # 完整內容見 Stage 3 hash_rate.md，卡片不重抄

  ####################
  # evidence_weight ← Stage 4
  ####################
  evidence_weight:                  # = prior_strength × context_modifier
                                    #   prior_weight.raw_value = 0.0242（horizon=14 實測 ic）
                                    #   prior_strength = 0.1929（收縮 0.886 後換算）
    # ⚠️ 這個 factor 的排序名次**跟 Horizon 高度相關**，比其他卡片明顯：
    #   horizon=7  → prior_strength 0.0644
    #   horizon=14 → prior_strength 0.1929
    #   horizon=30 → prior_strength 0.2440
    # 同一天、同一張卡，查詢尺度不同名次會差很多。這不是不穩定，是這個 factor
    # 的性質（資本支出驅動＝長尺度訊號）在排序上的正確反映

  source_reliability: null          # Stage 4 未定案，跟著留白
  historical_support: null          # 同上
  primary_horizon:                  # ← Stage 3＝中長期，applicable_days [30, 365]
  persistence:                      # ← Stage 3＝高（沉沒成本，狀態延續性最強的一類鏈上指標）

  ####################
  # related_evidence ← Stage 3
  ####################
  related_evidence:
    confirms: active_address        # ✅ 連得上，而且 active_address 卡片的 confirms 本來就列
                                    # hash-rate——**本專案第一組雙向 confirms 邊**
    conflicts: price                # ✅ 連得上（礦工投降時算力下降落後於價格）
    independent: cpi                # ✅ 連得上
    # ⚠️ 三格全部連得上，是目前八張卡裡唯一一張。對照組：funding_rate 三格全部連不上

  traceability: blockchain.info Charts API `hash-rate`（免key，日頻；2026-08-02 實測 timespan=5years 回 1822 筆）

prioritization:
  ranking_key: evidence_weight
  ranking_transform: abs            # 換算後恆非負，實質 no-op，宣告保留當防呆
  evidence_coverage: null           # 定義未拍板，不生成
  expected_rank: 中段，且隨 Horizon 上移   # horizon=30 時 prior_strength 0.2440，
                                    # 會超過 panews_sentiment(0.2437)／etf(0.2158)；
                                    # horizon=7 時只有 0.0644，掉到最後段
```

## 這份的特殊之處

**唯一一張 `related_evidence` 三格全部連得上的卡。** 這件事的意義不只是「好看」——
Stage 8 辯論層的 `DEBATE_GRAPH_RULE` 只在圖上有邊時才會觸發，三格全連代表這張卡是
目前唯一能同時觸發「supports 不可疊加信心」與「conflicts 必須正面處理」兩條規則的證據。

補上它之後 BTC 的圖從 11 條邊變 15 條（新增 3 條出邊，加上 active_address 原本那條
`confirms: hash-rate` 從 `referenced_but_no_card` 轉正），`referenced_but_no_card`
從 8 條降到 7 條。

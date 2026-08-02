---
tags: [projects, hackathon, hoyabit, evidence-card, coin-template, sol]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization；幣種模板（SOL）v2，2026-08-02
summary: SOL 會組出 7 張 Evidence Card，含 2026-08-02 新增的幣種專屬卡
---

# Stage 5 — Evidence Card ＋ Prioritization 幣種模板（SOL）

`evidence_id` 暫行規則 = `{FACTOR}_{COIN}`。

```yaml
coin: SOL
cards: 7

evidence_cards:
  - {evidence_id: FUNDING_RATE_SOL,     factor: funding_rate,     category: statistical,
     related_evidence: {confirms: open_interest, conflicts: long_short_ratio, independent: vol-compression}}   # 三格全部無卡
  - {evidence_id: PRICE_SOL,            factor: price,            category: statistical,
     related_evidence: {confirms: volume_change_24h, conflicts: active_address, independent: cpi}}
  - {evidence_id: CPI_SOL,              factor: cpi,              category: event,
     related_evidence: {confirms: null, conflicts: null, independent: null}}     # Event Knowledge 無三格
  - {evidence_id: PANEWS_SENTIMENT_SOL, factor: panews_sentiment, category: sentiment,
     related_evidence: {confirms: [news], conflicts: [], independent: []}}
  - {evidence_id: MOMENTUM_SOL,         factor: momentum,         category: statistical,
     related_evidence: {confirms: volume_change_24h, conflicts: active_address, independent: cpi}}
    # ⚠️ conflicts 指向 active_address——**只有 BTC 有那張卡**，其餘四幣這條連不上
  - {evidence_id: ORDERBOOK_DEPTH_SOL,  factor: orderbook_depth,  category: snapshot,
     related_evidence: {confirms: [funding_rate, open_interest], conflicts: null, independent: cpi}}

  - evidence_id: TPS_SOL         # ⭐ 新增
    factor: tps
    category: snapshot
    related_evidence: {confirms: null, conflicts: null, independent: cpi}
    note: ⚠️ 條件式證據——平常不該講，異常時才是強證據；13 沒有這個狀態可標

prioritization:
  ranking_key: evidence_weight
  ranking_transform: abs
  evidence_coverage: null
  output: 依 |evidence_weight| 由大到小排序後的 7 張卡（不刪除，只排序）

not_generated:
  - {evidence_id: ETF_SOL,            reason: 資料源不涵蓋（「不該存在」非「資訊不足」）}
  - {evidence_id: ACTIVE_ADDRESS_SOL, reason: 資料源不涵蓋（「不該存在」非「資訊不足」）}
  - {evidence_id: HASH_RATE_SOL,      reason: 概念不成立（非 PoW 鏈）}
```

## 幣種模板收掉了 13 的「待處理 5」

`etf`／`active_address`／`hash_rate` 三張卡對 SOL **不該存在**（不是資訊不足），在被生出來之前就被模板擋掉並附理由，不需要在卡片上多開 `applicable: false` 狀態。

⚠️ 注意這三張的「不該存在」理由不同層次：前兩張是**資料源不涵蓋**（找到來源就能補），`hash_rate` 是**概念不成立**（非 PoW 鏈，永遠不會有）。模板把兩者分開記，13 目前也沒有區分這兩種的欄位，一併記錄。

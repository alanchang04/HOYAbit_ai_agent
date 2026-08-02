---
tags: [projects, hackathon, hoyabit, evidence-card, coin-template, btc]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization；幣種模板（BTC）v2，2026-08-02
summary: BTC 會組出 9 張 Evidence Card，含 2026-08-02 新增的幣種專屬卡
---

# Stage 5 — Evidence Card ＋ Prioritization 幣種模板（BTC）

`evidence_id` 暫行規則 = `{FACTOR}_{COIN}`。

```yaml
coin: BTC
cards: 9

evidence_cards:
  - {evidence_id: FUNDING_RATE_BTC,     factor: funding_rate,     category: statistical,
     related_evidence: {confirms: open_interest, conflicts: long_short_ratio, independent: vol-compression}}   # 三格全部無卡
  - {evidence_id: PRICE_BTC,            factor: price,            category: statistical,
     related_evidence: {confirms: volume_change_24h, conflicts: active_address, independent: cpi}}
  - {evidence_id: CPI_BTC,              factor: cpi,              category: event,
     related_evidence: {confirms: null, conflicts: null, independent: null}}     # Event Knowledge 無三格
  - {evidence_id: PANEWS_SENTIMENT_BTC, factor: panews_sentiment, category: sentiment,
     related_evidence: {confirms: [news], conflicts: [], independent: []}}
  - {evidence_id: MOMENTUM_BTC,         factor: momentum,         category: statistical,
     related_evidence: {confirms: volume_change_24h, conflicts: active_address, independent: cpi}}
    # ⚠️ conflicts 指向 active_address——**只有 BTC 有那張卡**，其餘四幣這條連不上
  - {evidence_id: ORDERBOOK_DEPTH_BTC,  factor: orderbook_depth,  category: snapshot,
     related_evidence: {confirms: [funding_rate, open_interest], conflicts: null, independent: cpi}}

  - evidence_id: ETF_BTC
    factor: etf
    category: statistical
    related_evidence: {confirms: [price], conflicts: [active_address], independent: null}
    note: 2026-08-02 訂正——原 independent 指向已被移除的 liquidation；不改指 momentum（會與 SSRN 6592830 的雙向回饋迴圈矛盾），改 null
    confidence: very_low

  - evidence_id: ACTIVE_ADDRESS_BTC
    factor: active_address
    category: statistical
    related_evidence: {confirms: hash_rate, conflicts: price, independent: funding_rate}
    note: ⚠️ confirms 寫的是 hash-rate（連字號），新卡的 factor_id 是 hash_rate（底線），純字串比對接不起來——見 Stage 6 幣種模板②

  - evidence_id: HASH_RATE_BTC   # ⭐ 新增
    factor: hash_rate
    category: statistical
    related_evidence: {confirms: active_address, conflicts: price, independent: cpi}
    note: ✅ 唯一一張三格全部連得上的卡；與 active_address 形成本專案第一組雙向 confirms

prioritization:
  ranking_key: evidence_weight
  ranking_transform: abs
  evidence_coverage: null
  output: 依 |evidence_weight| 由大到小排序後的 9 張卡（不刪除，只排序）

not_generated: []               # BTC 九張全生成
```

## 13「待處理 5」在 BTC 看不出來

九張卡全部成立，`not_generated` 是空的。那條缺口要到其他四幣才會浮現。

---
tags: [projects, hackathon, hoyabit, evidence-graph, coin-template, eth]
source: [[13流程圖迭代定案v2]] Stage 6 — Evidence Graph；幣種模板（ETH）v2，2026-08-02
summary: ETH 7 張卡推出來的圖——7 節點／6 條邊／9 條指向空節點
---

# Stage 6 — Evidence Graph 幣種模板（ETH）

⚠️ 這張圖是**照 Stage 5 各卡片 `related_evidence` 欄位推導**出來的，
不是跑 `/api/stage6` 實測的輸出。建圖規則沿用同資料夾 `design.md`。

```yaml
coin: ETH
nodes: 7
edges: 6
referenced_but_no_card: 9

nodes_detail:
  - {evidence_id: FUNDING_RATE_ETH,      factor: funding_rate,      category: statistical}
  - {evidence_id: PRICE_ETH,             factor: price,             category: statistical}
  - {evidence_id: CPI_ETH,               factor: cpi,               category: event}
  - {evidence_id: PANEWS_SENTIMENT_ETH,  factor: panews_sentiment,  category: sentiment, isolated: true}
  - {evidence_id: MOMENTUM_ETH,          factor: momentum,          category: statistical}
  - {evidence_id: ORDERBOOK_DEPTH_ETH,   factor: orderbook_depth,   category: snapshot}
  - {evidence_id: GAS_ETH,  factor: gas, category: statistical}   # ⭐ 新增

edges_detail:
  - {from: PRICE_ETH,           to: CPI_ETH,          relation: independent}
  - {from: MOMENTUM_ETH,        to: CPI_ETH,          relation: independent}
  - {from: ORDERBOOK_DEPTH_ETH, to: FUNDING_RATE_ETH, relation: confirms}
  - {from: ORDERBOOK_DEPTH_ETH, to: CPI_ETH,          relation: independent}
  # ⚠️ MOMENTUM 的 conflicts 指向 active_address，ETH 沒有那張卡 → 連不上
  - {from: GAS_ETH,             to: PRICE_ETH,        relation: confirms}      # ⭐
  - {from: GAS_ETH,             to: CPI_ETH,          relation: independent}   # ⭐

referenced_but_no_card_detail:
  - {from: FUNDING_RATE_ETH,     relation: confirms,    referenced_factor: open_interest}
  - {from: FUNDING_RATE_ETH,     relation: conflicts,   referenced_factor: long_short_ratio}
  - {from: FUNDING_RATE_ETH,     relation: independent, referenced_factor: vol-compression}
  - {from: PRICE_ETH,            relation: confirms,    referenced_factor: volume_change_24h}
  - {from: PRICE_ETH,            relation: conflicts,   referenced_factor: active_address}   # ⚠️ BTC 沒有這條
  - {from: PANEWS_SENTIMENT_ETH, relation: confirms,    referenced_factor: news}
  - {from: MOMENTUM_ETH,         relation: confirms,    referenced_factor: volume_change_24h}
  - {from: MOMENTUM_ETH,         relation: conflicts,   referenced_factor: active_address}
  - {from: ORDERBOOK_DEPTH_ETH,  relation: confirms,    referenced_factor: open_interest}
```

## 跟 BTC 的圖比較

| | BTC | ETH |
|---|---|---|
| 節點 | 9 | 7 |
| 邊 | 14 | **6** |
| 指向空節點 | 8 | 9 |
| 孤立節點 | panews_sentiment | panews_sentiment |

新增的 `GAS_ETH` 帶進 2 條邊。即使如此，ETH 的圖仍然比 BTC 稀疏得多——
被拿掉的 `etf`／`active_address`／`hash_rate` 剛好是 BTC 圖上連通度最高的三個。

⚠️ **對 Stage 8 辯論層的實質影響**：ETH 圖上的 `conflicts` 邊數量遠少於 BTC，
`DEBATE_GRAPH_RULE` 的「看到 conflicts 必須正面處理」幾乎不會觸發。
這不是 bug，是「這次只分析了這幾個 factor」的自然後果，但報告時要講清楚，
不要讓人以為五幣的圖一樣紮實。

`open_interest` 仍是投報率最高的缺口（一張卡接回 3 條邊），但它是五幣共用的
衍生品資料，不屬於這輪「一幣一個幣種專屬 factor」的範圍。

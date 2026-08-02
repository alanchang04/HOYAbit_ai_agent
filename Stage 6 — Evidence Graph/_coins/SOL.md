---
tags: [projects, hackathon, hoyabit, evidence-graph, coin-template, sol]
source: [[13流程圖迭代定案v2]] Stage 6 — Evidence Graph；幣種模板（SOL）v2，2026-08-02
summary: SOL 7 張卡推出來的圖——7 節點／5 條邊／9 條指向空節點
---

# Stage 6 — Evidence Graph 幣種模板（SOL）

⚠️ 這張圖是**照 Stage 5 各卡片 `related_evidence` 欄位推導**出來的，
不是跑 `/api/stage6` 實測的輸出。建圖規則沿用同資料夾 `design.md`。

```yaml
coin: SOL
nodes: 7
edges: 5
referenced_but_no_card: 9

nodes_detail:
  - {evidence_id: FUNDING_RATE_SOL,      factor: funding_rate,      category: statistical}
  - {evidence_id: PRICE_SOL,             factor: price,             category: statistical}
  - {evidence_id: CPI_SOL,               factor: cpi,               category: event}
  - {evidence_id: PANEWS_SENTIMENT_SOL,  factor: panews_sentiment,  category: sentiment, isolated: true}
  - {evidence_id: MOMENTUM_SOL,          factor: momentum,          category: statistical}
  - {evidence_id: ORDERBOOK_DEPTH_SOL,   factor: orderbook_depth,   category: snapshot}
  - {evidence_id: TPS_SOL,  factor: tps, category: snapshot}   # ⭐ 新增

edges_detail:
  - {from: PRICE_SOL,           to: CPI_SOL,          relation: independent}
  - {from: MOMENTUM_SOL,        to: CPI_SOL,          relation: independent}
  - {from: ORDERBOOK_DEPTH_SOL, to: FUNDING_RATE_SOL, relation: confirms}
  - {from: ORDERBOOK_DEPTH_SOL, to: CPI_SOL,          relation: independent}
  # ⚠️ MOMENTUM 的 conflicts 指向 active_address，SOL 沒有那張卡 → 連不上
  - {from: TPS_SOL,             to: CPI_SOL,          relation: independent}   # ⭐（唯一連得上的一條）

referenced_but_no_card_detail:
  - {from: FUNDING_RATE_SOL,     relation: confirms,    referenced_factor: open_interest}
  - {from: FUNDING_RATE_SOL,     relation: conflicts,   referenced_factor: long_short_ratio}
  - {from: FUNDING_RATE_SOL,     relation: independent, referenced_factor: vol-compression}
  - {from: PRICE_SOL,            relation: confirms,    referenced_factor: volume_change_24h}
  - {from: PRICE_SOL,            relation: conflicts,   referenced_factor: active_address}   # ⚠️ BTC 沒有這條
  - {from: PANEWS_SENTIMENT_SOL, relation: confirms,    referenced_factor: news}
  - {from: MOMENTUM_SOL,         relation: confirms,    referenced_factor: volume_change_24h}
  - {from: MOMENTUM_SOL,         relation: conflicts,   referenced_factor: active_address}
  - {from: ORDERBOOK_DEPTH_SOL,  relation: confirms,    referenced_factor: open_interest}
```

## 跟 BTC 的圖比較

| | BTC | SOL |
|---|---|---|
| 節點 | 9 | 7 |
| 邊 | 14 | **5** |
| 指向空節點 | 8 | 9 |
| 孤立節點 | panews_sentiment | panews_sentiment |

新增的 `TPS_SOL` 帶進 1 條邊。即使如此，SOL 的圖仍然比 BTC 稀疏得多——
被拿掉的 `etf`／`active_address`／`hash_rate` 剛好是 BTC 圖上連通度最高的三個。

⚠️ **對 Stage 8 辯論層的實質影響**：SOL 圖上的 `conflicts` 邊數量遠少於 BTC，
`DEBATE_GRAPH_RULE` 的「看到 conflicts 必須正面處理」幾乎不會觸發。
這不是 bug，是「這次只分析了這幾個 factor」的自然後果，但報告時要講清楚，
不要讓人以為五幣的圖一樣紮實。

`open_interest` 仍是投報率最高的缺口（一張卡接回 3 條邊），但它是五幣共用的
衍生品資料，不屬於這輪「一幣一個幣種專屬 factor」的範圍。

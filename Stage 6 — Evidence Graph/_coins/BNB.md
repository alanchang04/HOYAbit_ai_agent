---
tags: [projects, hackathon, hoyabit, evidence-graph, coin-template, bnb]
source: [[13流程圖迭代定案v2]] Stage 6 — Evidence Graph；幣種模板（BNB）v2，2026-08-02
summary: BNB 7 張卡推出來的圖——7 節點／4 條邊／9 條指向空節點
---

# Stage 6 — Evidence Graph 幣種模板（BNB）

⚠️ 這張圖是**照 Stage 5 各卡片 `related_evidence` 欄位推導**出來的，
不是跑 `/api/stage6` 實測的輸出。建圖規則沿用同資料夾 `design.md`。

```yaml
coin: BNB
nodes: 7
edges: 4
referenced_but_no_card: 9

nodes_detail:
  - {evidence_id: FUNDING_RATE_BNB,      factor: funding_rate,      category: statistical}
  - {evidence_id: PRICE_BNB,             factor: price,             category: statistical}
  - {evidence_id: CPI_BNB,               factor: cpi,               category: event}
  - {evidence_id: PANEWS_SENTIMENT_BNB,  factor: panews_sentiment,  category: sentiment, isolated: true}
  - {evidence_id: MOMENTUM_BNB,          factor: momentum,          category: statistical}
  - {evidence_id: ORDERBOOK_DEPTH_BNB,   factor: orderbook_depth,   category: snapshot}
  - {evidence_id: BNB_BURN_BNB,  factor: bnb_burn, category: event, isolated: true}   # ⭐ 新增

edges_detail:
  - {from: PRICE_BNB,           to: CPI_BNB,          relation: independent}
  - {from: MOMENTUM_BNB,        to: CPI_BNB,          relation: independent}
  - {from: ORDERBOOK_DEPTH_BNB, to: FUNDING_RATE_BNB, relation: confirms}
  - {from: ORDERBOOK_DEPTH_BNB, to: CPI_BNB,          relation: independent}
  # ⚠️ MOMENTUM 的 conflicts 指向 active_address，BNB 沒有那張卡 → 連不上
  # ⭐ BNB_BURN_BNB 一條邊都沒有——Event Knowledge 無三格關係欄位（13 缺口 2）

referenced_but_no_card_detail:
  - {from: FUNDING_RATE_BNB,     relation: confirms,    referenced_factor: open_interest}
  - {from: FUNDING_RATE_BNB,     relation: conflicts,   referenced_factor: long_short_ratio}
  - {from: FUNDING_RATE_BNB,     relation: independent, referenced_factor: vol-compression}
  - {from: PRICE_BNB,            relation: confirms,    referenced_factor: volume_change_24h}
  - {from: PRICE_BNB,            relation: conflicts,   referenced_factor: active_address}   # ⚠️ BTC 沒有這條
  - {from: PANEWS_SENTIMENT_BNB, relation: confirms,    referenced_factor: news}
  - {from: MOMENTUM_BNB,         relation: confirms,    referenced_factor: volume_change_24h}
  - {from: MOMENTUM_BNB,         relation: conflicts,   referenced_factor: active_address}
  - {from: ORDERBOOK_DEPTH_BNB,  relation: confirms,    referenced_factor: open_interest}
```

## ⚠️⚠️ BNB 是唯一有**兩個**孤立節點的幣

`bnb_burn` 是 Event 型 → Event Knowledge 沒有 `confirms`／`conflicts`／`independent`
三格（13 缺口 2）→ **不發出任何邊**。而且跟 cpi 不同的是，cpi 至少有三張卡的
`independent` 指向它所以不孤立，**沒有任何一張卡指向 bnb_burn**。

加上本來就孤立的 `panews_sentiment`，BNB 七張卡裡有兩張完全不受 Stage 8
`DEBATE_GRAPH_RULE` 保護。**13 缺口 2 這是第二次咬人**（第一次是 cpi），
兩次都出現代表這不是個案而是 schema 缺陷，建議提高該缺口的優先序。

## 跟 BTC 的圖比較

| | BTC | BNB |
|---|---|---|
| 節點 | 9 | 7 |
| 邊 | 14 | **4** |
| 指向空節點 | 8 | 9 |
| 孤立節點 | panews_sentiment | **panews_sentiment ＋ bnb_burn** |

補了一張卡但**一條邊都沒增加**，是五幣裡唯一這樣的。BNB 圖上真正有推理價值的
`confirms` 只有 2 條、`conflicts` 一條都沒有——`DEBATE_GRAPH_RULE` 的「看到 conflicts
必須正面處理」對 BNB 完全不會觸發。報告與評審說明時要講清楚。

---
tags: [projects, hackathon, hoyabit, knowledge-layer, coin-template, eth]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer；幣種模板（ETH）v2，2026-08-02
summary: ETH 要載入的 7 份 Knowledge 檔清單，含 2026-08-02 新增的幣種專屬 factor
---

# Stage 3 — Knowledge Layer 幣種模板（ETH）

清單來源 = [[Stage 2 — Feature Extraction/_coins/ETH]] 的 `factors`，兩份必須一致。

```yaml
coin: ETH
knowledge_files: 7

load:
  - {factor: funding_rate,      spec: funding_rate.md,      category: statistical, applicable_days: [2, 60]}
  - {factor: price,             spec: price.md,             category: statistical, applicable_days: null}
  - {factor: cpi,               spec: cpi.md,               category: event,       applicable_days: [0, 90]}
  - {factor: panews_sentiment,  spec: panews_sentiment.md,  category: sentiment,   applicable_days: [1, 14]}
  - {factor: momentum,          spec: momentum.md,          category: statistical, applicable_days: [3, 30]}
  - {factor: orderbook_depth,   spec: orderbook_depth.md,   category: snapshot,    applicable_days: null}

  - factor: gas                  # ⭐ 新增
    spec: gas.md
    category: statistical
    applicable_days: [1, 60]
    supported_assets: [ETH]
    note: ⚠️ 序列橫跨 EIP-1559 與 L2 分流，前後段非同分布，window 不可無腦拉滿

not_loaded:
  - {factor: etf,            reason: supported_assets 只有 BTC}
  - {factor: active_address, reason: supported_assets 只有 BTC}
  - {factor: hash_rate,      reason: 概念不成立（非 PoW 鏈），跟資料源缺失是兩回事}
```

⚠️ `applicable_days: null` 的兩／三份（price／orderbook_depth，以及 Snapshot 型的新 factor）
代表 Stage 4 的 `time_horizon_match` 對它們算不出數字，只能定性交給 LLM。

---
tags: [projects, hackathon, hoyabit, knowledge-layer, coin-template, btc]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer；幣種模板（BTC）v2，2026-08-02
summary: BTC 要載入的 9 份 Knowledge 檔清單，含 2026-08-02 新增的幣種專屬 factor
---

# Stage 3 — Knowledge Layer 幣種模板（BTC）

清單來源 = [[Stage 2 — Feature Extraction/_coins/BTC]] 的 `factors`，兩份必須一致。

```yaml
coin: BTC
knowledge_files: 9

load:
  - {factor: funding_rate,      spec: funding_rate.md,      category: statistical, applicable_days: [2, 60]}
  - {factor: price,             spec: price.md,             category: statistical, applicable_days: null}
  - {factor: cpi,               spec: cpi.md,               category: event,       applicable_days: [0, 90]}
  - {factor: panews_sentiment,  spec: panews_sentiment.md,  category: sentiment,   applicable_days: [1, 14]}
  - {factor: momentum,          spec: momentum.md,          category: statistical, applicable_days: [3, 30]}
  - {factor: orderbook_depth,   spec: orderbook_depth.md,   category: snapshot,    applicable_days: null}

  - factor: etf
    spec: etf.md
    category: statistical
    applicable_days: [0, 10]
    supported_assets: [BTC]

  - factor: active_address
    spec: active_address.md
    category: statistical
    applicable_days: [14, 365]
    supported_assets: [BTC]

  - factor: hash_rate            # ⭐ 新增
    spec: hash_rate.md
    category: statistical
    applicable_days: [30, 365]   # 中長期——資本支出驅動
    supported_assets: [BTC]
    note: ⚠️ 對其他四幣是「概念不成立」（非 PoW）不是「資料源缺失」，兩者性質不同

not_loaded: []                  # BTC 九份全載
```

⚠️ `applicable_days: null` 的兩／三份（price／orderbook_depth，以及 Snapshot 型的新 factor）
代表 Stage 4 的 `time_horizon_match` 對它們算不出數字，只能定性交給 LLM。

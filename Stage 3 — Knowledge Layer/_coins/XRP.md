---
tags: [projects, hackathon, hoyabit, knowledge-layer, coin-template, xrp]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer；幣種模板（XRP）v2，2026-08-02
summary: XRP 要載入的 7 份 Knowledge 檔清單，含 2026-08-02 新增的幣種專屬 factor
---

# Stage 3 — Knowledge Layer 幣種模板（XRP）

清單來源 = [[Stage 2 — Feature Extraction/_coins/XRP]] 的 `factors`，兩份必須一致。

```yaml
coin: XRP
knowledge_files: 7

load:
  - {factor: funding_rate,      spec: funding_rate.md,      category: statistical, applicable_days: [2, 60]}
  - {factor: price,             spec: price.md,             category: statistical, applicable_days: null}
  - {factor: cpi,               spec: cpi.md,               category: event,       applicable_days: [0, 90]}
  - {factor: panews_sentiment,  spec: panews_sentiment.md,  category: sentiment,   applicable_days: [1, 14]}
  - {factor: momentum,          spec: momentum.md,          category: statistical, applicable_days: [3, 30]}
  - {factor: orderbook_depth,   spec: orderbook_depth.md,   category: snapshot,    applicable_days: null}

  - factor: xrp_supply_burn      # ⭐ 新增
    spec: xrp_supply_burn.md
    category: snapshot           # validity_window 約 4 秒，max_lookback 約 40 秒
    applicable_days: null        # 概念不成立
    supported_assets: [XRP]
    note: ⚠️ 量級上不可能影響價格——定位是敘事證據不是預測訊號

not_loaded:
  - {factor: etf,            reason: supported_assets 只有 BTC}
  - {factor: active_address, reason: supported_assets 只有 BTC}
  - {factor: hash_rate,      reason: 概念不成立（非 PoW 鏈），跟資料源缺失是兩回事}
```

⚠️ `applicable_days: null` 的兩／三份（price／orderbook_depth，以及 Snapshot 型的新 factor）
代表 Stage 4 的 `time_horizon_match` 對它們算不出數字，只能定性交給 LLM。

---
tags: [projects, hackathon, hoyabit, weight-engine, coin-template, btc]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine；幣種模板（BTC）v2，2026-08-02
summary: BTC 各 factor 的 Prior Weight 路徑與實測值；含 hash_rate 實測 ic=0.0242／n=1808
---

# Stage 4 — Dynamic Evidence Weight Engine 幣種模板（BTC）

⚠️ 本檔的實測值都是 BTC 的

```yaml
coin: BTC
conversion_constants: {ic_ref: 0.1, ic_shrink_c: 30}   # 全域常數，五幣共用

weights:
  - {factor: funding_rate,     basis: rolling_spearman_ic, scale: raw_ic, source: 現場算, measured: {horizon_days: 14, ic: -0.554}}
  - {factor: price,            basis: domain_knowledge,    scale: relative_strength, value: 0.35}
  - {factor: cpi,              basis: impact_level,        scale: relative_strength, value: 0.8}
  - {factor: panews_sentiment, basis: rolling_spearman_ic, scale: raw_ic, measured: {ic: 0.051, sample_size: 44, prior_strength: 0.2437, confidence: low}}
  - {factor: momentum,         basis: rolling_spearman_ic, scale: raw_ic, source: 現場算, measured: null}
    # ⚠️ 跟 funding_rate 一樣**沒有 Stage 4 .md**——值每次執行現場算，不是寫在檔案裡。
    #    2026-08-02 取代 liquidation（後者的 domain_knowledge 0.3 一併消失）
  - {factor: orderbook_depth,  basis: domain_knowledge,    scale: relative_strength, value: 0.35, ic: null}

  - factor: etf
    basis: rolling_spearman_ic
    scale: raw_ic
    btc_measured: {horizon_days: 1, ic: 0.0714, sample_size: 8, prior_strength: 0.2158}
    confidence: very_low

  - factor: active_address
    basis: rolling_spearman_ic
    scale: raw_ic
    btc_measured: {horizon_days: 14, ic: 0.0041, sample_size: 1807}

  - factor: hash_rate            # ⭐ 新增，2026-08-02 實測
    basis: rolling_spearman_ic
    scale: raw_ic
    btc_measured:
      horizon_days: 14
      ic: 0.0242
      sample_size: 1808
      shrink: 0.886
      prior_strength: 0.1929
      other_horizons: "h=7 ic=0.0075→0.0644／h=30 ic=0.0316→0.2440（隨 horizon 單調變強）"
    confidence: high             # 樣本 1808；⚠️ confidence 高 ≠ 有預測力
```

## ⚠️ 人工給值 vs 回測值的比例

BTC 九張卡裡有 5 張走 ic（funding_rate 現場算、panews／etf／active_address／hash_rate 讀實測值），4 張人工給值。是五幣裡回測支撐最厚的一個。

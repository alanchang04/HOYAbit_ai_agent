---
tags: [projects, hackathon, hoyabit, weight-engine, coin-template, eth]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine；幣種模板（ETH）v2，2026-08-02
summary: ETH 各 factor 的 Prior Weight 路徑與實測值；⚠️ 大部分 ic 欄位是空的——那些數字都是 BTC 算的
---

# Stage 4 — Dynamic Evidence Weight Engine 幣種模板（ETH）

⚠️ Stage 4 各 factor `.md` 裡寫的 ic 全部是拿 **BTC** 算的，對 ETH 一個都不能直接用；下面 measured 有值的才是這個幣自己跑過的

```yaml
coin: ETH
conversion_constants: {ic_ref: 0.1, ic_shrink_c: 30}   # 全域常數，五幣共用

weights:
  - {factor: funding_rate,     basis: rolling_spearman_ic, scale: raw_ic, source: 現場算, measured: null   # ⚠️ 本幣沒跑過}
  - {factor: price,            basis: domain_knowledge,    scale: relative_strength, value: 0.35}
  - {factor: cpi,              basis: impact_level,        scale: relative_strength, value: 0.8}
  - {factor: panews_sentiment, basis: rolling_spearman_ic, scale: raw_ic, measured: null   # ⚠️ 檔案裡的 0.051/n=44 是 BTC 的值}
  - {factor: momentum,         basis: rolling_spearman_ic, scale: raw_ic, source: 現場算, measured: null}
    # ⚠️ 跟 funding_rate 一樣**沒有 Stage 4 .md**——值每次執行現場算，不是寫在檔案裡。
    #    2026-08-02 取代 liquidation（後者的 domain_knowledge 0.3 一併消失）
  - {factor: orderbook_depth,  basis: domain_knowledge,    scale: relative_strength, value: 0.35, ic: null}

  - factor: gas                  # ⭐ 新增，2026-08-02 實測
    basis: rolling_spearman_ic
    scale: raw_ic
    measured:
      horizon_days: 14
      ic: 0.0187
      sample_size: 1874          # ⚠️ 不是 4021——被價格序列 1888 天交集卡住
      shrink: 0.888
      prior_strength: 0.1529
      other_horizons: "h=7 ic=0.0323→0.2493／h=30 ic=0.0379→0.2858（⚠️ 非單調，勿過度解讀）"
    confidence: high             # 這是 ETH 唯一有實測 ic 的 factor
```

## ⚠️ 人工給值 vs 回測值的比例

ETH 七張卡裡只有 2（funding_rate／gas 現場算或實測） 張走 ic，其餘人工給值，且那些人工值**五幣完全相同**。後果：換幣之後排序的變動來源很少。13 已記錄的「回測值被樣本折減、人工分級不被折減」那條不對稱在這裡影響比 BTC 大。

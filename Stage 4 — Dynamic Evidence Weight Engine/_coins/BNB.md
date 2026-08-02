---
tags: [projects, hackathon, hoyabit, weight-engine, coin-template, bnb]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine；幣種模板（BNB）v2，2026-08-02
summary: BNB 各 factor 的 Prior Weight 路徑與實測值；⚠️ 大部分 ic 欄位是空的——那些數字都是 BTC 算的
---

# Stage 4 — Dynamic Evidence Weight Engine 幣種模板（BNB）

⚠️ Stage 4 各 factor `.md` 裡寫的 ic 全部是拿 **BTC** 算的，對 BNB 一個都不能直接用；下面 measured 有值的才是這個幣自己跑過的

```yaml
coin: BNB
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

  - factor: bnb_burn             # ⭐ 新增
    basis: impact_level          # 同 cpi 路徑
    scale: relative_strength
    value: 0.5                   # Medium→0.5（cpi 是 Very High→0.8）
    ic: null                     # Event Factor 不算 ic；且季頻一年 4 點，本質不適用
    reason_short: 給 0.5 不是 0.8 的理由是「事前可預期、算不出實際 vs 預期的差額」，不是不重要
```

## ⚠️ 人工給值 vs 回測值的比例

BNB 七張卡裡只有 1（funding_rate 現場算） 張走 ic，其餘人工給值，且那些人工值**五幣完全相同**。後果：換幣之後排序的變動來源很少。13 已記錄的「回測值被樣本折減、人工分級不被折減」那條不對稱在這裡影響比 BTC 大。

---
tags: [projects, hackathon, hoyabit, weight-engine, coin-template, xrp]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine；幣種模板（XRP）v2，2026-08-02
summary: XRP 各 factor 的 Prior Weight 路徑與實測值；⚠️ 大部分 ic 欄位是空的——那些數字都是 BTC 算的
---

# Stage 4 — Dynamic Evidence Weight Engine 幣種模板（XRP）

⚠️ Stage 4 各 factor `.md` 裡寫的 ic 全部是拿 **BTC** 算的，對 XRP 一個都不能直接用；下面 measured 有值的才是這個幣自己跑過的

```yaml
coin: XRP
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

  - factor: xrp_supply_burn      # ⭐ 新增
    basis: domain_knowledge
    scale: relative_strength
    value: 0.2                   # ⚠️ 全專案最低
    ic: null                     # 結構性算不了（40 秒資料）
    reason_short: 低分理由是「量級上不可能有影響」（10 天燒掉 0.0000012%），不是資料少
    ⚠_modifier_gap: time_horizon_match 與 cross_source_consensus 兩條線索對它都無效
```

## ⚠️ 人工給值 vs 回測值的比例

XRP 七張卡裡只有 1（funding_rate 現場算） 張走 ic，其餘人工給值，且那些人工值**五幣完全相同**。後果：換幣之後排序的變動來源很少。13 已記錄的「回測值被樣本折減、人工分級不被折減」那條不對稱在這裡影響比 BTC 大。

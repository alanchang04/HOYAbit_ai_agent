---
tags: [projects, hackathon, hoyabit, weight-engine, tps]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine（tps）；2026-08-02 新增
summary: SOL tps 的 Prior Weight——ic 結構性算不出（資料只有 12 小時），走 domain_knowledge 給 0.25，是目前最低的一個
---

```yaml
# Stage 4 — Dynamic Evidence Weight Engine（tps）
#
# 跟 orderbook_depth／xrp_supply_burn 同一條路徑：資料源結構性缺歷史序列 → ic = null
# → Prior Weight 用 Domain Knowledge 給值＋理由。差別在給的值更低，理由見下。

weight:
  factor_id: tps

  historical_predictability:
    ic: null
    ic_null_reason: |
      ⚠️ 不是「還沒算」，是**算不了**。rolling_spearman_ic 需要 factor 值與
      forward_return 逐日對齊，而這個資料源的最大回看範圍是 12 小時
      （RPC limit 硬上限 720 窗 × 60 秒，2026-08-02 實測超過直接回 -32602），
      連一組跨日配對都湊不出來。這跟 panews_sentiment（44 筆，樣本不足但算得出）
      是不同層級的問題，跟 xrp_supply_burn（只回 10 個帳本≈40 秒）同一類。

  prior_weight:
    basis: domain_knowledge
    value: 0.25
    scale: relative_strength        # 已是 [0,1] 的 IC 等價強度，不換算、不做樣本收縮
    weight_direction: 不適用        # [0,1] 恆正，方向概念對它不成立
    reason: |
      給 0.25，比 orderbook_depth(0.35)／price(0.35) 都低，
      是目前所有 factor 裡第二低的（最低是 xrp_supply_burn 的 0.2）。三個理由：

      ① **日常值幾乎不帶資訊**。平穩的 3000 TPS 對「SOL 接下來會漲會跌」沒有
         任何已知的預測關係。相較之下 orderbook_depth 至少直接量測流動性成本、momentum 至少是
         有回測傳統的價格動能訊號，tps 兩者都不是。

      ② **價值集中在尾部事件**。SOL 的敘事是「網路穩定性／宕機」——這個 factor
         有用的時候是它異常的時候，但 Prior Weight 是一個**常數**，沒辦法表達
         「平常沒用、異常時很重要」。給高值會讓平常的無資訊數字排太前面，
         給低值則在真的宕機時排太後面。0.25 是選擇了「不要在平常誤導」，
         代價寫在這裡不藏。

      ③ **不做樣本收縮**（跟所有 relative_strength 型一樣）。這裡要特別標示 13
         已知的那條不對稱：hash_rate 的 ic=0.0242 被 1808 筆樣本折減後拿到
         0.1929，而這個「拍腦袋的 0.25」不被折減，反而排在前面——**一個沒有
         任何回測支持的數字贏過一個測了 1808 天的數字**。13 已記錄這條不對稱
         無解（解法會跟排序拍板打架），這份是它最刺眼的一個實例。

  ####################
  # Dynamic Modifier
  ####################
  market_regime:
    classification:
  time_horizon_match:            # ⚠️ 算不出數字——Snapshot 型沒有 applicable_days
                                 # （比照 orderbook_depth），這條線索對它只能定性
  cross_source_consensus:        # ⚠️ Stage 3 的 confirms／conflicts 都是 null，
                                 # 只有 independent(cpi)，而 independent 依 13 拍板不比方向
                                 # → 這條線索對這個 factor 實質上完全用不上
  freshness:                     # ✅ 這條反而最有意義——資料 60 秒就過期，
                                 # 是所有 factor 裡 freshness 最該嚴格判斷的一個

  context_modifier:              # 由 LLM 給，range=[0.5, 2.0]
  final_weight:                  # = 0.25 × context_modifier
```

## ⚠️ 四條 Dynamic Modifier 線索有兩條對它無效

`time_horizon_match` 算不出（沒有 applicable_days）、`cross_source_consensus` 用不上
（沒有 confirms／conflicts）。實質只剩 `market_regime`（定性）跟 `freshness`。

這代表這張卡的 `context_modifier` 幾乎完全由 LLM 自由心證決定，比其他 factor 更沒有
約束。這不是這份寫壞了，是 Snapshot 型 + 無關係欄位這個組合的必然結果——
`orderbook_depth` 只中了前一半（它至少有 confirms: funding_rate），tps 兩個都中。

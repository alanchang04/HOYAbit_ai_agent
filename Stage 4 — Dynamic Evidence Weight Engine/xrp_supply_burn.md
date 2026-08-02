---
tags: [projects, hackathon, hoyabit, weight-engine, xrp-supply-burn]
source: [[13流程圖迭代定案v2]] Stage 4 — Dynamic Evidence Weight Engine（xrp_supply_burn）；2026-08-02 新增
summary: XRP xrp_supply_burn 的 Prior Weight——ic 結構性算不出（只有 40 秒資料），domain_knowledge 給 0.2，是全專案最低
---

```yaml
# Stage 4 — Dynamic Evidence Weight Engine（xrp_supply_burn）

weight:
  factor_id: xrp_supply_burn

  historical_predictability:
    ic: null
    ic_null_reason: |
      ⚠️ 算不了，不是還沒算。端點只回最近 10 個帳本（約 40 秒，2026-08-02 實測），
      連一組跨日的 (factor_value, forward_return) 配對都湊不出來。
      跟 tps（12 小時）同一類結構性限制，
      而且比它們都更極端——**這是全專案回看範圍最短的 factor**。

  prior_weight:
    basis: domain_knowledge
    value: 0.2
    scale: relative_strength        # 已是 [0,1] IC 等價強度，不換算、不做樣本收縮
    weight_direction: 不適用
    reason: |
      給 0.2——**全專案最低**（低於 tps 的 0.25、orderbook_depth 的 0.35）。
      理由不是資料少，是**量級上這件事不可能影響價格**：

      實測 10 天銷毀約 1,233 XRP，佔總量（999.86 億）的 0.0000012%。
      就算把這個速率外推一整年，供給減少也只有約 0.00004%。任何一個交易
      horizon 下，這個供給變動都在雜訊裡看不見。

      這跟 tps(0.25) 的低分理由不同：tps 是「平常沒資訊、異常時有」，
      xrp_supply_burn 是「連異常都不會有」——銷毀速率由交易量決定，
      而交易量的波動早就被別的 factor 涵蓋了。

      ⚠️ 那為什麼還給 0.2 而不是 0？因為 13 拍板「不刪除只排序」，
      而且它確實是**真實、可查證、XRP 獨有**的事實，在報告裡有敘事價值
      （「XRP 有協議層通縮機制」）。0.2 的意思是「留著、但排最後」。

  ####################
  # Dynamic Modifier
  ####################
  market_regime:
    classification:
  time_horizon_match:            # ⚠️ 算不出數字——Snapshot 型沒有 applicable_days（同 tps／orderbook_depth）
  cross_source_consensus:        # ⚠️ 用不上——confirms／conflicts 都是 null，
                                 # 只有 independent(cpi)，而 independent 依 13 拍板不比方向
  freshness:                     # ✅ 唯一完全有效的一條，而且門檻極嚴：
                                 # 資料 4 秒就是下一個帳本了

  context_modifier:              # 由 LLM 給，range=[0.5, 2.0]
  final_weight:                  # = 0.2 × context_modifier
```

## 跟 tps 一起看：兩張「四條線索有兩條無效」的卡

| | tps (SOL) | xrp_supply_burn (XRP) |
|---|---|---|
| prior_weight | 0.25 | **0.2**（全專案最低）|
| max_lookback | 12 小時 | **約 40 秒** |
| time_horizon_match | ❌ 算不出 | ❌ 算不出 |
| cross_source_consensus | ❌ 用不上 | ❌ 用不上 |
| 低分理由 | 平常沒資訊、異常時有 | 量級上不可能有影響 |

兩張卡的 `context_modifier` 都幾乎只剩 LLM 自由心證（只有 `market_regime` 定性
跟 `freshness` 可用）。這是 Snapshot 型 ＋ 無關係欄位這個組合的共同後果，
不是個別 factor 寫壞了——如果之後要補救，該補的是「Snapshot 型要不要定義
applicable_days 的等價物」，而不是逐份調數字。

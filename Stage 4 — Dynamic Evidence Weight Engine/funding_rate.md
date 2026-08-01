---
tags: [projects, hackathon, hoyabit, dynamic-evidence-weight, draft]
source: [[11流程圖模板]] Stage 4 — Dynamic Evidence Weight Engine（示範：funding_rate）
---

## Stage 4 — Dynamic Evidence Weight Engine（示範：funding_rate）

> Market Regime 沿用 ATR 那份的定義（降息與否，FOMC 利率決議方向）。
>
> **Dynamic Modifier → context_modifier**：不用公式連乘，改由 LLM 讀取
> market_regime／time_horizon_match／context 這幾個線索，解釋並給出一個
> context_modifier 數字（含理由），再乘以 Prior Weight 得到 Final Weight。

```
weight:
  factor_id: funding_rate

  ####################
  # Prior Weight（來自 Knowledge，慢變動）
  ####################
  historical_predictability:
    ic: 0.11                     # 示範值
    # hit_rate: 0.63             # 示範值，先註解
    # normalization:             # 正規化公式，待 Ken 校準，先註解
  # source_reliability:          # 待來源可信度分級表定案，先註解
  # historical_support:          # 對應 references 欄位怎麼轉成分數，待定，先註解

  ####################
  # Dynamic Modifier（來自今日市場，快變動——餵給 LLM 當線索，不套公式）
  ####################
  market_regime:
    classification:              # rate_cutting／rate_hiking／rate_hold 三態，資料來源＝FOMC 利率決議方向（沿用 ATR 定義）
  time_horizon_match:            # 計算規則待補（Ken 說等等處理）
  context:                       # 待定

  context_modifier:              # 由 LLM 根據上述線索解釋給出，非公式計算
  final_weight:                  # = prior_weight × context_modifier（LLM 給的數字）
```

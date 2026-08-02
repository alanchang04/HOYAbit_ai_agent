---
tags: [projects, hackathon, hoyabit, evidence-card, snapshot, orderbook]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（示範：orderbook_depth）；第四型（Snapshot）第一張卡，暴露 Evidence Card schema 兩格對 Snapshot 型不成立
---

```yaml
# Stage 5 — Evidence Card ＋ Prioritization（示範：orderbook_depth）
#
# 這張卡是**第四型（Snapshot）的第一張**，跟 cpi 那張一樣會撞到 schema 問題，
# 但撞的地方不同：
#   cpi（Event）      → primary_horizon／persistence 在 Event Knowledge 裡**換了名字**
#                       （reaction_window／expected_duration），所以用 `→ 對應欄位` 解決
#   orderbook_depth   → 這兩個概念在 Snapshot Knowledge 裡**根本不存在**，不是換名字。
#                       所以這張卡直接**不放這兩格**，不是留 null、也不是硬對應到
#                       validity_window（那會讓 Stage 4 拿「秒級」去比對查詢的「2 週」，
#                       算出一個單位錯置的落差判斷，見 Stage 4 那份的提醒）

evidence:
  evidence_id: ORDERBOOK_DEPTH_BTC   # {FACTOR}_{COIN}（13 命名規則仍待定，暫行規則）
  category: snapshot                 # ← Stage 3 knowledge.category，第四型

  ####################
  # fact ← Stage 2（當下快照，不是歷史統計）
  ####################
  fact:
    mid_price:                       # 中價
    spread_bps:                      # 買賣價差（bps）——最直接的「貴不貴」
    bid_depth_10bps:                 # ±10bps 內的買方掛單量
    ask_depth_10bps:                 # ±10bps 內的賣方掛單量
    depth_imbalance_10bps:           # (買-賣)/(買+賣)，正值＝買方厚
    # ⚠️ 這裡沒有 percentile、沒有 trend——跟 liquidation 同一個原則（概念不成立的
    # key 整格不放），但原因不同：liquidation 是資料源不給歷史，這型是**當下狀態本來
    # 就沒有母體**。卡片上顯示 depth_imbalance=+44% 時，讀的人會想問「這算高嗎」，
    # 而這張卡誠實的答案是「不知道，沒有母體可比」——要能回答就得先自建歷史
    # （見 Stage 2 orderbook_depth.yaml 檔尾第 3 點）

  features:                          # 完整欄位（slippage／book_span_bps／levels_returned…）見 Stage 2 orderbook_depth.yaml
  knowledge:                         # 完整內容見 Stage 3 orderbook_depth.md（Snapshot Knowledge 骨架）

  ####################
  # evidence_weight ← Stage 4 的 final_weight
  ####################
  evidence_weight:                   # = prior_strength 0.35（Domain Knowledge，scale 已是 [0,1]）× context_modifier
    # ⚠️ 全專案目前最沒有支撐的一個權重：不是回測值、也還沒有文獻（Stage 3 references
    # 是空的）。它比 liquidation(0.3) 高一點的唯一理由是「至少測得到」。
    # 讀這張卡的人要知道：這個數字現在的角色是「先有個能跑的位置」，不是結論

  source_reliability: null           # Stage 4 未定案，跟著留白
  historical_support: null           # 同上——而且這格對本 factor 特別空：沒有歷史可支撐
  # primary_horizon / persistence：**這兩格不放**（不是留 null）。Snapshot Knowledge
  # 沒有這兩個概念，放了會讓下游以為「這次剛好沒填」。這是這張卡跟 cpi 那張最大的差別

  ####################
  # related_evidence ← Stage 3 的 confirms／conflicts／independent
  ####################
  related_evidence:
    confirms:                        # ← Stage 3：funding_rate ＋ open_interest（微結構三切面）
    conflicts:                       # ← Stage 3：尚無已知穩定的矛盾對象（待文獻查證）
    independent:                     # ← Stage 3：cpi
    # confirms 裡的 funding_rate 是本專案真的有卡片的 factor，這條邊接得上；
    # open_interest 一樣沒有對應卡片（跟其他幾張卡同一個缺口：知識層 factor 名
    # → 本次執行 evidence_id 缺一層解析）

  traceability:                      # Binance USDⓈ-M /fapi/v1/depth（limit=1000）

prioritization:
  ranking_key: evidence_weight       # 13 拍板：純照 evidence_weight
  ranking_transform: abs             # 2026-08-02 拍板：比大小時取絕對值。對這張卡是 no-op
                                     # （Domain Knowledge 給的 [0,1] 值恆正），但宣告要跟其他卡一致——
                                     # 混用才是會出事的狀態（同一次排序裡兩張卡用不同尺度比大小）
  evidence_coverage: null            # 定義未拍板，不生成
  expected_rank: 中段                # prior 0.35 略高於 liquidation(0.3)、遠低於 cpi(0.8)；
                                     # 實際名次還要看 context_modifier——而這型的 modifier 有個已知
                                     # 問題：time_horizon_match 會拿「秒級有效期」去比對查詢的「2 週」，
                                     # 機械式壓到下限，見 Stage 4 orderbook_depth.md 的提醒
```

### 這張卡暴露的 schema 缺口

Evidence Card 的欄位定義是照 Statistical Factor 寫的，到目前為止三型撞到的方式各不相同，值得一起看：

| 卡片欄位 | Statistical | Event（cpi） | Sentiment（panews） | **Snapshot（本張）** |
|---|---|---|---|---|
| `primary_horizon` | 直接對應 | `→ reaction_window`（換名字） | 有，但值是「狀態依存」不是單一尺度 | **概念不存在 → 整格不放** |
| `persistence` | 直接對應 | `→ expected_duration` | Stage 3 沒給單一值 → 不放 | **概念不存在 → 整格不放** |
| `fact.percentile` | 有母體 | 有但語意可疑（月頻指數單調上升） | 有 | **沒有母體 → 不放** |

三種「不放」的理由完全不同（換名字／沒給值／概念不成立），但卡片上看起來都是「這格沒有」。這是 13 待處理清單裡「Evidence Card schema 分型」那條的最新一筆證據——**卡片格式需要一個欄位級的狀態標記**（是不適用、還是這次沒算出來、還是換了名字），不然讀卡的人分不出來。這輪不擅自發明，先記錄。

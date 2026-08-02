---
tags: [projects, hackathon, hoyabit, evidence-card, momentum]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（示範：momentum）；2026-08-02 新增，跟 funding_rate 同一種「Prior Weight 沒有檔案可讀，現場算」的卡片
---

```yaml
# Stage 5 — Evidence Card ＋ Prioritization（示範：momentum）
#
#   fact       ← [[Stage 2 — Feature Extraction/momentum]]（yaml）
#   knowledge  ← [[Stage 3 — Knowledge Layer/momentum]]（md）
#   weight     ← Stage 4 現場算 rolling_spearman_ic（這個 factor 沒有 Stage 4 .md——
#                走的是預設 Statistical 路徑，值是算出來的不是寫在檔案裡，
#                跟 funding_rate 同一種模式，實測 BTC ic≈0.032，見程式驗證紀錄）

evidence:
  evidence_id: MOMENTUM_BTC         # 沿用 demo 的 {FACTOR}_{COIN} 格式
  category: statistical             # ← Stage 3 knowledge.category

  ####################
  # fact ← Stage 2（原始事實，不做任何解讀）
  ####################
  fact:
    current_value:                  # 最新一筆 RSI14（0~100），Stage 2 輸出
    percentile:                     # percentile_rank(current_value, series)，母體＝這次抓取的 window
    trend:                          # 由整段窗口前半／後半均值比較判讀出來的方向敘述
    # ⚠️ percentile 的母體是「LLM 依 Horizon 決定的那個 window」，不是固定天數——
    # 跟 funding_rate／active_address 同一個提醒，是 Stage 2「window 由 LLM 定」的共同後果
    # ⚠️ rsi_zone（超買/超賣/中性標籤）不放進 fact：它是 current_value 的分級解讀，
    # 不是原始事實。Stage 2 輸出裡有這格，要看完整欄位看 features

  features:                         # 完整欄位見 Stage 2 momentum.yaml，卡片不重抄
  knowledge:                        # 完整內容見 Stage 3 momentum.md，卡片不重抄

  ####################
  # evidence_weight ← Stage 4 的 final_weight（Statistical Factor 走 ic，現場算）
  ####################
  evidence_weight:                  # = prior_weight（＝ rolling_spearman_ic 算出來的 ic 本身）
                                    #   × context_modifier（LLM 給，[0.5, 2.0]）
    # 跟 funding_rate 同一種情況：這格沒有檔案可讀，是每次執行現場用「本地 CSV
    # 收盤價算出的 RSI14 序列 × 本地 CSV 收盤價算出的 forward_return」算出來的，
    # 同一個 factor 在不同 Horizon 下會得到不同的 ic。實測 BTC／horizon=14 天
    # 算出 ic≈0.0317（sample_size=1798）——小幅正相關，樣本數大，方向上「RSI 較高
    # 時後續報酬略高」，強度不算強，不代表沒有訊號，交給排序階段自然定位

  source_reliability: null          # Stage 4 未定案（該層仍註解狀態），跟著留白
  historical_support: null          # 同上
  primary_horizon:                  # ← Stage 3 knowledge.primary_horizon＝短期至中期（3~30 天適用）
  persistence:                      # ← Stage 3 knowledge.persistence＝短（逐日重算，狀態可持續數天到一兩週）

  ####################
  # related_evidence ← Stage 3 的 confirms／conflicts／independent（Stage 6 Evidence Graph 的邊）
  ####################
  related_evidence:
    confirms: volume_change_24h     # ← Stage 3（動量訊號搭配量能確認才可靠，產業共識）
    conflicts: active_address       # ← Stage 3（價格動能可能因槓桿/衍生品快速上衝，鏈上實際使用量沒跟上）
    independent: cpi                # ← Stage 3（不同時間尺度、不同成因的訊號，不假設固定關係）
    # ⚠️ conflicts 指向的 active_address 是本專案真的有卡片的 factor，邊接得上；
    # confirms 指向的 volume_change_24h 目前沒有對應卡片，會落在 referenced_but_no_card

  traceability: 本地技術指標計算（data/{coin}_daily_ohlcv.csv，RSI14 逐日重算，非外部資料，零網路成本）

prioritization:
  ranking_key: evidence_weight      # 13 拍板：純照 evidence_weight
  ranking_transform: abs            # 2026-08-02 拍板：比大小時取絕對值——ic 是相關係數，負值代表反向訊號，
                                    # 不是弱訊號。這張卡實測是正值（≈0.03），取絕對值對這次結果影響不大，
                                    # 但規則跟其他卡片一致，不因這次剛好是正值就不寫
  evidence_coverage: null           # 定義未拍板，不生成
  expected_rank: 不可預測           # 跟 funding_rate 同一種情況——ic 每次現場算，可正可負，
                                    # 絕對值大小也隨 Horizon 與幣種變動，排名事前講不出來
```

### 為什麼這張卡跟 funding_rate 那張最像

四個既有 factor 裡，只有 `funding_rate` 是「Prior Weight 完全沒有檔案可讀，靠現場算 ic」；`momentum` 是第二個——不是因為偷懶沒補 Stage 4 .md，是因為它跟 funding_rate 一樣有**真正可回測的獨立歷史序列**（RSI14 逐日重算），套用 `impact_level`／`domain_knowledge` 那種「人工給分」的處理方式反而是浪費了這個 factor 結構上最大的優勢——能現場驗證，不用猜。跟 `price`／`liquidation`／`cpi` 那種「本質上或資料源上就是不能算 ic」的三種情況不同，`momentum` 的 `ic: null` 不會出現在任何 Stage 4 文件裡，因為它從來不會走到那條分支。

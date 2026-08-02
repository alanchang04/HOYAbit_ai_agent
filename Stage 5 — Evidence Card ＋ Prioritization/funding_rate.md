---
tags: [projects, hackathon, hoyabit, evidence-card, funding-rate]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（示範：funding_rate）；13 正文那張卡就是拿這個 factor 畫的，這份是把它獨立成檔，讓四個 factor 的卡片 schema 都有對應檔案可讀
---

```yaml
# Stage 5 — Evidence Card ＋ Prioritization（示範：funding_rate）
#
# 2026-08-02 補檔說明：funding_rate 原本沒有獨立的卡片檔——13 正文的 Evidence Card
# 範例就是拿它畫的，所以另外三個 factor 各寫一份時它被跳過了。Stage 5 改成
# 「程式讀卡片 schema 檔」之後，缺這份會讓它變成唯一寫死在程式裡的例外，所以
# 照另外三份的骨架補上。內容＝13 正文那張卡，不是新設計。
#
# 這張卡的定位：**schema 的基準卡**。13 的 Evidence Card 欄位定義就是照這個 factor
# （Statistical Factor＋Statistical Knowledge）寫的，所以它每一格都對得上來源欄位，
# 沒有 cpi 那種分型缺口、也沒有 liquidation 那種資料源缺口。要判斷別張卡是「格式問題」
# 還是「資料問題」，拿這張當對照組。
#
#   fact       ← [[Stage 2 — Feature Extraction/funding_rate]]（yaml）
#   knowledge  ← [[Stage 3 — Knowledge Layer/funding_rate]]（md）
#   weight     ← Stage 4 現場算 rolling_spearman_ic（這個 factor 沒有 Stage 4 .md——
#                它走的是預設 Statistical 路徑，值是算出來的不是寫在檔案裡，
#                跟 cpi／liquidation「值寫在 .md 裡由程式讀」不同）

evidence:
  evidence_id: FUNDING_RATE_BTC     # 沿用 demo 的 {FACTOR}_{COIN} 格式（13 命名規則仍待定；
                                    # 13 正文的 DER_FUNDING_001 只是 11 沿用下來的示範字串，不是規則）
  category: statistical             # ← Stage 3 knowledge.category

  ####################
  # fact ← Stage 2（原始事實，不做任何解讀）
  ####################
  fact:
    current_value:                  # 最新一筆結算費率（Stage 2 輸出已轉成 +0.0000% 格式）
    percentile:                     # percentile_rank(current_value, series)，母體＝這次抓取的 window
    trend:                          # 由整段窗口前半／後半均值比較判讀出來的方向敘述
    # ⚠️ percentile 的母體是「LLM 依 Horizon 決定的那個 window」，不是固定近 30 天——
    # 同一天、不同 Horizon 的查詢會給出不同的 percentile。卡片顯示時要一起顯示 window
    # （這條跟 active_address 那張卡同一個提醒，是 Stage 2「window 由 LLM 定」的共同後果）
    # ⚠️ crowd_label（擁擠度標籤）不放進 fact：它是 percentile 的分級解讀，不是原始事實。
    # Stage 2 輸出裡有這格，要看完整欄位看 features

  features:                         # 完整欄位（slope/roc/rolling_*/z_score/quality/crowd_label）
                                    # 見 Stage 2 funding_rate.yaml，卡片不重抄
  knowledge:                        # 完整內容見 Stage 3 funding_rate.md，卡片不重抄

  ####################
  # evidence_weight ← Stage 4 的 final_weight（Statistical Factor 走 ic，現場算）
  ####################
  evidence_weight:                  # = prior_weight（＝ rolling_spearman_ic 算出來的 ic 本身）
                                    #   × context_modifier（LLM 給，[0.5, 2.0]）
    # ⚠️ 這格跟另外三張卡最大的差別：它的 prior_weight **沒有檔案可讀**，是每次執行
    # 現場用「本地 CSV 價格 × Binance funding 歷史」算出來的，所以同一個 factor 在不同
    # Horizon 下會得到不同的 ic（這正是 13 把 ic 改成吃 Horizon 當參數的用意）。
    # 附帶後果：這張卡的排名不像 cpi（固定 0.8）／liquidation（固定 0.3）那樣可預測，
    # ic 是相關係數、值域 [-1, 1]，**可能是負的**——負的 ic × 正的 modifier 會讓
    # evidence_weight 變負數，排序時直接掉到最後面。負 ic 的意思是「這個 factor 在這個
    # Horizon 下跟未來報酬反向相關」，不是「算錯了」，但要不要在排序上跟「趨近 0」
    # 分開處理，13 拍板是不分開——一律照 evidence_weight 排

  source_reliability: null          # Stage 4 未定案（該層仍註解狀態），跟著留白，不重複造一套新標準
  historical_support: null          # 同上，待「references 怎麼轉成分數」定案後一起補
  primary_horizon:                  # ← Stage 3 knowledge.primary_horizon＝短期（每 8 小時結算，近 30 天百分位）
  persistence:                      # ← Stage 3 knowledge.persistence＝中低（費率每 8 小時重算，
                                    #   但它反映的「擁擠倉位」狀態可持續數日到數週）

  ####################
  # related_evidence ← Stage 3 的 confirms／conflicts／independent（Stage 6 Evidence Graph 的邊）
  ####################
  related_evidence:
    confirms: open_interest         # ← Stage 3（產業共識：funding + OI 合看才判斷得出擁擠 regime）
    conflicts: long_short_ratio     # ← Stage 3（倉位大小加權 vs 帳戶數加權，可能背離）
    independent: vol-compression    # ← Stage 3（費率看付費壓力方向，vol-compression 看波動大小）
    # ⚠️ 三格列的 factor 本專案都沒有對應卡片（KNOWN_FACTORS 五個：funding_rate／
    # active_address／cpi／liquidation／panews_sentiment，不含 open_interest／
    # long_short_ratio／vol-compression），Stage 6 畫圖時
    # 這三條邊一樣會指向不存在的節點——跟 active_address 那張卡是同一個缺口
    # （知識層 factor 名 → 本次執行 evidence_id 缺一層解析）。
    # 反過來，liquidation 那張卡的 confirms 列了 funding_rate，所以圖上有一條
    # liquidation → funding_rate 的邊連得上；這張卡在圖上不是孤立節點，但它自己列的
    # 三條邊一條都連不上

  traceability: Binance USDⓈ-M /fapi/v1/fundingRate（免key，每 8 小時一筆結算費率）

prioritization:
  ranking_key: evidence_weight      # 13 拍板：純照 evidence_weight
  evidence_coverage: null           # 定義未拍板，不生成
  expected_rank: 不可預測           # 唯一一張排名事前講不出來的卡——另外三張的 prior_weight
                                    # 要嘛是固定值（cpi 0.8／liquidation 0.3），要嘛結構性趨近 0
                                    # （active_address ic≈0），只有這張的 ic 每次現場算、
                                    # 可正可負。實測（BTC／horizon=2週）它排最後（final=-0.554），
                                    # 但那是那一次的 ic 值，不是這個 factor 的固定位置
```

### 這份的特殊之處

四張卡裡，它是**唯一一張 Prior Weight 沒有檔案可讀的卡**。另外三張的權重來源都落在某個 `.md` 裡（cpi 讀 `impact_level`、liquidation 讀 Domain Knowledge 值、active_address 雖然也是現場算 ic 但同時有一份 Stage 4 .md 記錄實測結果），只有 funding_rate 從頭到尾靠現場計算。這件事在「程式讀規格檔」的架構下有個意義：**卡片 schema 讀得到檔案，不代表卡片的每一個值都讀得到檔案**——schema 講的是「這張卡長什麼樣」，值還是各層自己算出來的。這正是 13 說 Stage 5 是「組裝／輸出格式層，不重新運算」的意思。

另外一點，`evidence_weight` 可能是負數這件事只有這張卡會遇到（cpi/liquidation 是 [0,1] 的重要性分數，active_address 的 ic 實測趨近 0 的正值）。13 的排序拍板「一律照 evidence_weight 由大到小」在負值上仍然成立、也不需要特別處理，但值域不一致這件事會讓「排序鍵到底在比什麼」更難解釋——這是 13「待處理 3」（Prior Weight 尺度沒統一、`normalization` 仍是註解狀態）在這張卡上的具體樣子。

---
tags: [projects, hackathon, hoyabit, evidence-card, sentiment, panews]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（示範：panews_sentiment）；組裝 Stage 2 Fact／Stage 3 Knowledge／Stage 4 Weight 三層真實輸出，非編造
---

```yaml
# Stage 5 — Evidence Card（示範：panews_sentiment）
# 組裝 Stage 2 Fact／Stage 3 Knowledge／Stage 4 Weight 三層輸出成統一卡片，
# 這一層本身不產生新資訊，純粹組裝——欄位結構比照
# [[Stage 5 — Evidence Card ＋ Prioritization/../11流程圖模板]] 的 Evidence Card 骨架，
# 對照既有 funding_rate 示範。

evidence:
  evidence_id: PANEWS_SENTIMENT_BTC  # ⚠️ 2026-08-02 拉齊（原本寫 SENT_PANEWS_BTC_001）：13 正文的
                                     # `DER_FUNDING_001` 是從 11 沿用下來的示範字串，13 自己標「命名規則待定」，
                                     # 不是可以比照的規則——「類型前綴_來源_幣種_序號」裡的前綴對照表沒人定義過，
                                     # 序號也沒有任何東西在產生。實際會跑的是 demo 的 `_evidence_id()`＝
                                     # `{FACTOR}_{COIN}`，其他四張卡都是這個格式，這份跟上，全專案先只有一套。
                                     # 正式命名規則仍待拍板，屆時四張卡一起改
  category: sentiment                # 沿用 Stage 3 Knowledge 的類型分類

  fact:                              # = Stage 2 Feature Extraction 的原始事實（示範 run：2026-06-16~2026-08-02）
    mention_count: 1095              # 47 天內 BTC 相關文章數
    sentiment_score_overall: -0.0103 # 整段期間平均分數，接近中性偏負
    nonzero_ratio: 0.491             # 關鍵字命中率，見 Stage 2 方法論說明

  features:                          # 完整版見 Stage 2 — Feature Extraction/panews_sentiment.yaml
  knowledge:                         # 完整版見 Stage 3 — Knowledge Layer/panews_sentiment
  evidence_weight: 0.051             # ⚠️ 2026-08-02 拉齊（原本寫 0.755）：Stage 4 的 prior_weight 已改回
                                     # **ic 原值**填法（跟 demo `_resolve_prior_weight()`／active_address 一致），
                                     # 0.755 是 `proposed_normalization` 套公式後的值，那條公式 13 還沒拍板、
                                     # demo 也不套用，不能當卡片上的實際權重。
                                     # 尚未乘 context_modifier——Dynamic Modifier 這次示範沒有真的跑 LLM
                                     # ⚠️ 連帶影響 expected_rank：0.051 在純權重排序下落後段（跟 active_address 同一種
                                     # 情況），不是原本 0.755 會有的前段位置

  source_reliability:                # Stage 4 目前也還沒定（先註解掉），這裡跟著留白，不重複造一套新標準
  historical_support:                # 同上，待來源可信度分級表定案後一起補
  primary_horizon:                   # = Stage 3 Knowledge.primary_horizon（短期，且 regime-dependent，非單一數字）
  persistence:                       # Stage 3 沒有給單一 persistence 值（跟 category=sentiment 的「狀態依存」特性有關），這裡對應留空，不硬湊

  related_evidence:                  # = Stage 3 Knowledge 的 confirms／conflicts／independent
    confirms: [news]
    conflicts: []                    # Stage 3 標記「待驗證」，本卡先不下判斷，避免用低信賴度的方法論結論污染 Evidence Graph
    independent: []

  traceability: universal-api.panewslab.com/articles（分頁端點，非 RSS 即時流）

  # ⚠️ Confidence 標記（這輪新增，見 Stage 4 說明）：
  confidence: low   # 因為 Stage 4 的 ic 樣本數只有 44 天，這張卡片不該被當成
                     # 跟 active_address（confidence 較高，1807 天樣本）同等可信
                     # 的證據直接排序比較——這是這輪發現的、13 原本 Evidence Card
                     # 模板沒有的欄位，先加在這裡示範，要不要正式收進模板待 Ken 拍板
                     # ⚠️ 但「不該直接排序比較」這件事目前**不成立於排序層**：2026-08-02
                     # Ken 拍板一律照 evidence_weight 單鍵排序，不因來源或信賴度分組。
                     # 所以 confidence 現階段只是卡片上的顯示資訊，不影響名次——
                     # 要不要讓它真的介入排序，是拍板後才會改變的事

prioritization:
  # 2026-08-02 補：這塊原本整個沒有，是五張卡裡唯一沒宣告排序鍵的一張。
  # 程式改成讀卡片 .md 之後，沒宣告就等於「這張卡沒說自己照什麼排」，
  # 13 的排序拍板在它身上驗證不了（webapp/stage_specs.py 的自我檢查會直接報出來）。
  ranking_key: evidence_weight      # 13 拍板：純照 evidence_weight，跟其他四張一致
  ranking_transform: abs            # 2026-08-02 Ken 補充拍板：排序鍵不變（evidence_weight），
                                    # 但比大小時**取絕對值**。理由：ic 是相關係數，負值代表反向訊號
                                    # （factor 越高、後續報酬越低），那是有預測力的訊號不是弱訊號——
                                    # 實測 BTC funding_rate ic=-0.55 是五張卡裡強度最高的一個，照帶號值
                                    # 由大到小排會被排到最後一名，等於把最強的訊號當成最弱的。
                                    # ⚠️ 代價：名次只表達「訊號強度」，不表達方向。方向沒有消失——留在
                                    # evidence_weight 的正負號與卡片的 weight_direction 欄位，下游
                                    # （Stage 6 Graph／Stage 7-9 推理鏈）要判方向讀那兩格，不是讀名次。
                                    # 對 impact_level／domain_knowledge 型的卡片（值域 [0,1] 恆正）
                                    # 取絕對值不改變任何東西——那種卡本來就沒有「方向」這個概念
  evidence_coverage: null           # 定義未拍板，不生成
  expected_rank: 後段               # ic=0.051 高於 active_address（0.0041）、遠低於
                                    # cpi（0.8）／liquidation（0.3）。⚠️ 但這個名次是
                                    # 44 天樣本算出來的，上面 confidence: low 講的就是
                                    # 這件事——名次照排，可信度另外標，兩件事不互相干擾
```

### Stage 5 這輪新發現：Evidence Card 可能缺一個 `confidence` 欄位

13 的 Evidence Card 模板目前只有 `evidence_weight` 這個數字，沒有標注「這個數字本身有多可信」。前三個示範（active_address／cpi／liquidation）都不需要這個欄位——要嘛樣本夠、要嘛是 Domain Knowledge 判斷，本身不存在「數字算出來了但不可信」的中間狀態。panews_sentiment 是第一個踩到這個坑的：`evidence_weight=0.051`（2026-08-02 拉齊後的 ic 原值，原本寫 0.755）這個數字如果不附帶「只有 44 天樣本」的警告，直接跟其他 factor 的 `evidence_weight` 放在 Stage 5 排序裡比較，讀的人會以為它跟 active_address 的 0.0041 是同等可信的兩個測量值——實際上一個有 1807 天樣本、一個只有 44 天。（原本 0.755 的版本問題更嚴重：它會讓這張卡直接排到前段。）這個缺口已經在 Stage 4 提過一次，這裡從 Evidence Card 實際組裝的角度再確認一次：**不是這份文件自己能補的欄位，需要回報給 [[13流程圖迭代定案v2]] 正式收進 Evidence Card 模板**。

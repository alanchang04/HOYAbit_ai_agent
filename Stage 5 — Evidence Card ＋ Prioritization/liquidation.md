---
tags: [projects, hackathon, hoyabit, evidence-card, liquidation]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（示範：liquidation）；Stage 2 yaml 檔尾「降級處理」明講要在 Evidence Card 的 traceability／備註裡標「單次觀察窗，非統計訊號」——這份就是那條要求的落實位置
---

```yaml
# Stage 5 — Evidence Card ＋ Prioritization（示範：liquidation）
#
# ⚠️ 這張卡是三份裡**空格最多**的一張，但空的理由跟 cpi 完全相反：
#   cpi        → 資料齊全，是卡片 schema 的分型缺口（Statistical 欄位名套 Event Knowledge）
#   liquidation → schema 完全適用（它就是 Statistical Factor），是**資料源生不出內容**
#                 （Binance 查歷史清算單的 REST API 已停用，只剩即時監聽）
# 兩種空要分清楚：前者補一組欄位定義就能解決，後者換資料源才能解決。
#
# 這份還有一個特殊職責：[[Stage 2 — Feature Extraction/liquidation]] 檔尾的
# 「降級處理」條款明確寫了——這個 factor 拿不到穩定量化訊號時，要「在 Evidence Card 的
# traceability／備註裡明講『單次觀察窗，非統計訊號』」。Stage 5 就是那個指定的落實位置，
# 下面 traceability 那格不是隨手加的註解，是 Stage 2 交辦下來的必填內容。

evidence:
  evidence_id: LIQUIDATION_BTC      # 沿用 demo 的 {FACTOR}_{COIN} 格式（13 命名規則仍待定）
  category: statistical             # ← Stage 3 knowledge.category。分類本身沒錯（衍生品統計型），
                                    # 錯的是資料現實跟不上分類——這點跟 cpi 的「分類錯誤」是兩回事

  ####################
  # fact ← Stage 2（單次即時監聽窗口，不是歷史查詢）
  ####################
  fact:
    observed_count:                 # 這次監聽窗口內觀測到的清算單筆數（0 不代表沒發生，只代表這段窗口沒觀測到）
    observed_notional:              # 窗口內清算名目金額加總
    listen_seconds:                 # 監聽時長——⚠️ 這格取代了其他 factor 的 window，語意是「聽多久」不是「回看多久」
    # ⚠️ 這裡**沒有 percentile、沒有 trend**，而且是刻意不放這兩個 key，不是放 null：
    # 兩者都需要同一 factor 的歷史時間序列當母體／比較基準，這個 factor 結構性沒有。
    # 放 null 會讓下游以為「這次剛好沒算出來，下次可能有」；整格不存在才傳達得出
    # 「這個概念對這個 factor 不成立」。demo 的 _fact_summary() 也是照這個原則寫的

  features:                         # 完整欄位見 Stage 2 liquidation.yaml——注意該份 slope／roc／rolling_*／z_score 一整排都是 null，
                                    # 那是誠實標記，不是還沒填
  knowledge:                        # 完整內容見 Stage 3 liquidation.md（Time Property 來自文獻對現象的描述，非本專案回測值）

  ####################
  # evidence_weight ← Stage 4 的 final_weight（ic 結構性算不出，走 Domain Knowledge）
  ####################
  evidence_weight:                  # = prior_weight 0.3（Domain Knowledge，雙重理由：確認性訊號＋資料侷限）× context_modifier
    # 這格「有數字」這件事本身要講清楚：0.3 不是回測出來的，是 Stage 4 用兩個獨立理由
    # 論證出來的低值——① 文獻定位上 liquidation 是 funding_rate／open_interest 的
    # 確認性／落後訊號，資訊量大半已含在別的 factor 裡，重複計入等於雙重計分；
    # ② 資料只能單窗口監聽，樣本代表性弱。
    # ⚠️ ①這個理由在 Stage 5 這層有實際後果：它說的是「這張卡跟 funding_rate 那張
    # 高度重疊」。純照 evidence_weight 的排序**看不出重疊**——排序只回答誰重要，
    # 不回答誰跟誰是同一件事。這正是 13 說 Stage 6 Evidence Graph 存在的理由
    # （「排序只回答哪個訊號重要，Graph 回答這些訊號之間打不打架、是不是同一件事」），
    # 而這張卡是四張裡最需要那層的一張

  source_reliability: null          # Stage 4 未定案，跟著留白
  historical_support: null          # 同上
  primary_horizon:                  # ← Stage 3＝極短期（分鐘級，文獻對現象本身的描述，非本專案回測）
    # ⚠️ 這格會讓 Stage 4 的 time_horizon_match 幾乎必然往下調：Stage 1 判出來的 Horizon
    # 通常是天／週／月，跟分鐘級差好幾個尺度。這不是 bug，是這個 factor 對多數查詢
    # 本來就不該有高權重——但要注意這跟 prior_weight 的理由②（資料侷限）是**兩次獨立扣分**，
    # 同一個「資料只有即時窗口」的現實被扣了兩次。是否算重複計分，待拍板
  persistence: null                 # ← Stage 3 標「不適用」——事件型 factor，不是持續存在的狀態量，
                                    # 「持續多久」這個問題對它不成立。這裡照搬不適用，不自己補一個值

  ####################
  # related_evidence ← Stage 3（這是這張卡少數填得滿、而且填得有價值的區塊）
  ####################
  related_evidence:
    confirms: funding_rate ＋ open_interest   # ← Stage 3（文獻共識：三者合看才是有效前兆，單看任一個訊號都弱）
    conflicts: null                          # ← Stage 3 誠實列空（沒有已知穩定的矛盾對象）
    independent: cpi                         # ← Stage 3（外生新聞衝擊型 vs 內生擁擠倉位堆積型是兩種清算連鎖）
    # 這三格的可連接性比 active_address 那張好：funding_rate 跟 cpi 都是本專案真的有卡片的 factor，
    # 邊接得上；只有 open_interest 沒有對應卡片（同樣是「知識層 factor 名 → 本次 evidence_id」
    # 缺一層解析的問題，見 [[Stage 5 — Evidence Card ＋ Prioritization/active_address]] 文末）。
    # 附帶效果：cpi 那張卡自己的 related_evidence 三格全 null（Event Knowledge 沒這組欄位），
    # 它在圖上唯一的一條邊就是從這裡連過去的

  traceability:
    # ⚠️ 2026-08-02 格式訂正：這格原本寫成「traceability: <一行文字>」後面直接縮排接
    # note，那不是合法 YAML（scalar 後面不能再長出 mapping），程式讀這份檔會整份解析失敗。
    # 改成 source／note 兩個子欄位，內容一字未改。四張卡裡只有這張的 traceability
    # 有 note——因為 Stage 2 liquidation.yaml 的「降級處理」條款指定要寫在這裡。
    source: Binance USDⓈ-M `!forceOrder@arr` WebSocket 即時監聽
    note: |
      ⚠️ 單次觀察窗，非統計訊號。本卡的 fact 來自一次固定時長的即時監聽，不是歷史查詢
      也不是多次取樣的統計量；observed_count=0 只代表這段窗口沒觀測到，不代表市場沒有清算。
      Binance 查歷史清算單的 REST API（/fapi/v1/allForceOrders）已停用，這是資料源的
      結構性限制，不是本次執行的失敗。引用本卡做論證時，強度應等同「一則即時觀察」，
      不等同 funding_rate／active_address 那種有歷史母體的統計特徵。
      —— 這段是 [[Stage 2 — Feature Extraction/liquidation]] 檔尾「降級處理」條款指定要寫在
      Evidence Card 的內容，非本份自行添加

prioritization:
  ranking_key: evidence_weight      # 13 拍板：純照 evidence_weight
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
  expected_rank: 中後段             # prior 0.3 高於 active_address（ic≈0）、低於 cpi（0.8），
                                    # 再被 time_horizon_match 往下壓（分鐘級 vs 天/週查詢）
    # 排序位置在這張卡上特別容易誤導：它排在 active_address 前面，
    # 但 active_address 的低分是**回測測出來沒有預測力**，這張的分數是**沒得測、用理由給的**——
    # 「有理由的猜測」排在「測過的事實」前面。
    # ✅ 2026-08-02 Ken 拍板：**一律照 evidence_weight 排序**，不為這種情況另設規則。
    # 列為已知且接受的副作用，不是待處理項；理由差異看卡片內容（本檔 evidence_weight 註解）就讀得到
```

### 兩種「填不出來」，跟一個 Stage 5 目前接不住的東西

| | cpi | liquidation |
|---|---|---|
| 空格成因 | 卡片 schema 是照 Statistical Factor 寫的，Event Knowledge 沒有那些欄位 | 資料源生不出算法要的輸入（無歷史序列） |
| 解法 | 補一組 Event Factor 的欄位對應／關係欄位定義 | 換資料源（例如付費的 Coinglass 歷史 API） |
| 現在怎麼處理 | 能對應的標「→ 對應欄位」，不能對應的（related_evidence）留 null | 概念不成立的 key 直接不放（percentile／trend），有結構性說明的寫進 traceability.note |

Stage 5 目前接不住的那件事：**這張卡跟 funding_rate 那張高度重疊**（Stage 4 給 0.3 的第一個理由就是這個）。純照 `evidence_weight` 排序完全表達不出重疊——排序是一維的，只排得出誰高誰低，排不出「這兩張其實在講同一件事」。13 把這個責任明確劃給 Stage 6 Evidence Graph，設計上沒問題；但要留意目前這條線還沒活起來（13「待處理 1」：`related_evidence` 沒有任何 collector 真的去填，圖永遠是空的）。也就是說**在 Graph 真的有資料之前，liquidation 跟 funding_rate 會以兩張獨立卡片的樣子進到 Stage 7-9 推理鏈，被當成兩份獨立佐證**——這是目前所有示範卡片裡風險最具體的一張，因為它是唯一一張明確知道自己跟誰重疊的卡。

---
tags: [projects, hackathon, hoyabit, evidence-card, active-address]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（示範：active_address）；三個新示範裡唯一四格（Fact／Knowledge／Weight／Relationship）都填得滿的一張卡，也因此是唯一能拿來檢查「卡片格式本身有沒有問題」的基準
---

```yaml
# Stage 5 — Evidence Card ＋ Prioritization（示範：active_address）
#
# Stage 5 是**組裝層，不重新運算**（13 拍板）：三個來源各自已經做完自己的事，
# 這層只負責把它們包成同一種格式，再排序。所以這份文件不會出現任何
# 「這裡再算一次」的欄位，每一格都標得出它是從哪一層搬過來的：
#   fact       ← [[Stage 2 — Feature Extraction/active_address]]（yaml）
#   knowledge  ← [[Stage 3 — Knowledge Layer/active_address]]（md）
#   weight     ← [[Stage 4 — Dynamic Evidence Weight Engine/active_address]]（md）
#
# 這張卡的定位：三份新示範裡**唯一每一格都填得出實質內容**的一張——cpi 是
# Event Factor（schema 對不上，見那份）、liquidation 有結構性資料缺口，只有
# active_address 是「Statistical Factor＋歷史序列完整＋ic 真的算得出來」的
# 標準案例。也正因為它標準，它暴露的問題才是**卡片格式本身的問題**，不是
# 個別 factor 的資料現實問題（見文末兩點）。

evidence:
  evidence_id: ACTIVE_ADDRESS_BTC   # 13 的命名規則仍標「待定」（13 正文暫用 DER_FUNDING_001 這種示範編號）。
                                    # 這裡沿用 demo 實作的 {FACTOR}_{COIN} 格式，先求可對照、不自己發明一套沒人拍板的正式編號
  category: statistical             # ← Stage 3 knowledge.category。13 拍板：2026-08-02 起分類以 13 為準，不再對照 09 的產業別

  ####################
  # fact ← Stage 2（原始事實，不做任何解讀）
  ####################
  fact:
    current_value:                  # series[-1]，blockchain.info n-unique-addresses 最新一筆
    percentile:                     # percentile_rank(series, current_value)，母體＝這次抓取的 window
    trend:                          # 由 slope／slope_7d 判讀出來的方向敘述
    # ⚠️ 這三格的母體都是「LLM 依 Horizon 決定的那個 window」，不是固定回看區間——
    # 同一天、不同 Horizon 的查詢會給出不同的 percentile，這是 Stage 2 的設計（window 由 LLM 定），
    # 不是資料不穩定。卡片上顯示 percentile 時要一起顯示 window，否則讀的人會誤以為是絕對分位

  features:                         # 完整欄位（slope/roc/rolling_*/z_score/quality）見 Stage 2 active_address.yaml，卡片不重抄
  knowledge:                        # 完整內容見 Stage 3 active_address.md，卡片不重抄

  ####################
  # evidence_weight ← Stage 4 的 final_weight
  ####################
  evidence_weight:                  # = prior_weight（ic 導出，ic 隨 Horizon 重算）× context_modifier（LLM 給，[0.5, 2.0]）
    # ⚠️ 這個 factor 的 prior_weight 趨近 0（Stage 4 示範跑：horizon=14 → ic=0.0041），
    # 所以不論 context_modifier 給到上限 2.0，evidence_weight 都會是很小的數——
    # 這張卡在排序時**結構性地會排在後段**。這是這個 factor 目前的真實狀態，不是排序壞掉。
    # 附帶結論：Stage 5 排序若真的照 evidence_weight 排，active_address 幾乎不可能進前段，
    # 這正是「排序不刪除、只排序」（13 拍板）這條規則的價值——它仍然在卡片清單裡，
    # 下游要不要看得到它，是 Stage 6 Graph／Stage 7-9 推理鏈的事，不是這層先幫忙砍掉

  source_reliability: null          # Stage 4 尚未定案（該份仍註解狀態），這裡跟著留白，不重複造一套新標準
  historical_support: null          # 同上，待「references 怎麼轉成分數」定案後一起補
  primary_horizon:                  # ← Stage 3 knowledge.primary_horizon＝中長期（結構性網路使用趨勢）
  persistence:                      # ← Stage 3 knowledge.persistence＝中（ETF 後鏈上/價格脫鉤，訊號延續性比 2021 前弱）

  ####################
  # related_evidence ← Stage 3 的 confirms／conflicts／independent（Stage 6 Evidence Graph 的邊）
  ####################
  related_evidence:
    confirms: hash-rate             # ← Stage 3
    conflicts: price                # ← Stage 3
    independent: funding_rate       # ← Stage 3
    # ⚠️ 三格裡只有 funding_rate 是本專案真的有卡片的 factor（demo 的 KNOWN_FACTORS 五個：
    # funding_rate／active_address／cpi／liquidation／panews_sentiment）。
    # hash-rate 跟 price 都**沒有對應的 Evidence Card**，
    # Stage 6 畫圖時這兩條邊會指向不存在的節點——這是 13「待處理 1」
    # （related_evidence 目前沒有任何 collector 真的去填）的另一半：不只是「沒人填」，
    # 是**填了也未必連得上**。Stage 3 寫 confirms 時是照文獻寫「這個 factor 通常跟誰一起看」，
    # 那是知識層的正確寫法；Evidence Graph 需要的卻是「本次執行有哪幾張卡、彼此什麼關係」。
    # 兩者不是同一件事，中間缺一層對照（把知識層的 factor 名字解析成本次的 evidence_id）。
    # 這層目前不存在，先記錄，這份不擅自發明

  traceability: blockchain.info Charts API `n-unique-addresses`（免key，每日一筆）
    # ⚠️ 僅涵蓋 BTC UTXO 鏈（Stage 3 supported_assets: [BTC]）。查 ETH/SOL/BNB/XRP 時，
    # 這張卡在資料上根本不成立——但 Stage 5 目前**沒有「因不支援而不產卡」的機制**，
    # 13 只講了排序不刪除，沒講「不該存在的卡」怎麼處理。待拍板，見文末

prioritization:
  ranking_key: evidence_weight      # 13 拍板：純照 evidence_weight 由大到小，不參雜其他輸入
  evidence_coverage: null           # 定義 13 仍未拍板 → 不產生這個欄位假裝有定案（跟 Stage 4 的 source_reliability 同一種留白原則）
  expected_rank: 後段               # 理由見上方 evidence_weight 註解，不是預先安排的位置，是 ic≈0 的必然結果
    # ✅ 2026-08-02 Ken 拍板：**一律照 evidence_weight 排序**——不因這張卡的低分是
    # 「回測測出來的事實」、而 cpi/liquidation 的分數是「分級表／理由給的」就分組處理。
    # 單一排序鍵是這層的設計，來源差異在 Stage 4 各 factor 文件裡交代，不在排序層重複處理
```

### 這份的特殊之處

三份新示範裡，這是**唯一一張沒有「因為資料現實所以填不出來」的格子的卡**——Fact 有完整歷史序列、Knowledge 欄位全滿、Weight 有真的算出來的 `ic`。也因為它每格都填得滿，它跑出來的兩個問題就不能推給 factor 本身，是 **Evidence Card 這個格式本身缺的東西**：

1. **`related_evidence` 指向不存在的節點**：Stage 3 的 `confirms: hash-rate`／`conflicts: price` 是知識層的正確答案（文獻上這個 factor 就是跟這兩個一起看），但本專案目前只有五張卡（demo 的 `KNOWN_FACTORS`：funding_rate／active_address／cpi／liquidation／panews_sentiment），hash-rate／price 都不在裡面。Stage 6 Evidence Graph 拿這欄位當邊，就會畫出指向空節點的邊。缺的是一層「知識層 factor 名 → 本次執行 evidence_id」的解析，13 的「待處理 1」只記到「沒人填這個欄位」，這裡補上後半：**填了也未必連得上**。
2. **卡片不成立時沒有處理機制**：`supported_assets: [BTC]`，查 ETH 時這張卡在資料上不成立。13 對 Stage 5 只拍板了「不刪除，只排序」——那是針對「算不出權重」的卡，不是針對「這個 factor 對這個幣種根本不適用」的卡。兩者性質不同，前者是資訊不足、後者是不該存在。要不要多一個「applicable: false」的狀態，待 Ken 拍板，這份不擅自發明。

排序上，這張卡因為 `ic≈0` 會結構性排後段（Stage 4 那份已經說明 `prior_weight` 趨近 0 時 `context_modifier` 救不回來）。這反而是驗證「純照 evidence_weight 排序」這個拍板的好案例：**排序把它排到後面，但沒有把它丟掉**——它仍然是一張完整、可追溯的卡，只是不該在報告裡被當成主要論據。

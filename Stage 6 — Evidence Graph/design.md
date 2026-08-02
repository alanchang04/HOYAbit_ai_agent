---
tags: [projects, hackathon, hoyabit, evidence-graph]
source: [[13流程圖迭代定案v2]] Stage 6 — Evidence Graph（原 Stage 7）；這份是這輪第一次落地成可執行設計，不是重複貼 13 正文
---

# Stage 6 — Evidence Graph 設計

跟 Stage 2/3/4/5 不同，這一層**不是逐 factor 各寫一份**——Graph 本質是「這批卡片彼此的關係」，只有在所有卡片都組好之後才有得畫，所以本資料夾只有一份設計文件，不是四五份 factor 檔案。

## 輸入

Stage 5 排序後的 Evidence Cards（`/api/stage5` 的 `evidence_cards`），每張卡片的 `related_evidence.confirms／conflicts／independent` 是這一層唯一的資料來源——不重新判斷任何關係，只是把已經寫在 Stage 3 Knowledge（透過 Stage 5 傳過來）的關係畫成圖。

## 建圖規則

```
對每張卡片 C：
  對 C.related_evidence.confirms 裡列出的每個 factor 名 F：
    若 F 在這批卡片裡有對應卡片 → 畫邊 C --supports--> F
    若 F 沒有對應卡片 → 記進 referenced_but_no_card，不畫邊、不假裝有這個節點
  conflicts 同理，畫 --conflicts--> 邊
  independent 同理，畫 --independent--> 邊（弱關係，前端可選擇不畫或畫成虛線）
```

## 這輪發現的三個已知缺口（2026-08-02，記在 13 正文，這裡具體化）

1. **`related_evidence` 指向沒有對應卡片的 factor**：`funding_rate` 的 Stage 3 Knowledge 寫 `confirms: open_interest`，但這批 Stage 5 卡片裡沒有 `open_interest` 這張卡。同樣情況：`active_address` 的 `confirms: hash-rate`。這些關係**是真的**（Stage 3 Knowledge 裡有依據），只是「這次查詢沒有把那個 factor 也一起分析」，跟「這個關係不存在」是兩回事——所以不能略過不提，也不能編一個假節點。畫圖時分兩欄：`edges`（真的有兩張卡可以連的）跟 `referenced_but_no_card`（有關係但這次批次沒有對應卡片），讓看的人知道「圖不完整不是資料錯，是這次只分析了這幾個 factor」。
   ⚠️ 2026-08-02 更新：`active_address` 的 `conflicts: price` **不再是這個缺口的範例**——新增 `price` 卡片之後這條關係已經有兩端可以連，變成一條真的 `edges`，不會再出現在 `referenced_but_no_card` 裡（下面第 47 行的範例 JSON 已同步更新）。`open_interest`／`hash-rate` 目前還沒有對應卡片，缺口仍然存在。

2. **Event Factor（cpi）永遠不會主動連出任何邊**：Stage 3 的 Event Knowledge schema（`usually_affects`／`related_events`）跟 Statistical／Sentiment Knowledge 的 `confirms`／`conflicts`／`independent` 不是同一組欄位名，Stage 5 組裝 `related_evidence` 時三格對 cpi 誠實留 null（見 `Stage 5 — Evidence Card ＋ Prioritization/cpi.md`）。這代表 cpi**結構性不會是任何邊的起點**——`usually_affects: FOMC利率決議預期／DXY／美債殖利率` 這些關係是有記錄的，只是欄位名跟 Graph 讀的 key 對不上，讀不到。⚠️ 但這不代表 cpi 一定是孤立節點：實測發現 `liquidation` 的 `independent` 欄位反過來指到 `cpi`（見 liquidation.md），所以 cpi 有可能因為**別的卡片指向它**而出現在圖上，只是它自己永遠不會發出邊。這裡先誠實維持這個不對稱現狀，**不**臨時把 `usually_affects` 塞進 `confirms` 湊出對稱的邊——那是繞過問題，不是解決問題，正確做法是回頭讓 13 的 Event Knowledge schema 也定義對稱的 Graph 用關係欄位，這輪不動。

3. **`DEBATE_GRAPH_RULE` 檢查不到孤立節點**：HOYAbit_ai_agent `1.2c` 分支已經把 Evidence Graph 接進辯論層 prompt（`DEBATE_GRAPH_RULE`：看到 supports 不能疊加信心、看到 conflicts 不能略過），但這條規則的前提是「圖裡有邊」——cpi 這種孤立節點不會觸發任何規則，等於這條防呆對 Event Factor 沒有保護力，這點跟缺口 2 是同一個根因，一併記錄。

## 輸出格式（給 `/api/stage6` 用）

```json
{
  "nodes": [
    {"evidence_id": "FUNDING_RATE_BTC", "factor": "funding_rate", "category": "statistical"},
    {"evidence_id": "CPI_BTC", "factor": "cpi", "category": "event", "isolated": true}
  ],
  "edges": [
    {"from": "FUNDING_RATE_BTC", "to": "ACTIVE_ADDRESS_BTC", "relation": "independent"},
    {"from": "ACTIVE_ADDRESS_BTC", "to": "PRICE_BTC", "relation": "conflicts"}
  ],
  "referenced_but_no_card": [
    {"from": "FUNDING_RATE_BTC", "relation": "confirms", "referenced_factor": "open_interest"},
    {"from": "ACTIVE_ADDRESS_BTC", "relation": "confirms", "referenced_factor": "hash-rate"}
  ]
}
```

`isolated: true` 只標在圖上確實沒有任何邊的節點（目前實測下 cpi 必然如此，其他 factor 視當次查詢資料而定）。

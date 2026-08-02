---
tags: [projects, hackathon, hoyabit, evidence-graph, coin-template, btc]
source: [[13流程圖迭代定案v2]] Stage 6 — Evidence Graph；幣種模板（BTC）v2，2026-08-02
summary: BTC 9 張卡推出來的圖——9 節點／13~14 條邊／7~8 條指向空節點
---

# Stage 6 — Evidence Graph 幣種模板（BTC）

⚠️ 這張圖是**照 Stage 5 各卡片 `related_evidence` 欄位推導**出來的，
不是跑 `/api/stage6` 實測的輸出。建圖規則沿用同資料夾 `design.md`。

```yaml
coin: BTC
nodes: 9
edges: 13~14
referenced_but_no_card: 7~8

nodes_detail:
  - {evidence_id: FUNDING_RATE_BTC,      factor: funding_rate,      category: statistical}
  - {evidence_id: PRICE_BTC,             factor: price,             category: statistical}
  - {evidence_id: CPI_BTC,               factor: cpi,               category: event}
  - {evidence_id: PANEWS_SENTIMENT_BTC,  factor: panews_sentiment,  category: sentiment, isolated: true}
  - {evidence_id: ETF_BTC,               factor: etf,               category: statistical}
  - {evidence_id: ACTIVE_ADDRESS_BTC,    factor: active_address,    category: statistical}
  - {evidence_id: MOMENTUM_BTC,          factor: momentum,          category: statistical}   # 取代 liquidation
  - {evidence_id: ORDERBOOK_DEPTH_BTC,   factor: orderbook_depth,   category: snapshot}
  - {evidence_id: HASH_RATE_BTC,         factor: hash_rate,         category: statistical}   # ⭐ 新增

edges_detail:
  - {from: ACTIVE_ADDRESS_BTC,  to: PRICE_BTC,            relation: conflicts}
  - {from: ACTIVE_ADDRESS_BTC,  to: FUNDING_RATE_BTC,     relation: independent}
  - {from: ACTIVE_ADDRESS_BTC,  to: HASH_RATE_BTC,        relation: confirms}      # ⚠️ 條件式，見下方②
  - {from: HASH_RATE_BTC,       to: ACTIVE_ADDRESS_BTC,   relation: confirms}      # ⭐ 與上一條構成本專案第一組雙向 confirms
  - {from: HASH_RATE_BTC,       to: PRICE_BTC,            relation: conflicts}     # ⭐
  - {from: HASH_RATE_BTC,       to: CPI_BTC,              relation: independent}   # ⭐
  - {from: PRICE_BTC,           to: ACTIVE_ADDRESS_BTC,   relation: conflicts}
  - {from: PRICE_BTC,           to: CPI_BTC,              relation: independent}
  - {from: ETF_BTC,             to: PRICE_BTC,            relation: confirms}
  - {from: ETF_BTC,             to: ACTIVE_ADDRESS_BTC,   relation: conflicts}
  - {from: MOMENTUM_BTC,        to: ACTIVE_ADDRESS_BTC,   relation: conflicts}     # momentum 取代 liquidation 後的新邊
  - {from: MOMENTUM_BTC,        to: CPI_BTC,              relation: independent}
  - {from: ORDERBOOK_DEPTH_BTC, to: FUNDING_RATE_BTC,     relation: confirms}
  - {from: ORDERBOOK_DEPTH_BTC, to: CPI_BTC,              relation: independent}

referenced_but_no_card_detail:
  - {from: FUNDING_RATE_BTC,      relation: confirms,    referenced_factor: open_interest}
  - {from: FUNDING_RATE_BTC,      relation: conflicts,   referenced_factor: long_short_ratio}
  - {from: FUNDING_RATE_BTC,      relation: independent, referenced_factor: vol-compression}
  - {from: PRICE_BTC,             relation: confirms,    referenced_factor: volume_change_24h}
  - {from: PANEWS_SENTIMENT_BTC,  relation: confirms,    referenced_factor: news}
  - {from: ORDERBOOK_DEPTH_BTC,   relation: confirms,    referenced_factor: open_interest}
  - {from: MOMENTUM_BTC,          relation: confirms,    referenced_factor: volume_change_24h}
  # ⚠️ ACTIVE_ADDRESS_BTC --confirms--> hash-rate 是否留在這裡，取決於名稱解析，見下方②
```

## ⭐ 這輪的兩個變化

**① 補 `HASH_RATE_BTC`：多 3~4 條邊。** 3 條新出邊（三格全部連得上），
第 4 條是 `ACTIVE_ADDRESS_BTC --confirms--> hash_rate` 有沒有從 `referenced_but_no_card`
轉正——⚠️ 這條**取決於名稱解析**，見下方②。

**② `liquidation` → `momentum`（另一條線 2026-08-02 的改動）：淨少 1 條邊。**
- 失去 2 條：`LIQUIDATION → FUNDING_RATE (confirms)`、`LIQUIDATION → CPI (independent)`
- 得到 2 條：`MOMENTUM → ACTIVE_ADDRESS (conflicts)`、`MOMENTUM → CPI (independent)`
- ✅ **順手修掉一條斷邊**：`ETF_BTC` 原本的 `independent: liquidation` 會指向不存在的
  節點，已於同日把 Stage 3／Stage 5 兩份 `etf.md` 都訂正成 `independent: null`。
  ⚠️ **刻意不改指 momentum**——momentum 是 RSI14、純價格函數，而 Stage 3 `etf.md`
  自己引的 SSRN 6592830 記載 ETF 流量與價格報酬是**雙向回饋迴圈**，宣稱兩者獨立
  會跟自己引的文獻矛盾。（可能的替代人選是 hash_rate，但那是新的關係宣稱，沒查證不填。）

合計 **8 節點／11 邊** → **9 節點／13~14 邊**，`referenced_but_no_card` 7~8 條，
區間的來源是②的名稱解析問題。

## ⚠️② 名稱對不起來：`hash-rate` vs `hash_rate`（2026-08-02 發現，**待拍板**）

`Stage 3/active_address.md` 的關係欄位寫的是 **`confirms: hash-rate（網路算力）`**
——連字號，而且帶中文後綴。新 factor 的 `factor_id` 是 **`hash_rate`**（底線）。

**純字串比對接不起來。** 所以「補了 hash_rate 卡片就自動修好那條斷邊」這個說法
**只在有名稱解析層的前提下成立**——而那層正是 13 待處理清單第 1 條列的已知缺口
（「缺一層『知識層 factor 名 → 本次執行 evidence_id』的解析」）。

實際的邊數因此是：
- **13 條**（純字串比對，那條仍留在 `referenced_but_no_card`，共 8 條）
- **14 條**（有名稱解析／正規化，那條轉正，`referenced_but_no_card` 7 條）

兩條解法，都不在幣種模板的範圍，**我沒有動**：
- (a) 把 `active_address.md` 的 `hash-rate（網路算力）` 改寫成 `hash_rate` —— 一行的事，
  但等於要求所有 Knowledge 的關係欄位都用 factor_id 當受控字彙
- (b) 在建圖時做正規化（去中文後綴、連字號↔底線互通）—— 不用改既有文件，
  但那是 Stage 6 建圖規則的變更

⚠️ 這也不只影響 hash_rate：`vol-compression`（funding_rate 的 independent）同樣是
連字號寫法，`volume_change_24h`／`long_short_ratio` 則是底線。整批關係欄位的
命名一致性本來就沒有規範過，這次只是第一次真的咬到人。

## ⚠️ 仍未解的兩件事

**① 孤立節點是 `panews_sentiment`。** `design.md` 寫「實測下 cpi 必然孤立」在九張卡下
不成立——cpi 有 4 條入邊（price／momentum／orderbook_depth／hash_rate）。真正沒有任何
邊的是 panews_sentiment，`DEBATE_GRAPH_RULE` 對它完全沒有保護力。

**② `open_interest` 仍是最該補的缺卡**（funding_rate／orderbook_depth 都 confirms 它）。
⚠️ 但它是衍生品資料、五幣共用，不屬於這輪「一幣一個幣種專屬 factor」的範圍。

**③ ~~`ETF_BTC` 指向已移除的 `liquidation`~~ → 2026-08-02 已修**：Stage 3 與 Stage 5
兩份 `etf.md` 都改成 `independent: null`，理由寫在檔案裡（不改指 momentum 的原因見上方②）。

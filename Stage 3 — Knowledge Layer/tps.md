---
tags: [projects, hackathon, hoyabit, knowledge-layer, tps]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer / Snapshot Knowledge（tps）；2026-08-02 新增，SOL 的幣種專屬 factor
summary: SOL 網路吞吐量的 Knowledge Layer——Snapshot 型（比照 orderbook_depth，不放 primary_horizon/persistence）；12 小時是資料源硬上限
---

```yaml
# Stage 3 — Knowledge Layer / Snapshot Knowledge（tps）
#
# 比照 orderbook_depth 用 category: snapshot：**直接不放** primary_horizon／
# persistence 兩個 key——不是資料缺失，是這兩個概念對「當下狀態量」本身不成立。

knowledge:
  factor_id: tps
  factor_name: Solana 網路吞吐量（Transactions Per Second）
  category: snapshot

  ####################
  # Time Property（Snapshot 型用 validity_window，不用 primary_horizon）
  ####################
  validity_window: 60 秒        # 單窗取樣週期；超過就是下一個窗的狀態了
  max_lookback: 12 小時         # ⚠️ 資料源硬上限（RPC limit=720 × 60 秒），
                                # 2026-08-02 實測超過 720 直接回 -32602 錯誤

  ####################
  # Scope
  ####################
  supported_assets: [SOL]
    # 概念上其他鏈也有吞吐量，但四幣各自的量測口徑完全不同
    # （BTC 看 24h 交易筆數、ETH/BNB 看區塊 gas 使用率、XRP 看單帳本 tx_count），
    # 不是同一把尺、不能互相比較，所以這份只涵蓋 SOL

  ####################
  # Data Dependency
  ####################
  data_source: Solana 公開 RPC `getRecentPerformanceSamples`（免 key）
  known_limitation: |
    ⚠️ 這是本專案**歷史涵蓋最短**的 factor，比 etf（9-10 個交易日）還短：
    只有 12 小時，且實測拿到的是 421 窗（約 7 小時）而非上限 720。
    直接後果：
      ① 算不出 ic（沒有跨日序列可以跟 forward_return 對齊）→ Stage 4 走 domain_knowledge
      ② percentile／z_score 的母體只有數小時，跟 hash_rate/gas 的「相對五年」
         不是同一種百分位，卡片上必須標明母體範圍
      ③ 沒有免 key 的長歷史替代來源（pipeline/待辦筆記 已記錄 SOL/BNB/XRP
         鏈上歷史序列全部卡住，Dune Analytics 等替代方案都要付費或註冊）

  ####################
  # Relationship（靜態知識）
  ####################
  Relationship:
    confirms: null           # ⚠️ 誠實列空：吞吐量跟本專案其他 factor 沒有已知穩定的
                             # 「應該同向」關係。硬掰一個（例如「TPS 高＝生態熱＝價格強」）
                             # 沒有依據，且會在 Evidence Graph 上製造假的確認邊
    conflicts: null
    independent: cpi         # ✅ 有卡片可連——網路吞吐量與總經事件明確不在同一因果鏈

  ####################
  # References
  ####################
  references:
    industry:
      - "Solana Docs - getRecentPerformanceSamples: https://solana.com/docs/rpc/http/getrecentperformancesamples"
    academic: null           # ⚠️ 誠實留 null，不填未查證的出處

  version: 1.0
  last_updated: 2026-08-02
```

## ⚠️ 這份的定位要講清楚

Ken 拍板「一幣一個，抓不到就算了」，SOL 這個屬於**抓得到但資訊量低**的那一類。
誠實的評估：

- ✅ 端點可用、免 key、實測 HTTP 200、拿得到真數字（最新窗 3040.4 TPS）
- ❌ 12 小時窗口 → 算不出 ic、排序只能靠人工給值
- ❌ 日常 TPS 數字本身幾乎不帶預測資訊（平穩的 3000 TPS 說明不了任何事）
- ⚪ 真正的價值在**尾部事件**：SOL 的特有題材是「網路穩定性／宕機」，
  12 小時窗口足夠偵測「當下是不是不正常」，這是它唯一能貢獻的東西

所以這張卡在報告裡的正確用法是**條件式的**：平常不講，數字異常時才是證據。
這跟其他 factor「每次都給一個值進排序」的用法不同，但 13 沒有為這種
「條件式證據」定義過狀態，目前只能照一般卡片處理，先記錄這個落差。

---
tags: [projects, hackathon, hoyabit, knowledge-layer, gas]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer / Statistical Knowledge（gas）；2026-08-02 新增，ETH 的幣種專屬 factor
summary: ETH gas 的 Knowledge Layer——鏈上需求熱度的直接代理，短中期尺度；⚠️ 序列跨越 EIP-1559 與 L2 分流，前後段非同分布
---

```yaml
# Stage 3 — Knowledge Layer / Statistical Knowledge（gas）

knowledge:
  factor_id: gas
  factor_name: Ethereum Gas Price（鏈上需求熱度）
  category: statistical

  ####################
  # Time Property
  ####################
  primary_horizon:
    scale: 短中期
    applicable_days: [1, 60]     # ⚠️ 由下方 rationale 人工換算，**非回測值**
    rationale: |
      gas 價格是**當下鏈上區塊空間的競價結果**——需求一來（NFT 鑄造潮、DeFi
      清算潮、行情劇烈波動時的鏈上操作暴增）就立刻反映，需求退去也立刻回落。
      尖峰通常持續數小時到數日，不像算力那樣有數月的資本支出慣性。
      上限取 60 天是因為「鏈上活躍度的一個週期」大致在這個量級，再往上拉
      就會跨進結構性改變（見下方 known_limitation），不再是同一件事。

  persistence: 中低——單次尖峰數小時到數日就衰減；但「鏈上整體活躍水位」這個
               背景狀態可以持續數週，兩個時間尺度混在同一個數字裡，讀的時候要分開

  update_frequency: 每日一筆（etherscan CSV 匯出端點日頻）

  ####################
  # Scope
  ####################
  supported_assets: [ETH]
    # ⚠️ BSC 也有 gas 概念、EVM RPC 也拿得到即時值，但**沒有免 key 的歷史序列**——
    # 2026-08-02 重新實測 Etherscan V2 `chainid=56` 仍回
    # "Free API access is not supported for this chain"，跟 pipeline/流程紀錄.md
    # 2026-07-20 的記載一致。所以 gas 對 BNB 只能是 snapshot，不是同一張卡，
    # 這份的 supported_assets 只列 ETH

  ####################
  # Data Dependency
  ####################
  data_source: etherscan.io/chart/gasprice CSV 匯出端點（免 key）
  known_limitation: |
    ⚠️ 序列橫跨兩次結構性改變，前後段不是同一個分布：
      ① EIP-1559（2021-08）改變了手續費機制本身
      ② L2（Arbitrum／Optimism／Base 等）大規模分流，把大量交易帶離主網
    實測最新值 0.598 Gwei，相對 2021 年熱潮期低了兩個數量級。
    後果：拿全段 4021 筆算 percentile，現值會永遠落在極低百分位，那反映的是
    「結構變了」不是「現在很冷」。這是 Stage 2 特別提醒「window 不要無腦拉滿」
    的原因，也是這個 factor 跟 hash_rate 最大的差別（算力沒有這種機制性斷點）。

  ####################
  # Relationship（靜態知識）
  ####################
  Relationship:
    confirms: price          # ✅ 兩端都有卡片——鏈上需求熱度與價格常同步（行情動起來，
                             # 鏈上操作跟著暴增），是產業共識層級的關係
    conflicts: null          # 誠實列空：沒有已知穩定的矛盾對象
    independent: cpi         # 總經事件與鏈上區塊空間競價不在同一個因果鏈上

  ####################
  # References
  ####################
  references:
    industry:
      - "Etherscan - Ethereum Average Gas Price Chart: https://etherscan.io/chart/gasprice"
    academic: null
      # ⚠️ 誠實留 null：本份沒有查證過可引用的學術出處，不填一個沒查證的湊格式

  version: 1.0
  last_updated: 2026-08-02
```

## 為什麼 ETH 選這個

ETH 拿掉 `etf`／`active_address` 之後（資料源都只涵蓋 BTC），剩下的 6 張卡裡**沒有
一張是 ETH 專屬的鏈上證據**——funding_rate／price／momentum／orderbook_depth 都是
交易所資料、五幣通用，cpi 是總經、panews 是輿情。gas 是唯一補得回「這是 ETH 這條鏈
自己發生的事」的 factor，而且資料現成（`pipeline/fetch_onchain_history.py` 已在抓）。

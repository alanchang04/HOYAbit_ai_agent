---
tags: [projects, hackathon, hoyabit, knowledge-layer, bnb-burn]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer / Event Knowledge（bnb_burn）；2026-08-02 新增，BNB 的幣種專屬 factor
summary: BNB 季度銷毀的 Knowledge Layer——本專案第二個 Event 型 factor；⚠️ 跟 cpi 最大的差別是它「事前可預期」，效率市場下應已被 price in
---

```yaml
# Stage 3 — Knowledge Layer / Event Knowledge（bnb_burn）
#
# 比照 cpi.md 的 Event Knowledge 骨架（沒有 primary_horizon，改在頂層放 applicable_days）。

knowledge:
  factor_id: bnb_burn
  factor_name: BNB 季度銷毀（Quarterly Auto-Burn）
  category: event

  ####################
  # Event 屬性
  ####################
  event_class: 供給側週期性事件
  impact_level: Medium          # ⚠️ 刻意**不**給 Very High（cpi 才是 Very High），
                                # 理由見下方 predictability_caveat——這是本份最重要的判斷

  frequency: 季頻（一年 4 次）
  applicable_days: [0, 90]      # ⚠️ 兩段不連續尺度的聯集，寫法比照 cpi：
                                #   reaction_window   [0, 3]  公告當下的價格反應
                                #   expected_duration [0, 90] 供給效果延續到下一季銷毀
                                # 落在區間內不代表各點強度相同

  predictability_caveat: |
    ⚠️⚠️ **這是它跟 cpi 最本質的差別，也是 impact_level 只給 Medium 的原因**：

    cpi 的數字在公布前沒有人知道，「意外」本身就是衝擊來源，所以 Very High。
    BNB 銷毀是**事前公告、機制透明、時程固定**的——Auto-Burn 公式公開，
    任何人都能事先估算大致銷毀量與時間。在效率市場假設下，可預期的供給變動
    應該早就反映在價格裡，真正的訊號只剩「實際銷毀量 vs 市場預期」的差額，
    而**本專案沒有市場預期的資料源**，算不出這個差額。

    所以這個 factor 誠實的定位是：**敘事證據，不是預測訊號**。它能讓報告講出
    「BNB 有制度性通縮、上一季燒了 156 萬枚」這種具體事實，但不該被當成
    「所以接下來會漲」的依據。impact_level 給 Medium 而不是 Very High，
    就是把這個保留寫進數字裡。

  ####################
  # Scope
  ####################
  supported_assets: [BNB]       # 其他四幣沒有對應的制度性定期銷毀機制
                                # （XRP 有交易費銷毀但那是連續的、不是事件，見 xrp_supply_burn）

  ####################
  # Data Dependency
  ####################
  data_source: BNB Chain Blog 文章內文（HTML 解析，免 key）
  known_limitation: |
    ⚠️ 2026-08-02 實測只回溯得到最近兩期（35th／34th）。30th／25th 回 HTTP 200
    但是空殼頁（SPA 對不存在的路徑不回 404），必須用「內文有沒有 Auto-Burn 字樣」
    判斷成功，不能用 status code。
    兩條替代路都已排除：bnbburn.info 是 JS 渲染 SPA 靜態抓不到；
    BscScan（Etherscan V2 chainid=56）免費方案仍被擋。

  ####################
  # Relationship
  ####################
  # ⚠️ Event Knowledge 沒有 confirms／conflicts／independent 三分法（13 已知缺口 2），
  # 這裡比照 cpi 誠實不硬塞。後果：這張卡在 Evidence Graph 上**不會發出任何邊**，
  # 而且目前沒有任何一張卡指向它 → 它會是 BNB 圖上的第二個孤立節點
  # （第一個是 panews_sentiment）。這件事已寫進 Stage 6 BNB 幣種模板。
  usually_affects:
    - BNB 流通供給量（直接、機械性的減少）
  related_events:
    - BNB Chain 生態升級公告（常在同一批官方發布裡出現）

  ####################
  # References
  ####################
  references:
    industry:
      - "BNB Chain Blog - 35th BNB Burn: https://www.bnbchain.org/en/blog/35th-bnb-burn"
    academic: null              # ⚠️ 誠實留 null，不填未查證的出處

  version: 1.0
  last_updated: 2026-08-02
```

## 為什麼 BNB 選這個

BNB 在這個專案裡的處境很特別——`02改_資料網格.html` 上三個 BNB 專屬記錄**全部是缺席**：
沒有 CME 期貨（`cme-cot` 四幣有它沒有）、Kraken/Coinbase 都不上架（訂單簿只能用
Hyperliquid，實測深度 212,768 USD vs BTC 的 33,329,879）、BscScan 免費方案被擋。

季度銷毀是 BNB **唯一一件「有而別人沒有」的事**，而且是可量化的真實數字。
選它的理由是敘事完整度：不然 BNB 這一幣從頭到尾只有「缺席」可講。

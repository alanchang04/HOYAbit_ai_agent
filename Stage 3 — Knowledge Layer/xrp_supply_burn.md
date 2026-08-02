---
tags: [projects, hackathon, hoyabit, knowledge-layer, xrp-supply-burn]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer / Snapshot Knowledge（xrp_supply_burn）；2026-08-02 新增，XRP 的幣種專屬 factor
summary: XRP 交易費銷毀的 Knowledge Layer——Snapshot 型；⚠️ 銷毀速率實測 10 天約 1,233 XRP（總量的 0.0000012%），是敘事不是訊號
---

```yaml
# Stage 3 — Knowledge Layer / Snapshot Knowledge（xrp_supply_burn）
#
# 比照 orderbook_depth／tps 用 category: snapshot：不放 primary_horizon／persistence。

knowledge:
  factor_id: xrp_supply_burn
  factor_name: XRP 流通供給量與交易費銷毀
  category: snapshot

  ####################
  # Time Property
  ####################
  validity_window: 約 4 秒       # XRPL 帳本關閉間隔；下一個帳本就是新狀態
  max_lookback: 約 40 秒         # ⚠️ 端點只回最近 10 個帳本（2026-08-02 實測）。
                                 # 這是本專案回看範圍最短的 factor

  ####################
  # Scope
  ####################
  supported_assets: [XRP]
    # XRPL 的交易費銷毀是協議層機制（每筆交易的 base fee 直接銷毀、不給任何人），
    # 其他四幣沒有等價機制：BTC/SOL 無銷毀；ETH 的 EIP-1559 base fee 銷毀概念相近
    # 但那是浮動費率、量級完全不同；BNB 是**事件型**季度銷毀不是連續銷毀
    # （見 bnb_burn.md），性質不同不能混為一談

  ####################
  # Data Dependency
  ####################
  data_source: XRPScan `/api/v1/ledger`（免 key，每日 10,000 次請求額度）
  known_limitation: |
    ⚠️ 兩件事：
    ① **回傳結構跟先前文件記載不同**。pipeline/流程紀錄.md（2026-07 Step 28）
       記的是單筆帳本物件，2026-08-02 實測回的是
       {{"current_ledger": int, "ledgers": [10 筆]}}。接這個 factor 時要照
       實測結構寫解析，不要照舊文件。
    ② **只有 10 個帳本（約 40 秒）**，沒有任何歷史序列 → 算不出 ic。
       要建序列只能自己每天抓一次累積，那是另一件事（跟 raw_data/price 那些
       series CSV 同一種做法），本輪不做。

  magnitude_caveat: |
    ⚠️⚠️ **這個 factor 最重要的一句話**：銷毀速率極慢。
      2026-07-23 記錄：99,985,633,424.35 XRP
      2026-08-02 實測：99,985,632,191.46 XRP
      → 10 天減少約 1,233 XRP ＝ 總量的 0.0000012%
    在任何交易 horizon（1 天到 1 年）下，這個供給變動都不可能影響價格。
    定位因此是**敘事證據**（「XRP 有協議層通縮機制」是真的、可量化）
    而不是**預測訊號**。Stage 4 給的低權重就是照這個判斷來的，不是資料不足的權宜。

  ####################
  # Relationship（靜態知識）
  ####################
  Relationship:
    confirms: null            # ⚠️ 誠實列空。硬要說「銷毀多＝鏈上活躍＝利多」是兩層推論
                              # 疊加，本份不採用（會在 Graph 上製造沒有依據的確認邊）
    conflicts: null
    independent: cpi          # ✅ 有卡片可連——協議層供給機制與總經事件明確無關

  ####################
  # References
  ####################
  references:
    industry:
      - "XRPScan API - Ledger: https://api.xrpscan.com/api/v1/ledger"
    academic: null            # ⚠️ 誠實留 null，不填未查證的出處

  version: 1.0
  last_updated: 2026-08-02
```

## 為什麼 XRP 選這個

XRP 的另外幾個候選（XRPL `load_factor` 網路負載、兩個官方源的監管敘事）各有問題：
`load_factor` 實測長期是 1（沒有變化就沒有訊號），監管敘事屬於 News 方向已經被
`panews_sentiment` 涵蓋。交易費銷毀是 XRP **唯一一個協議層獨有、可量化、且五幣裡
沒有等價物**的數字。

⚠️ 但要誠實：選它是因為「XRP 專屬的可量化數字」這個條件下沒有更好的，
不是因為它有預測力。上面的 magnitude_caveat 講得很清楚——這是敘事素材。
Ken 拍板「都做了，抓不到就算了」，這份就是「抓得到但幾乎沒有訊號」的代表。

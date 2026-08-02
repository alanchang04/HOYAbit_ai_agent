---
tags: [projects, hackathon, hoyabit, knowledge-layer, cpi]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer（示範：cpi），2026-08-02 改用 [[11流程圖模板]] Event Knowledge schema（原本誤用 Statistical Knowledge，比對 [[09_權重改版草案]] 才發現分類錯誤，見下方說明）；references 為 2026-08-02 上網查證補充的公開文獻/產業資料，非編造
---

```yaml
# Stage 3 — Knowledge Layer，**改用 Event Knowledge 骨架**（示範：cpi）
#
# ⚠️ 2026-08-02 重新分類，理由跟 Stage 2 cpi.yaml 同一份：CPI 是排定公布
# 時程的離散事件（一個月一次），不是每天都有值的連續數列，套用 Statistical
# Knowledge（percentile／IC／HitRate 那套）從一開始就分類錯誤。09_權重改版
# 草案.md 的 Event Factor Interpreter 對應這種情況：量化方式是 Impact Level
# （Domain Knowledge 分級，不是統計出來的），09 自己給的示範分級表就把
# 「Fed 利率決議」跟 CPI 同性質的「決定性總體/結構事件」列為 Very High——
# 這裡沿用同一個分級，不是自己另外發明。

knowledge:
  factor_id: cpi
  factor_name: 美國消費者物價指數公布（CPI Release）
  category: event

  # Event Property
  event_type: scheduled_macro_release  # 排定時程，非突發事件——跟 ETF 核准這種時間不確定的事件不同
  event_class: 決定性總體/結構事件（Very High）  # 沿用 09_權重改版草案.md Event Factor Interpreter 示範分級表，跟 Fed 利率決議同級

  # Time Property
  reaction_window: 公布當下至 2-3 個交易日（初期衝擊，見下方 References）
  expected_duration: 數週至數月（透過 Fed 政策路徑預期的間接管道，效果比直接價格衝擊持續更久，但屬於「累積效應」不是這次公布本身的延續）
  # Event Factor 沒有 primary_horizon（那是 Statistical/Sentiment 骨架的欄位），但 Stage 4 的
  # time_horizon_match 仍需要一個可數值比對的區間，所以這裡補一格 applicable_days，
  # 內容是上面 reaction_window／expected_duration 兩段的換算，不是新的判斷。
  applicable_days: [0, 90]      # ⚠️ 這是**兩段不連續**尺度的聯集，不是單一連續區間：
                                 #   0-3 天   ＝ reaction_window（公布當下的直接衝擊）
                                 #   14-90 天 ＝ expected_duration（Fed 政策預期的間接管道）
                                 # 中間 4-13 天這段其實兩種效果都弱，但為了讓比對邏輯單純，
                                 # 這裡用聯集表示；落在區間內不代表各點強度相同，見 Stage 4 的判讀說明

  # Scope
  affected_assets: [BTC, ETH, SOL, BNB, XRP]  # 總經系統性因子，全幣種同時受影響，跟 funding_rate/active_address 需要逐幣種資料的性質不同
  affected_market: 全市場（現貨＋衍生品皆受影響，不限特定商品類型）

  # Dependency
  required_fields: release_date（公布時間）／reference_month（對應月份）／市場事前降息預期定價（判斷 surprise 方向的基準，非數字本身）

  # Relationship
  usually_affects: FOMC 利率決議預期、DXY 美元指數、美債殖利率——同一條總經流動性傳導鏈上的其他變數
  related_events: FOMC 利率決議（08 文件 SUPPLY_CALENDAR／FOMC_DECISIONS_2026 同一份事件日曆機制）

  # References（只存出處，不存評價；學界對「CPI/通膨跟 Bitcoin 到底正相關還負相關」沒有共識，兩派都列，不只列支持某一方的文獻）
  references:
    academic:
      - arxiv: "2301.10117"  # 《Bitcoin Does Not Hedge Inflation》——實證顯示 Bitcoin 對 1 個標準差的通膨驚訝（以 CPI 代理）當日顯著下跌 24bp
      - doi: 10.1016/j.jbusres.2024.115035  # Rodriguez & Colombo,《Is bitcoin an inflation hedge?》, Journal of Business Research, 2025——結論隨通膨指標選取與樣本期間而異
    industry:
      - "Cryptorank.io - Bitcoin Weathered 4 CPI Shocks in 2026: June's Print Lands Today: https://cryptorank.io/news/feed/2aa49-us-cpi-report-bitcoin-pump-or-dump-july-2026"
      - "Bitcoin Foundation - Why U.S. Macroeconomic Data Drives Bitcoin Price in 2026: https://bitcoinfoundation.org/news/bitcoin/why-u-s-macroeconomic-data-drives-bitcoin-price-in-2026-inflation-interest-rates-and-liquidity-impact-explained/"
      - "Cryptonomist - Crypto Market Response CPI Highlights Rally and Fed Impact (2026-07-16): https://en.cryptonomist.ch/2026/07/16/crypto-market-response-cpi/"

  # Metadata
  version: 0.2
  last_updated: 2026-08-02
```

### 這次公布的實際內容（事件本身的數字，非 Knowledge 欄位，供對照）

真實抓自 FRED（series id=CPIAUCSL），跟 Stage 2 cpi.yaml 記錄的事件時程對得上：

```yaml
reference_month: "2026-06"
release_date: "2026-07-14"
index_value: 332.568
mom_pct: -0.422   # 月增率，低於前值 333.979
yoy_pct: 3.464    # 年增率，基準 2025-06 = 321.435
```

### 跟既有知識庫的關係

**這份是這輪三個新示範裡唯一整份重寫過分類的**——Stage 2／Stage 3 原本都套 Statistical Factor／Knowledge 模板（percentile／trend／momentum／IC），2026-08-02 對照 [[09_權重改版草案]] 的 Factor Interpreter 分型表才發現：09 明確把 Macro 統計型限定在 FNG／FX（Fear&Greed、匯率），CPI 全文只出現在 Event 的 Failure Conditions 示範裡，`agent/collectors/macro.py` 現有程式碼也是拿 CPI 當事件日曆處理，不是連續序列——三個獨立線索都指向同一個結論：CPI 該用 Event Knowledge 骨架，不是 Statistical Knowledge。這是 Ken 提醒「你要把 09 的分型考慮進去」之後修正的，舊版（Statistical 版）已被這份取代。

---
tags: [projects, hackathon, hoyabit, knowledge-layer, etf]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer（示範：etf），欄位對照 [[11流程圖模板]] Statistical Knowledge schema；references 為 2026-08-02 上網查證補充的公開文獻/產業資料，非編造
---

```yaml
# Stage 3 — Knowledge Layer，Statistical Knowledge 骨架（示範：etf）
# 這層是「這個 Factor 本身有哪些金融知識」，不是算出來的數字（跟
# Stage 2 Feature Extraction/etf.yaml 那份即時抓取算出來的不一樣）。
#
# ⚠️ 這份是這輪目前為止文獻證據最強的一個，但有一個關鍵警訊要放在最前面：
#   1. 學術實證（SSRN，Lim 2026）給出具體數字：$100M 淨流入對應當日 53bp
#      報酬，流量解釋 21% 的日報酬變異，且能預測次日報酬——這比 funding_rate／
#      active_address／cpi／liquidation 任何一個的文獻證據都更直接、更量化
#   2. 但同一篇／同時期其他報導明確指出這是**雙向回饋迴圈**：流量造成報酬，
#      報酬也造成流量（動能追價的資金流）——也有產業評論直接說「ETF flow
#      不是在預測價格，是在確認已經在發生的方向」。這代表這個 factor 的
#      IC／HitRate measured 出來即使很高，也不能簡單解讀成「有預測力」，
#      可能大半是同期共變（contemporaneous correlation）而非領先關係，
#      這是這份 Knowledge 最重要的一個警訊，primary_horizon／persistence
#      要照這個雙向性質寫，不能只抄「文獻證據強」就當作單向領先訊號

knowledge:
  factor_id: etf
  factor_name: 美國現貨 BTC ETF 淨流量（Spot Bitcoin ETF Net Flow）
  category: statistical

  # Time Property
  # primary_horizon 改成結構化（2026-08-02 拍板 Option B），格式與其他四份 factor 一致；
  # 原 minimum_horizon／maximum_horizon 已收斂進 applicable_days 與 rationale。
  primary_horizon:
    scale: 短期
    applicable_days: [0, 10]   # ⚠️ 由下方 rationale 的「當日」～「10 個交易日」直接取值，非回測值；
                                # 語意是「適用多長的分析期間」，不是「要抓幾天資料」
    rationale: |
      當日至 10 個交易日內效果最集中；Lim 2026 估當日 53bp／$100M，10 日累積效果約
      96bp（見 references）。⚠️ 但因雙向回饋迴圈（flows↔returns 互為因果，見上方
      警訊），這個「短期效果」有多少是領先、多少是同期 confirm，本身仍是開放問題——
      跟 liquidation 那份「上限不適用」不同，這裡不是尺度概念不成立，是尺度內的
      因果方向不確定。超過 10 個交易日的累積效果文獻沒有明確估計。
  persistence: 中——效果會隨後續流量方向持續強化或減弱（回饋迴圈本身就是一種延續機制），但不是獨立於價格之外的「訊號本身很持久」，是跟價格互相強化的動態關係

  # Scope
  supported_assets: [BTC]  # 本文件示範資料來源＝美國現貨 BTC ETF 市場，目前沒有涵蓋 ETH/SOL/BNB/XRP 的對應免費資料源（BNB/XRP 甚至沒有美國現貨 ETF 這個資產類別存在）
  supported_market_regimes: 機構持續累積期（連續多日同向流量）訊號最清楚；流量方向頻繁翻轉、進出拉鋸的盤整期訊號雜訊大——2026 年實測就出現「10 日、$2.73B 流出後單日反轉 $221.72M 流入」這種急轉，解讀要謹慎，不能看一天流量方向就下定論
  supported_market_types: 現貨市場（ETF 申購/贖回機制透過授權參與商在現貨市場買賣 BTC），但反映的是機構/TradFi 資金管道，跟鏈上零售使用量（active_address）是不同的資金來源

  # Data Dependency
  required_inputs: bitbo.io ETF flow 頁面（各檔 BTC 現貨 ETF 逐日淨流量＋Totals 全市場合計，免key，僅近期窗口，見 Stage 2 已知限制）
  optional_inputs: ETF 總持倉量／規模（AUM）——用來判斷單日流量相對於存量的比例，同樣的流量金額對小規模 ETF 跟大規模 ETF 意義不同，這次示範沒有另外抓

  # Relationship
  confirms: price（現貨價格走勢）  # 文獻明確指出流量跟價格是雙向回饋，這裡定義成 confirms 而非「領先預測」，呼應上方警訊——這是同向確認關係，不是「這個訊號能告訴你價格接下來要漲跌」
  conflicts: active_address（鏈上活躍地址數）  # 呼應 [[Stage 3 — Knowledge Layer/active_address]] 已經記錄的發現：2024 年 ETF 通過機構化之後，價格走勢跟鏈上零售使用量出現結構性背離——etf 流量代表的正是這條「機構資金管道」，跟「鏈上零售使用」是兩個可能互相背離的資金/使用來源，這條關係在 active_address 那份就已經埋了伏筆，這裡是反過來從 ETF 這邊呼應
  independent: liquidation（清算流／連鎖清算）  # 一個是現貨市場的機構申購贖回行為，一個是衍生品市場的槓桿倉位強平機制，資金管道與市場層次都不同，可視為獨立訊號並列

  # References（只存出處，不存評價）
  references:
    academic:
      - ssrn: "6592830"  # Lim, B.C.,《The Price Impact of Spot Bitcoin ETF Flows》——核心量化發現：$100M 淨流入≈當日 53bp 報酬，流量解釋 21% 日報酬變異，能預測次日報酬，但同時發現雙向回饋迴圈（flows 造成 returns，returns 也造成 flows）
    industry:
      - "Techtimes - Bitcoin ETF Inflows Hit $510M Over 3 Days: When BlackRock Leads, Bitcoin Follows (2026-07-09): https://www.techtimes.com/articles/319974/20260709/bitcoin-etf-inflows-hit-510m-over-3-days-when-blackrock-leads-bitcoin-follows.htm"
      - "KuCoin - How Bitcoin ETF Inflows and Outflows Impact BTC Price in 2026: https://www.kucoin.com/blog/how-bitcoin-etf-inflows-and-outflows-impact-btc-price-in-2026"
      - "Cryptonomist - Bitcoin ETF Inflows Mark 2026 Trend Reversal and Market Signal (2026-07-27): https://en.cryptonomist.ch/2026/07/27/bitcoin-etf-inflows-trend-reversal/"
      - "Intellectia.ai - Bitcoin ETF Flows 2026: Institutional Investors Retreat After...: https://intellectia.ai/blog/bitcoin-etf-flows-2026-analysis"

  # Metadata
  version: 0.1
  last_updated: 2026-08-02
```

### 跟既有知識庫的關係

這份文獻證據是這輪所有示範裡最強、最量化的（$100M→53bp 這種具體換算比率，其他 factor 的文獻都停在方向性/相關性層次），但正因為證據太漂亮，更要提防「同期共變被誤讀成預測力」這個陷阱——這是這份 Knowledge 最核心的警訊，寫在最前面，不是等 Stage 4 算出漂亮的 ic 才想到要澄清。

⚠️ 跟 [[Stage 3 — Knowledge Layer/active_address]] 的關係要講精確：這裡把 `conflicts` 定成 `active_address`，是**概念上呼應**——兩份文件各自獨立查證出「機構 ETF 資金」跟「鏈上零售使用」是會背離的兩條資金管道；但 active_address.md 那份自己寫的 `conflicts` 值是 `price`，不是 `etf`，兩個欄位字面上沒有互指。這代表 Stage 6 Evidence Graph **不會**自動畫出 etf↔active_address 這條邊（只會各自畫向各自寫的 `price`／被誰引用），只有這份文件單向指向 active_address。要讓這條關係在圖上真的連起來，需要回頭改 active_address.md 的 `conflicts`（例如改成 `price ＋ etf`），這輪先不動別人的檔案，只誠實記錄這個落差，不假裝已經是雙向結構化關係。

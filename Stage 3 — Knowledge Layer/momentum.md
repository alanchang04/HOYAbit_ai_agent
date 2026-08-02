---
tags: [projects, hackathon, hoyabit, knowledge-layer, momentum]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer（示範：momentum）；2026-08-02 新增，補上 agent/collectors/price.py 已經在算、但一直沒有接進 Stage 2-6 完整骨架的技術面動能訊號（RSI14）。欄位對照 [[11流程圖模板]] Statistical Knowledge schema；primary_horizon 採 2026-08-02 拍板的 Option B 結構化格式，跟 funding_rate／active_address 一致；references 為 2026-08-02 上網查證補充的公開文獻/產業資料，非編造
---

```yaml
# Stage 3 — Knowledge Layer，Statistical Knowledge 骨架（示範：momentum）
#
# 這份只涵蓋 RSI14（相對強弱指標），不是 agent/collectors/price.py 產出的整包
# 技術指標（SMA7/14、RSI14、波動率、量能趨勢合成一筆 EvidenceDraft）。拆開的
# 理由跟 price（現貨報價）那份一致：Stage 2-6 的 Statistical Factor 骨架是
# 「一個 factor 一條可回測的序列」，RSI14 是這包指標裡唯一有清楚學術定義、
# 有天然值域（0~100）、有公認超買超賣門檻、且能獨立算 percentile／ic 的一個——
# SMA 是趨勢追蹤指標不是動量指標，波動率／量能不是「動量」概念，各自更適合
# 開自己的卡片，不是這份的範圍。

knowledge:
  factor_id: momentum
  factor_name: 動量指標（RSI14 相對強弱指標）
  category: statistical

  # Time Property
  # primary_horizon 採結構化格式（2026-08-02 拍板 Option B，格式與 funding_rate／
  # active_address 一致）：applicable_days 可數值比對，rationale 保留論述。
  primary_horizon:
    scale: 短期至中期
    applicable_days: [3, 30]   # RSI14 本身用 14 天窗口算，訊號在數天到約一個月內最有解讀力；
                                # 人工判斷，非回測門檻
    rationale: |
      RSI14 用 14 天收盤價算一次值，太短的窗口（1-2 天）看不出「超買/超賣」的
      累積效果；太長的窗口（數月以上）RSI 會在極端區間反覆進出，單一讀數的
      邊際資訊量下降，且產業文獻指出動量訊號的可預測性會隨窗口拉長而減弱
      （見下方 references，高頻/日內動量效果比月度動量更一致）。
  persistence: 短——RSI 逐日重算，一天一個新值，但它反映的「超買/超賣」狀態通常會維持數天到一兩週才緩解或反轉（見產業慣例：極端 RSI 讀數常見連續多日）

  # Scope
  supported_assets: [BTC, ETH, SOL, BNB, XRP]  # 五幣皆有本地 OHLCV 資料集，皆可算
  supported_market_regimes: 強趨勢市場中 RSI 容易長時間停留在極端區間而不觸發反轉（「鈍化」現象）——熊市可長期低於30、牛市可長期高於70；盤整/區間市場中超買超賣訊號較可靠。這是技術分析的常見觀察，不是本專案回測結論
  supported_market_types: 現貨（本地 OHLCV 資料集是現貨日線收盤價），非永續合約——跟 funding_rate 抓的衍生品資料是不同市場

  # Data Dependency
  required_inputs: 本地共同基準資料集 data/{coin}_daily_ohlcv.csv 的收盤價序列（RSI14 需要至少 15 天資料算出第一個值）
  optional_inputs: 跨資料源交叉驗證（例如交易所自家的 K 線 API）——單一資料集若有缺漏或錯誤會直接反映在 RSI 上，多資料源比對可提高可信度，這份 demo 沒有實作

  # Relationship
  confirms: volume_change_24h（24 小時成交量變化）  # 產業共識：動量訊號搭配量能確認才可靠——價漲量增支持動量延續，價漲量縮則動量可能減弱（見下方 industry 來源）
  conflicts: active_address（鏈上活躍地址數）  # RSI 反映的是價格動能，active_address 反映的是鏈上使用行為，兩者可能背離：價格因槓桿/衍生品交易快速動能上衝，但鏈上實際使用量沒有同步跟上，是「價格與基本面脫鉤」的一種型態
  independent: cpi（美國消費者物價指數公布）  # 短期價格動能訊號跟月頻總經事件是不同時間尺度、不同成因，不假設兩者存在固定關係

  # References（只存出處，不存評價；動量訊號的方向與強度學界沒有共識，見下方兩篇實證論文的分歧發現）
  #
  # ⚠️ RSI 的原始出處（J. Welles Wilder Jr., New Concepts in Technical Trading
  # Systems, 1978）沒有 DOI／arXiv／SSRN 可引——這本書早於這些識別碼系統存在。
  # webapp/stage1_demo_api.py 的 _enrich_references() 只認得 doi/arxiv/ssrn 三種
  # key，硬塞一個 `citation:` 欄位會被靜靜濾掉（kind 解析不出來，不會報錯但畫面
  # 上不會出現）——與其留一條看起來存在、實際上讀不到的參考，不如誠實只列有
  # 數位識別碼可查證的文獻，Wilder 原始定義改放進下方 industry 說明性連結裡。
  references:
    academic:
      - doi: 10.1016/j.najef.2022.101733  # Wen, Bouri, Xu, Zhao,《Intraday Return Predictability in the Cryptocurrency Markets: Momentum, Reversal, or Both》, North American Journal of Economics and Finance, 2022——高頻加密貨幣市場同時存在動量與反轉，方向隨流動性與大事件而變
      - doi: 10.1016/j.ribaf.2019.101176  # Chu, Chan, Zhang,《High Frequency Momentum Trading with Cryptocurrencies》, Research in International Business and Finance, 2020——七大加密貨幣的高頻動量策略實證，效果隨資產與頻率而異
    industry:
      - "Investopedia - Relative Strength Index (RSI) Indicator Explained With Formula（含 Wilder 1978 原始定義與 70/30 門檻由來）: https://www.investopedia.com/terms/r/rsi.asp"
      - "Binance Academy - What Is the Relative Strength Index (RSI)?: https://academy.binance.com/en/articles/what-is-the-relative-strength-index-rsi"

  # Metadata
  version: 0.1
  last_updated: 2026-08-02
```

### 跟既有知識庫的關係

這是繼 `price` 之後第二個從 `agent/collectors/price.py` 拆出來、接進 Stage 2-6 完整骨架的技術面因子。跟 `price`（即時報價快照，本質上沒有歷史序列）不同，`momentum` 是**完整規格的 Statistical Factor**——有真正的每日序列、能算 percentile／trend，也能現場算 `rolling_spearman_ic`（見 [[Stage 4 — Dynamic Evidence Weight Engine/momentum]]，這個 factor 跟 funding_rate 一樣不需要 Stage 4 .md，值是現場算出來的）。

`agent/collectors/price.py` 原本把 SMA／RSI／波動率／量能四個指標合成一筆 `EvidenceDraft`，這裡只挑 RSI14 開一張獨立卡片，理由是它是這四個指標裡唯一有清楚公認定義（Wilder 1978）、天然值域（0~100，適合算 percentile）、且是「動量」這個概念的標準代表——SMA 是趨勢指標、波動率跟量能都不是動量概念，各自需要另外開卡片，不是這份補齊的範圍。

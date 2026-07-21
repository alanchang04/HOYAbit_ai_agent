# 各類資料時間窗口政策

> 最後更新：2026-07-21

## 背景

命題文件「多源整合」範例題型明講是「過去兩週」，且執行時間硬性上限 15 分鐘、
單次執行機會——即時 API 呼叫的窗口要摳。但主辦方提供的 5 年 Daily OHLCV 是
本地 CSV（零網路成本），可以拿長窗口不用省。

**核心邏輯：六類不套同一個數字，分兩層**——Price 的技術面吃本地免費長窗口，
其餘五類（即時 API 呼叫）窗口盡量收斂在題目常見的兩週尺度上下。

## 六類窗口設定

| 類別 | 建議窗口 | 理由 |
|---|---|---|
| Price | 技術面：全歷史本地 CSV（算 MA20/60/120、歷史波動率百分位）；敘事面：近 2-4 週 | 長窗口零成本，算「相對歷史的位置」；描述「現在發生什麼」收斂到兩週尺度 |
| Onchain | 近 14-30 天，日頻 | 看趨勢不是單日快照，但即時 API 有限速+時間預算，30 天內日頻夠用 |
| News | 近 7-14 天為主，重大結構性事件（監管/上市/駭客）額外標記不受窗口限制 | 新聞訊號衰減快；重大事件即使超過兩週也該保留 |
| Social | 近 3-7 天 | 社群情緒最短命，抓太長會把過期情緒當現況 |
| Derivatives | 近 7-30 天 | funding rate／持倉量看趨勢和擁擠度，30 天內足夠算相對位置 |
| Macro | 回顧 30-90 天＋往前看下一個排定事件（下次 FOMC/CPI） | 總經是慢變數，且題目可能問「即將到來的事件」，要往前看不只往後看 |

## 現況比對（2026-07-21 盤點，逐檔核對過實際常數）

標記說明：✅ 已落實（正式 collector 或 prototype 皆算）／⚠️ 部分落實，缺口有明確原因／
❌ 尚未落實（有明確待辦）。「正式」＝併進 `agent/collectors/`，pipeline 呼叫得到；
「prototype」＝目前只在 `pipeline/`，Ken 驗證用，還沒併回正式 collector。

### Price ✅（技術面已用全歷史，敘事面 2 週）

| 內容 | 窗口 | 狀態 | 位置 |
|---|---|---|---|
| SMA7/14、RSI14、近 14 日波動率、MA20/60/120 | 近 121 天（`INDICATOR_WINDOW`） | 正式 | [price.py:24](../../agent/collectors/price.py#L24) |
| OHLCV 敘事摘要 | 近 14 天 | 正式 | [price.py:172](../../agent/collectors/price.py#L172) |
| MA20/60/120 完整歷史序列 | 全歷史（1826 天） | prototype，未併回 | [compute_ma.py](../../pipeline/compute_ma.py) |
| 波動壓縮度百分位（20 天標準差 vs 近 90 天分佈） | 90 天滾動 | prototype，未併回 | [compute_volatility_compression.py:26-27](../../pipeline/compute_volatility_compression.py#L26-L27) |
| 歷史波動率百分位（14 天標準差 vs 全歷史） | 全歷史（擴張視窗） | prototype，未併回 | [compute_historical_volatility_percentile.py](../../pipeline/compute_historical_volatility_percentile.py) |
| 相對強弱比值 90 天位置 | 90 天滾動 | prototype，未併回 | [compute_relative_strength.py](../../pipeline/compute_relative_strength.py) |

「全歷史」目前只在 prototype 落地，正式 `price.py` 的技術指標仍是 121 天窗口（MA120 所需最小值）。三支全歷史/90 天 prototype 都已驗證能跑，尚未併回正式 collector 的 evidence 產出——這是「還沒 merge」不是「忘記做」。

### Onchain ⚠️（快照已符窗口精神，「日頻歷史」缺口明確且部分幣種無免費來源）

| 內容 | 窗口 | 狀態 | 位置 |
|---|---|---|---|
| 即時快照（區塊高度/Gas/TPS/mempool） | 當下一個時間點 | 正式 | [onchain.py](../../agent/collectors/onchain.py) |
| 日頻歷史序列 | BTC 近 5 年、ETH 回溯到 2015 | prototype，僅 BTC/ETH | [fetch_onchain_history.py:9-12](../../pipeline/fetch_onchain_history.py#L9-L12) |

SOL/BNB/XRP 目前沒有免費歷史序列來源（見 `pipeline/待辦筆記/onchain_歷史資料.md`），這不是窗口設計問題，是資料源本身的缺口。「14-30 天日頻」這個窗口設計只有在把 `fetch_onchain_history.py` 併回正式 collector 後才會被讀報告的人看到；目前正式 collector 仍是純即時快照。

### News ✅（已符合，且已內建重大事件不受限的彈性）

RSS 抓 `MAX_ITEMS_PER_SOURCE=5` 篇最新項目，沒有寫死日期窗口——RSS feed 本身天然只回傳近期項目，效果上落在 7-14 天內；重大事件不因為超過兩週被排除（RSS 本身沒有窗口截斷邏輯，不會誤刪）。[news.py:18](../../agent/collectors/news.py#L18)

### Social ✅（已符合，t=week 剛好落在建議窗口內）

Reddit 搜尋 `params={"t": "week"}`，即近 7 天，落在「近 3-7 天」建議窗口的上緣。[social.py:29](../../agent/collectors/social.py#L29)

### Derivatives ⚠️（尚未有正式 collector，prototype 窗口普遍落在 7-30 天內，個別欄位是短窗趨勢不是主指標）

| 內容 | 窗口 | 狀態 | 位置 |
|---|---|---|---|
| 費率擁擠度百分位 | 90 筆（8h/筆，約 30 天） | prototype | [fetch_funding_rate_percentile.py:30](../../pipeline/fetch_funding_rate_percentile.py#L30) |
| OI×價格四象限 | 30 小時趨勢（主指標是當下 OI+方向，趨勢只是輔助） | prototype | [fetch_oi_price_quadrant.py:33](../../pipeline/fetch_oi_price_quadrant.py#L33) |
| 多空帳戶比背離 | 30 小時趨勢（同上，主指標是最新一筆） | prototype | [fetch_long_short_ratio.py:33-34](../../pipeline/fetch_long_short_ratio.py#L33-L34) |
| 期貨到期結構 | 當下快照（永續/當季/次季三點） | prototype | [fetch_futures_term_structure.py](../../pipeline/fetch_futures_term_structure.py) |
| CME COT 機構倉位 | 12 週 | prototype | [fetch_cme_cot.py:36](../../pipeline/fetch_cme_cot.py#L36) |
| 選擇權 IV/Skew | 目標到期日 30 天（不足則 clamp 到最遠檔） | prototype | [fetch_options_binance.py:52-54](../../pipeline/fetch_options_binance.py#L52-L54) |
| 跨幣費率差 / CEX-DEX 費率差 | 複用費率擁擠度的 30 天快照 | prototype | [compute_cross_coin_funding_diff.py](../../pipeline/compute_cross_coin_funding_diff.py) |
| 清算流 | 45 秒即時監聽窗（性質不同，見下） | prototype | [fetch_liquidation_flow.py:35](../../pipeline/fetch_liquidation_flow.py#L35) |

OI×價格四象限、多空帳戶比這兩項的「30 小時」是輔助趨勢欄位，不是主要判讀依據（主判讀是最新一筆的方向/背離），跟「近 7-30 天」的建議窗口不衝突，是不同層次的東西，不需要改。清算流因為 Binance 只開放即時推送、沒有歷史 REST 端點，本質上是「觀察窗」不是「回顧窗」，跟其他六類的窗口定義不是同一件事，Ken 已在腳本 docstring 裡把這個限制講清楚，報告措辭也已配合调整。整批衍生品都還是 pipeline prototype，尚未併成正式 `agent/collectors/derivatives.py`。

### Macro ✅（Fear & Greed 30 天落在建議範圍下緣，事件日曆已覆蓋「往前看」）

| 內容 | 窗口 | 狀態 | 位置 |
|---|---|---|---|
| Fear & Greed 百分位 | 近 30 天 | 正式 | [macro.py:14](../../agent/collectors/macro.py#L14) |
| 美元匯率 | 當下快照 | 正式 | [macro.py](../../agent/collectors/macro.py) |
| FOMC/CPI 事件日曆 | 回顧最近一次＋往前看下一次 | prototype，未併回 | [fetch_event_calendar.py](../../pipeline/fetch_event_calendar.py) |

`FNG_WINDOW=30` 落在「30-90 天」建議範圍的下緣，符合但沒有用滿範圍；事件日曆已經同時做到「往前看下一個排定事件」，只是還沒併進正式 `macro.py` 的 evidence 輸出。

## 待併回正式 collector 的項目（如果要更完整落實這份窗口政策）

以下都已在 `pipeline/` 驗證過邏輯正確，只是還沒進 `agent/collectors/`，是這份政策目前唯一「文件上有、正式輸出裡沒有」的落差：

1. `compute_ma.py` / `compute_volatility_compression.py` / `compute_historical_volatility_percentile.py` / `compute_relative_strength.py` → 併進 `price.py`，補上全歷史技術面 evidence
2. `fetch_onchain_history.py` → 併進 `onchain.py`（僅 BTC/ETH，SOL/BNB/XRP 仍缺免費歷史源）
3. `fetch_event_calendar.py` → 併進 `macro.py`，補上「往前看下次 FOMC/CPI」的 evidence
4. 整批衍生品 prototype → 新增正式 `agent/collectors/derivatives.py`（見 `pipeline/待辦筆記/derivatives_collector化.md`）

這些是實際新增程式碼／改動正式 collector 的工作，不是調整窗口常數就能完成，且會動到 alanchang 也在維護的 `agent/collectors/`，按照 [[project-hoyabit-git-workflow]] 併回前建議先跟他對過。

## 對應 raw_data 子資料夾

- `raw_data/price/` — 技術面全歷史（`ma_20_60_120_series.csv`、`volatility_compression_series.csv` 等）＋近 2-4 週敘事面（`realtime_price.json`）
- `raw_data/onchain/` — 近 14-30 天（僅 BTC/ETH 有歷史序列，其餘幣種仍是即時快照）
- `raw_data/news/` — 近 7-14 天（重大事件不受限）
- `raw_data/social/` — 近 3-7 天
- `raw_data/derivatives/` — 近 7-30 天
- `raw_data/macro/` — 回顧 30-90 天＋下一個排定事件

對應設計脈絡見上層 [DATA_SOURCES.md](../../DATA_SOURCES.md)、逐項開發紀錄見 [pipeline/流程紀錄.md](../../pipeline/流程紀錄.md)。

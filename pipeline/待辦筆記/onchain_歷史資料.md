# Onchain 歷史資料待辦

> 2026-07-20 討論起頭：Onchain 現況（`fetch_onchain.py`）只抓「當下一個時間點」
> 快照，跟 Price 方向有 5 年歷史 CSV 不一樣。Ken 決定先暫緩、記錄起來，之後
> 有空再處理。

## 已測試過的結論（免 key，實測驗證過）

| 幣/鏈 | 5 年歷史 | 怎麼拿 |
|---|---|---|
| BTC | 可以 | `blockchain.info` 免費 charts API。hashrate／24h 交易筆數有 1822 天（2021-07-21~2026-07-19）；mempool 筆數/大小只有 1497 天（~4年） |
| ETH | Gas 價格可以 | `etherscan.io/chart/gasprice?output=csv`，免 key 公開圖表下載端點，回溯到 2015 年 |
| BNB | 卡住 | `bscscan.com` 同款端點被 Cloudflare 擋掉（403），沒找到免費替代 |
| SOL | 卡住 | RPC 的 `getRecentPerformanceSamples` 只給「最近」幾個窗口，不是歷史序列 |
| XRP | 卡住 | 沒找到免費的每日歷史帳本統計來源 |

## 對應窗口設計（2026-07-21 補記）

`07_流程圖迭代定案.md` Round 4 把這個缺口列進六大類窗口表——Onchain 建議
窗口是「近 14-30 天，日頻」，本檔上面的測試結論就是在填這個窗口的資料源。

## 卡住三幣二次測試（2026-07-21 補測）

| 幣 | 結論 | 細節 |
|---|---|---|
| BNB | 仍卡住 | 實測 `bscscan.com/chart/tx?output=csv` 直接回 403（Cloudflare），跟上面結論一致，沒找到繞過法 |
| BNB | 可能出路：Dune Analytics | 免費方案支援 SQL query + API（`dune.com/blockchains/bnb` 資料齊），但要先手動寫一條 query 存起來才能靠 API 抓，且免費額度有月執行次數限制——不是「免 key 直接 GET」等級，是要花工才能用的路 |
| SOL | 仍卡住 | 實測 `public-api.solscan.io/chaininfo` 回 401，需要 key |
| SOL | 可能出路：Dune Analytics | Dune 原生索引 Solana，理論上可比照 BNB 寫一條歷史 tx count query，限制同上 |
| SOL | 其他選項：Helius | 官方主打歷史資料完整，但要申請/付費，非公開免費 |
| XRP | 仍卡住 | `api.xrpscan.com/api/v1/stats` 回 404；Ripple 官方 `data.ripple.com/v2`（舊 Data API）回 403，這服務其實已經停維護 |
| XRP | Dune 不支援 | XRPL 非 EVM/非 Solana，Dune 沒有原生索引這條鏈，目前完全沒找到免費的每日歷史交易數來源 |

結論：三個卡住的幣目前都還沒有像 BTC/ETH 那種「單一 GET 就拿到 CSV」的免費來源。Dune Analytics 對 BNB/SOL 是一條可能路，但代價是要自己寫 SQL query＋有月配額限制，跟現有免 key 方案不同量級；XRP 目前是死路，沒有替代方案。

## 待 Ken 補的筆記

-

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

## 待 Ken 補的筆記

-

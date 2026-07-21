# X 大老提及次數／觀點立場待辦

> 2026-07-20~21 討論起頭：卡片標記 status: unverified，Ken 要求實測抓抓看
> 「X 大老提及 BTC 次數」這個想法可不可行。結論：免費路線覆蓋率跟資料新鮮度
> 兩個條件湊不齊，沒有一條線可以直接用，需要 Ken 決定要縮小範圍、換訊號性質、
> 還是直接降級成非核心訊號。

## 已測試過的結論（實測驗證過，2026-07-20/21）

| 路線 | 結果 | 細節 |
|---|---|---|
| Nitter 鏡像站（xcancel.com） | 覆蓋率差，不可預測 | 測 8 個候選帳號，只有 @saylor／@elonmusk 抓到 200，其餘 6 個（Vitalik／CZ／Solana／Ripple／CryptoCapo／Adam Back）全部 403，15 秒後重試仍 403。換兩個備援鏡像（lightbrd.com、nitter.privacyredirect.com）也掛，證實是系統性問題（X 對 guest-token 爬蟲的軍備競賽），不是單一站點或 IP 被擋 |
| Nitter 抓到的資料本身 | 若抓得到，資料是即時的 | @saylor 抓到 21 則近期貼文，日期跟抓取當天對得上，BTC/Bitcoin 內容密集，訊噪比高。@elonmusk 雖然也抓到 200，但 20 則裡幾乎沒有加密貨幣內容，不能算有效訊號來源——「抓得到」不等於「訊號有用」 |
| X 官方 syndication API（`syndication.twitter.com/srv/timeline-profile/screen-name/{handle}`） | 覆蓋率好，但資料是舊的 | 官方內嵌推文用端點，測 5 人（Vitalik／CZ／CryptoCapo／aeyakovenko／JoelKatz）4 人有資料。但回傳的不是近期時間軸，是橫跨 2018~2026 的「精選／高互動」歷史推文（例：cz_binance 100 則裡只有 1 則是 2026 年），無法拿來算「近期提及次數」；aeyakovenko（Solana 創辦人）直接 0 則 |
| Reddit `.json` 公開端點 | 已被封死 | curl 直接被 Reddit 官方擋（`403 Blocked`，`Server: snooserv`，是判定成機器人流量，不是暫時性錯誤），WebFetch 走不同網路出口也連不上。2023 年後跟 X 同樣的鎖數據趨勢 |
| Reddit 官方 OAuth API | 未測試，但已知有免費額度 | 跟 X 不同，Reddit 官方 API 對讀取公開資料仍保留免費層（每 App 每分鐘 100 次），要用的話需要 Ken 自己去 reddit.com/prefs/apps 註冊一個 App 拿 client_id/secret；但這是「社群熱度」訊號（subreddit 討論量），不是「指定大老」訊號，性質跟原本設計不同，不是直接替代品 |

## 已定案的子決策

- Layer2 觀點立場改用**規則式關鍵字判斷**（bullish/bearish 詞庫，本地算，方向 +1/0/-1），不占 LLM call 額度——這點 Ken 已確認，不管上面資料源問題怎麼解，這個判斷邏輯先保留

## 待 Ken 補的筆記

-

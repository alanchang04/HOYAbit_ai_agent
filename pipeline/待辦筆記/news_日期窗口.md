# News 日期窗口待辦

> 2026-07-21 討論起頭：對照 `07_流程圖迭代定案.md` Round 4 的窗口設計表——
> News 建議窗口是近 7-14 天為主，重大結構性事件（監管/上市/駭客）額外標記
> 不受窗口限制。現況 `agent/collectors/news.py` 的 `MAX_ITEMS_PER_SOURCE=5`
> 是「抓最新 5 則」，不管間隔多久——官方 blog 發文頻率低時，5 則可能橫跨
> 數月，等於沒有真正的日期窗口過濾。

## 現況

- RSS 來源（BTC/ETH/SOL）：`entry.get('published')` 有拿到日期字串但沒拿來
  過濾，只是印在 `content_reference` 裡
- HTML 來源（BNB/XRP）：`_scrape_bnbchain_blog` 直接標記「未知」日期，
  `_scrape_ripple_insights` 有抓到日期但同樣沒過濾

## 待處理方向（未定案，僅記錄想法）

- 加日期窗口判斷：超過 14 天的項目要嘛濾掉、要嘛額外標記「非近期」
- 但如果某幣官方源本來就發文很少（例如 BTC 只有一條 Optech Newsletter），
  過濾後可能整類無資料——這個 trade-off 需要 Ken 決定

## 待 Ken 補的筆記

-

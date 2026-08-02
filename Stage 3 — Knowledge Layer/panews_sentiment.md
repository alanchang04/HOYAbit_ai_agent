---
tags: [projects, hackathon, hoyabit, knowledge-layer, sentiment, panews]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer（示範：panews_sentiment），欄位對照 [[11流程圖模板]] Sentiment Knowledge schema；對應 [[09_權重改版草案]] Sentiment Factor Interpreter（原本完全沒設計，這份是第一次落地）；references 為 2026-08-02 上網查證補充的公開文獻，非編造
---

```yaml
# Stage 3 — Knowledge Layer，Sentiment Knowledge 骨架（示範：panews_sentiment）
# 這層是「這個 Factor 本身有哪些金融知識」，不是算出來的數字（跟
# Stage 2 Feature Extraction/panews_sentiment.yaml 那份即時抓取算出來的不一樣）。
#
# ⚠️ 這是這輪四個示範裡第一個 Sentiment 類型，跟前三個（Statistical／Event）
# 都不同型，關鍵知識點：
#   1. 學術文獻對「媒體情緒有沒有預測力」不是簡單的有/沒有二分——2026 年
#      研究明確指出這是 regime-dependent（狀態依存）：情緒訊號在「恐懼／貪婪
#      極端狀態」下、或對「低市值＋近期下跌」的資產上，預測力比較顯著；在
#      正常狀態下對大市值資產（BTC 正是其中之一）預測力較弱。這代表
#      primary_horizon／persistence 不能只給一個籠統數字，要註明「有條件」。
#   2. Stage 2 已經誠實記錄了方法論缺口（用簡化版關鍵字計分，非正式 NLP 模型），
#      這份 Knowledge 的 confirms／conflicts 判斷也建立在這個簡化方法之上，
#      換一個真正的情緒模型後，這裡的關係判斷可能需要重新驗證。

knowledge:
  factor_id: panews_sentiment
  factor_name: PANews 媒體報導情緒（中文加密貨幣媒體情緒指標）
  category: sentiment

  # Source Property
  platform: PANews（universal-api.panewslab.com，中文加密貨幣媒體）
  data_type: 媒體報導標題＋摘要（記者編輯過的內容，非使用者原創社群貼文——跟 Twitter／Reddit 類 Sentiment 來源性質不同，見下方 Scope）

  # Time Property
  # primary_horizon 改成結構化（2026-08-02 拍板 Option B），格式與其他 factor 一致。
  primary_horizon:
    scale: 短期（狀態依存）
    applicable_days: [1, 14]    # ⚠️ 由 rationale 的「短期」人工換算成天，非回測值。
                                 # 這個 factor 特別要注意：即使 horizon 落在區間內，也不代表訊號可靠——
                                 # 它的預測力是 regime-dependent（見 rationale），時間尺度匹配只是必要條件不是充分條件
    rationale: |
      短期，且高度狀態依存（regime-dependent）——2026 研究顯示情緒訊號在「恐懼/貪婪極端狀態」
      或「低市值+近期下跌資產」上預測力較顯著，BTC 屬大市值資產，正常狀態下訊號較弱，
      需搭配 market_regime 一起判斷，不是穩定的單一時間尺度。
  update_frequency: 準即時（NEWS 型快訊近乎即時發布，NORMAL 型深度文章數小時到數天一篇；本文件示範用歷史分頁端點，非即時 RSS，見 Stage 2 差異說明）

  # Scope
  supported_assets: [BTC, ETH, SOL, BNB, XRP]  # 關鍵字比對規則對五幣都定義了（見 pipeline/fetch_media_kol_mentions.py COIN_KEYWORDS），但這次示範只實測 BTC
  supported_languages: [zh]  # 本文件示範只抓 lang=zh 版本，PANews 有其他語言版本但未測試涵蓋範圍

  # Dependency
  required_inputs: universal-api.panewslab.com/articles 分頁端點（title/desc/publishedAt/authorId/metric）

  # Relationship
  confirms: news（官方新聞事件）  # PANews 常常是官方新聞的二次報導/大老觀點轉寫，跟 Stage 3 News 類 Knowledge（若存在）方向上應該高度重疊，不是獨立訊號源
  conflicts: 待驗證——目前簡化版關鍵字方法命中率只有 49.1%（見 Stage 2），近一半文章立場資訊沒被捕捉到，現階段不足以自信判斷跟哪個 factor 系統性衝突，換成真正的 NLP 模型後才適合下這個結論

  # References（只存出處，不存評價）
  references:
    academic:
      - doi: 10.1002/for.70068  # Gür,《The Impact of News Sentiment on the Bitcoin Price via Machine Learning and Deep Learning-Based NLP Models》, Journal of Forecasting, 2026
      - arxiv: "2411.12748"    # 《FinBERT-BiLSTM: A Deep Learning Model for Predicting Volatile Cryptocurrency Market Prices Using Market Sentiment Dynamics》——示範了用金融領域微調過的 BERT 模型（FinBERT）做情緒分類，是 Stage 2 那套簡化關鍵字法未來應該升級成的方向
      - doi: 10.1007/s12525-025-00815-6  # 《Wisdom of the crowd signals: Predictive power of social media trading signals for cryptocurrencies》, Electronic Markets, 2025——關鍵發現：情緒訊號的預測力是 regime-dependent，不是穩定恆常的
    industry:
      - "PANews 首頁 RSS 訂閱說明: https://www.panewslab.com/zh/rss"

  # Metadata
  version: 0.1
  last_updated: 2026-08-02
```

### 跟既有知識庫的關係

這份是這輪第一個補上的 Sentiment 型示範，對應 [[09_權重改版草案]] 明確標記「全新，還沒設計」的 Sentiment Factor Interpreter。內容特性又跟前三個示範（active_address／cpi／liquidation）不同——這個 factor 最大的知識點不是「有沒有預測力」的是非題，是「預測力在什麼條件下才會出現」，`primary_horizon` 因此寫成有條件描述，不是單一數字，這是照 Ken 的要求「根據 data 制定不同的內容」延續下來的做法。

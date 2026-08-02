---
tags: [projects, hackathon, hoyabit, knowledge-layer, snapshot, orderbook]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer（示範：orderbook_depth）；**第四型 Snapshot Knowledge 骨架**，2026-08-02 新增。⚠️ references 這份**尚未做文獻查證**，跟其他五份不同——其他份的 academic/industry 出處是實際查證過的，這份先留空待補，不放沒查證過的引用
---

```yaml
# Stage 3 — Knowledge Layer，**Snapshot Knowledge 骨架**（示範：orderbook_depth）
#
# ⚠️ 這是第四型 Knowledge（前三型：Statistical／Event／Sentiment），跟前三型的
# 差別在**時間性質**，不只是欄位名不同：
#   Statistical → 「這個 factor 在哪個時間尺度上有預測力」（primary_horizon）
#   Event       → 「事件發生後多久市場反應完」（reaction_window）
#   Sentiment   → 同 Statistical，但預測力是狀態依存的
#   Snapshot    → 「這個測量值的有效期有多長」（validity_window）——盤口是秒級變動的
#                  狀態量，五分鐘前的深度跟現在可以完全不同，它不是「訊號持續多久」
#                  的問題，是「這個數字多快就過期」的問題
# 兩者不能混用同一格：把 validity_window 填進 primary_horizon，Stage 4 的
# time_horizon_match 會拿「秒級」去比對查詢的「2週」，得到一個毫無意義的落差判斷。

knowledge:
  factor_id: orderbook_depth
  factor_name: 永續合約盤口深度／流動性（Order Book Depth）
  category: snapshot

  # Time Property（Snapshot 型專屬——不是 primary_horizon）
  validity_window: 秒級——盤口逐筆變動，這張快照描述的是「打 API 那一瞬間」的狀態，
    不宜當成分鐘級以上的持續狀態引用
  refresh_semantics: 每次執行重新打一次 REST，沒有「上次的值」可比較（除非自建歷史，見 Stage 2 檔尾第 3 點）
  # primary_horizon / persistence 這兩格**不適用**：它們預設 factor 是一個能跨時間比較的
  # 序列。這裡不填「不適用」四個字了事，而是直接不放這兩個 key——放了會讓下游以為
  # 有這個概念只是這次沒填（同 liquidation.yaml 對 percentile 的處理原則）

  # Scope
  supported_assets: [BTC, ETH, SOL, BNB, XRP]  # Binance USDⓈ-M 永續合約，五幣都有盤口
  supported_market_types: 永續合約掛單簿；跟現貨盤口是不同的簿，不可互相代用
  supported_market_regimes: 高波動／事件前後最有解讀價值（深度會急縮、價差會拉開）；
    平靜盤中深度變化不大時，這個 factor 的資訊量偏低

  # Data Dependency
  required_inputs: Binance USDⓈ-M `/fapi/v1/depth`（免 key，limit=1000）
  optional_inputs: open_interest（判斷「深度縮」是撤單還是真的減倉）；funding_rate（同上，交叉判斷擁擠度）

  # Relationship
  confirms: funding_rate ＋ open_interest  # 同屬衍生品市場微結構的不同切面：費率看付費壓力、
    # OI 看倉位規模、深度看承接能力。三者同向時對「市場結構是否脆弱」的判斷才比較穩
  conflicts: （尚無已知穩定的矛盾對象，待文獻查證後補）
  independent: cpi（總經數據）  # 一個是市場微結構的當下狀態，一個是排程總經事件，資料域不重疊

  # References
  # ⚠️ 這份**還沒做文獻查證**——其他五份 Stage 3 的 academic/industry 出處都是實際查過、
  # 附得出 DOI/arXiv/URL 的。這裡不放「聽起來合理」的引用充數。要補的方向記在下面，
  # 補的時候應該找：order book imbalance 對短期報酬的預測力（市場微結構經典題）、
  # 掛單可撤性／spoofing 對深度指標可信度的影響、crypto 永續市場的深度與清算連鎖關係。
  references:
    academic: []   # 待補
    industry: []   # 待補

  # Metadata
  version: 0.1
  last_updated: 2026-08-02
```

### 為什麼要開第四型，而不是把它塞進既有三型

Stage 3 的三型骨架各自對應一種**時間性質**，不是三種產業分類。盤口深度套哪一型都會壞：

| 套用 | 壞在哪 |
|---|---|
| Statistical | `primary_horizon`／`persistence` 預設 factor 是可跨時間比較的序列，盤口不是；套下去 Stage 4 的 `time_horizon_match` 會拿「秒級」去比對查詢的「2 週」，算出一個沒有意義的落差 |
| Event | 盤口不是排程事件，沒有 `reaction_window`／`event_class` 可言 |
| Sentiment | 它測的不是情緒，是掛單簿的物理狀態 |

所以新增 `category: snapshot`，Time Property 換成 `validity_window`（這個數字多快過期），並**直接不放** `primary_horizon`／`persistence` 兩個 key——這跟 cpi 那份「用 `→ reaction_window` 標示對應」的處理不同：cpi 是同一個概念換個名字，這裡是概念本身不存在。

### 這份跟其他五份最大的差別：references 是空的

其他五份的出處都經過實際查證。這份的資料源是這輪臨時決定改用的（原本是 liquidation 走 WebSocket，實測那條管道在本機收不到任何 frame），文獻還沒查。**空著比填一個看起來很像的引用誠實**——Stage 4 的 Prior Weight 因此也只能靠 Domain Knowledge 給值，那份文件會把這個依賴關係講清楚。

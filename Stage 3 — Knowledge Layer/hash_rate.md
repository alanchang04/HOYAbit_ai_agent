---
tags: [projects, hackathon, hoyabit, knowledge-layer, hash-rate]
source: [[13流程圖迭代定案v2]] Stage 3 — Knowledge Layer / Statistical Knowledge（hash_rate）；2026-08-02 新增，BTC 的幣種專屬 factor
summary: BTC 算力的 Knowledge Layer——中長期尺度、資本支出驅動、與 active_address 互相印證；補掉 active_address 原本指向空節點的 confirms 邊
---

```yaml
# Stage 3 — Knowledge Layer / Statistical Knowledge（hash_rate）
#
# 2026-08-02 新增。這份的 Relationship 是這輪唯一「補上去就修好一條既有斷邊」的：
# active_address.md 的 confirms 列了 hash-rate，但本專案沒有這張卡，Stage 6 Graph
# 會畫出指向空節點的邊（design.md 缺口 1 的原始範例）。這份補上之後兩端都有卡片。

knowledge:
  factor_id: hash_rate
  factor_name: Bitcoin 網路算力（Hash Rate）
  category: statistical

  ####################
  # Time Property
  ####################
  primary_horizon:
    scale: 中長期
    applicable_days: [30, 365]   # ⚠️ 由下方 rationale 人工換算成天，**非回測值**。
                                 # 之後若有回測結果應該覆蓋掉（跟其他 factor 同一條規則）
    rationale: |
      算力反映的是礦工的**實體資本支出決策**——買機台、簽電力合約、蓋機房，
      決策週期以月、季為單位，不是日內或數日可以反轉的東西。因此這個 factor
      擅長回答「這一季礦工在擴張還是收縮」，不擅長回答「這週會漲會跌」。
      ⚠️ 短期還有一層雜訊：算力是從出塊速度回推的估計量，單日波動有相當比例
      來自出塊運氣（variance），不是真的有礦機上下線，這也是短 horizon 不適用的原因。

  persistence: 高——礦機一旦部署就會持續運轉（沉沒成本），除非電價或幣價跌破關機價才會下線，
               狀態延續性是所有鏈上指標裡最強的一類

  update_frequency: 每日一筆（blockchain.info charts API 日頻）

  ####################
  # Scope
  ####################
  supported_assets: [BTC]  # ⚠️ 概念上只對 PoW 鏈成立。ETH 已轉 PoS（2022 The Merge 之後沒有算力這回事）、
                           # SOL/BNB/XRP 本來就不是 PoW，這個 factor 對它們**不是資料源缺失，是概念不成立**

  ####################
  # Data Dependency
  ####################
  data_source: blockchain.info Charts API `hash-rate`（免 key）
  known_limitation: |
    ⚠️ 2026-08-02 實測 timespan=5years 回 1822 筆（2021-08-03 ~ 2026-08-01）。
    這是資料源的實際涵蓋範圍，不是參數設錯。

  ####################
  # Relationship（靜態知識，不隨每日刷新變動；「今天同不同向」歸 Stage 4 查詢當下算）
  ####################
  Relationship:
    confirms: active_address   # ✅ 兩端都有卡片——同屬「鏈上使用強度」這一組，
                               # 且 active_address.md 的 confirms 本來就列了 hash-rate，
                               # 補上這份之後變成雙向確認，是本專案第一組雙向 confirms
    conflicts: price           # 礦工投降（capitulation）情境下算力下降常**落後於**價格下跌，
                               # 兩者短期會出現方向背離；這是有文獻討論的經典情境，
                               # 但本份沒有引可驗證的出處，僅記錄為產業共識
    independent: cpi           # 總經事件與礦工資本支出決策不在同一個因果鏈上

  ####################
  # References
  ####################
  references:
    industry:
      - "Blockchain.com - Hash Rate Chart: https://www.blockchain.com/explorer/charts/hash-rate"
    academic: null
      # ⚠️ 誠實留 null：本份沒有查證過可引用的學術出處。其他幾份 Knowledge 的
      # academic references 是實際查過的，這份不比照填一個沒查證的進去湊格式。
      # 要補的話是獨立一項工作（查文獻 → 驗證 DOI → 填入），不在本輪範圍。

  version: 1.0
  last_updated: 2026-08-02     # 每日刷新只動這一格（13 拍板）
```

## 為什麼 BTC 選這個當幣種專屬 factor

BTC 原本就有兩張別的幣沒有的卡（`etf`／`active_address`），照理不缺。選 hash_rate 的
理由不是「BTC 資料不夠」，是**它同時解掉一個結構性缺口**：Stage 6 `design.md` 缺口 1
舉的兩個空節點範例是 `open_interest` 跟 `hash-rate`，補這張卡直接消掉其中一個，
而且是唯一能讓專案出現第一組**雙向 confirms 邊**的補法（active_address ⇄ hash_rate）。

⚠️ 這也是它跟 `open_interest` 的差別：補 `open_interest` 能一次接回三條邊（投報率更高），
但那是**衍生品**資料、五幣共用，不是幣種專屬 factor，不符合這輪「一幣一個」的定位。
兩件事不衝突，`open_interest` 仍留在待補清單上。

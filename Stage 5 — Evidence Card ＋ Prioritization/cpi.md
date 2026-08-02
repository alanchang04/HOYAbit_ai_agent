---
tags: [projects, hackathon, hoyabit, evidence-card, cpi]
source: [[13流程圖迭代定案v2]] Stage 5 — Evidence Card ＋ Prioritization（示範：cpi）；13 的 Evidence Card schema 是照 Statistical Factor 設計的，Event Factor 有三格對不上，這份記錄對應方式（2026-08-02）
---

```yaml
# Stage 5 — Evidence Card ＋ Prioritization（示範：cpi）
#
# ⚠️ 這份要處理的是**卡片格式的分型缺口**，不是資料缺口。
# 13 正文那張 Evidence Card 範例是拿 funding_rate（Statistical Factor）畫的，
# 欄位定義寫死了三個對照關係：
#     primary_horizon: = Stage 3 Knowledge.primary_horizon
#     persistence:     = Stage 3 Knowledge.persistence
#     related_evidence: = Stage 3 Knowledge 的 confirms／conflicts／independent
# 但 cpi 在 Stage 3 已經改用 **Event Knowledge 骨架**（見
# [[Stage 3 — Knowledge Layer/cpi]]），這三個來源欄位在 Event Knowledge 裡
# **根本不存在**——Event Knowledge 對應的是 reaction_window／expected_duration／
# usually_affects／related_events。所以這張卡不是「有格子填不出來」，是
# 「schema 指定的來源欄位在這一型 Knowledge 裡不叫這個名字」。
# 對應方式記在下面每一格，不是靜靜換掉、也不是硬塞 null 假裝沒事。

evidence:
  evidence_id: CPI_BTC              # 沿用 demo 的 {FACTOR}_{COIN} 格式（13 命名規則仍待定）
                                    # ⚠️ 但 cpi 是總經系統性因子，Stage 3 affected_assets 是五幣全體——
                                    # 把幣種塞進 id 裡會產生五張內容完全相同的卡（CPI_BTC／CPI_ETH…），
                                    # 語意上其實只該有一張。id 規則待拍板時要一起考慮這件事
  category: event                   # ← Stage 3 knowledge.category＝event（不是 statistical，13 拍板：分類以 13/Stage 3 為準）

  ####################
  # fact ← Stage 2（事件時程 ＋ 這次公布的數字）
  ####################
  fact:
    current_value:                  # CPIAUCSL 指數值（FRED）
    mom_pct:                        # 月增率
    yoy_pct:                        # 年增率
    percentile:                     # ⚠️ 語意警告：對月頻事件算 percentile，母體是「過去 N 個月的指數值」，
                                    # 跟 Statistical Factor 的「過去 N 天的日值分位」不是同一種東西。
                                    # CPI 指數本身長期單調上升（物價指數的性質），現值幾乎永遠落在高分位——
                                    # 這格算得出數字，但**讀起來會誤導**，卡片顯示時要嘛不顯示、要嘛標註母體
    # 沒有 trend 這格：Event Factor 的「趨勢」概念在 Stage 2 已經改成事件時程
    # （announcement_time／hours_since_event／next_release），不是 slope 判讀出來的方向

  features:                         # 完整欄位見 Stage 2 cpi.yaml（Event Factor 骨架：event_type／confirmation_count／hours_since_event…）
  knowledge:                        # 完整內容見 Stage 3 cpi.md（Event Knowledge 骨架）

  ####################
  # evidence_weight ← Stage 4 的 final_weight（Event Factor 走 impact_level，不走 ic）
  ####################
  evidence_weight:                  # = prior_weight 0.8（impact_level: Very High 分級推導）× context_modifier（LLM 給）
    # 13 已拍板：三種 Prior Weight 來源（ic 算法／impact_level 分級／Domain Knowledge 理由）
    # 在 Evidence Card 這層視為**同一個 evidence_weight 概念下的不同填法**，不是三套系統。
    # 卡片上不區分來源，但排序時要意識到一件事：0.8 這個數字是人工分級表給的，
    # active_address 的 ic≈0 是回測算出來的——兩個數字放進同一個排序鍵比大小時，
    # 比的不是同一種東西（「重要性」vs「預測力」）。
    # ✅ 2026-08-02 Ken 拍板：**一律照 evidence_weight 排序**，不因來源不同而分組、
    # 加註記號或另設規則——來源差異已經在 Stage 4 各 factor 的文件裡交代清楚，
    # 不在排序層重複處理。上述不可比性列為「已知且接受的副作用」，不是待處理項

  source_reliability: null          # Stage 4 未定案，跟著留白
  historical_support: null          # 同上
  primary_horizon: → reaction_window        # ⚠️ 對應（非原欄位）：Event Knowledge 沒有 primary_horizon，
                                            # 最接近的是 reaction_window＝公布當下至 2-3 個交易日
  persistence: → expected_duration          # ⚠️ 對應（非原欄位）：Event Knowledge 沒有 persistence，
                                            # 最接近的是 expected_duration＝數週至數月（透過 Fed 政策路徑的間接管道）
    # 這兩格的對應不是等價替換：Statistical 的 primary_horizon 是「這個 factor 在哪個尺度有預測力」，
    # Event 的 reaction_window 是「事件發生後多久市場會反應完」——一個講訊號適用尺度，一個講衝擊衰減時間。
    # Stage 4 的 time_horizon_match 線索比對這一格時，等於是拿兩種尺度概念在比，
    # Event Factor 的 modifier 判斷因此比 Statistical Factor 複雜（Stage 4 cpi.md 已標注同一件事）

  ####################
  # related_evidence（Event Knowledge 沒有 confirms/conflicts/independent 三分法）
  ####################
  related_evidence:
    confirms: null                  # Event Knowledge 無此欄位
    conflicts: null                 # Event Knowledge 無此欄位
    independent: null               # Event Knowledge 無此欄位
    # 最接近的是 usually_affects（FOMC 利率決議預期／DXY／美債殖利率）跟 related_events（FOMC）——
    # 但語意完全不同：confirms/conflicts 是「訊號之間同不同向」（對稱關係，Stage 6 Graph 要的），
    # usually_affects 是「這個事件會影響誰」（有方向的因果宣稱，不對稱）。硬把 usually_affects
    # 塞進 confirms 會讓 Graph 把「CPI 影響 DXY」讀成「CPI 與 DXY 互相確認」，那是錯的。
    # 這裡誠實留 null，代價是 **cpi 這張卡在 Stage 6 Evidence Graph 上會是孤立節點**。
    # 反過來看，[[Stage 3 — Knowledge Layer/liquidation]] 的 independent 有列 cpi，
    # 所以圖上其實有一條 liquidation → cpi 的邊——關係存在，只是要從對方那側才連得到。
    # Event Factor 要不要補一組對稱的 relationship 欄位，待拍板

  traceability: FRED series CPIAUCSL（數值）＋ BLS CPI 公布時程（事件，經 usinflationcalculator.com 彙整）
                # 跟 agent/collectors/macro.py 的 CPI_RELEASES_2026 事件日曆同一份資料

prioritization:
  ranking_key: evidence_weight      # 13 拍板：純照 evidence_weight
  evidence_coverage: null           # 定義未拍板，不生成
  expected_rank: 前段               # prior_weight 0.8 是目前所有示範裡最高的（active_address ic≈0／liquidation 0.3／
                                    # panews_sentiment ic=0.051、confidence=low），
                                    # 只要 context_modifier 不給到接近下限 0.5，這張卡大概率排第一。
                                    # 排第一的理由是「人工分級表給了 0.8」而非回測結果，這點已於
                                    # 2026-08-02 拍板為可接受（見上方 evidence_weight）——記錄在此供讀卡的人理解，
                                    # 不是要求排序層做任何額外處理
```

### Event Factor 進 Evidence Card 缺了什麼

這張卡沒有任何一格是「資料抓不到」——CPI 的數字跟時程都是公開、抓得到、已經抓到的。它缺的三格（`primary_horizon`／`persistence`／`related_evidence`）全部是**格式問題**：13 的 Evidence Card schema 把來源欄位寫死成 Statistical Knowledge 的欄位名，而 Stage 3 已經拍板 cpi 改用 Event Knowledge 骨架。兩份文件各自都對，接起來才出現落差。

三格的處理方式刻意不一致，因為三格的性質不一樣：

| 卡片欄位 | 處理 | 為什麼 |
|---------|------|-------|
| `primary_horizon` | 對應到 `reaction_window` | 概念不等價但同屬「時間尺度」，標明是對應、不是原欄位，下游至少讀得到東西 |
| `persistence` | 對應到 `expected_duration` | 同上 |
| `related_evidence` | 留 `null`，不對應 | `usually_affects` 是**有方向的因果宣稱**，塞進對稱的 confirms 會讓 Stage 6 Graph 讀出錯誤關係——這裡填錯比留白傷害大 |

代價講清楚：cpi 在 Stage 6 Evidence Graph 上是**孤立節點**（只有 liquidation 那側單向列了 `independent: cpi`）。對一個 `prior_weight` 最高、大概率排第一的 factor 來說，圖上沒有邊代表辯論層（Stage 8）的 `DEBATE_GRAPH_RULE` 對它完全不生效——「不可當獨立佐證疊加信心」這條規則檢查不到它。這是目前 Event Factor 走完整條 pipeline 最實質的一個缺口，先記錄，待 Ken 拍板要不要給 Event Knowledge 補一組對稱關係欄位。

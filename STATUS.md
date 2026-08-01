# 專案進度說明（HOYA BIT 2026 雲湧智生黑客松）

> 最後更新：2026-07-24

## 已完成

### Stage 1：專案骨架
- `agent/schemas.py`：Evidence／EvidenceDraft／LogEntry pydantic schema（id 格式 `ev-NNN`、ISO8601 時間戳驗證、`coin` 欄位）
- `agent/config.py`：`.env` 載入、選用 API key 缺漏警告、LLM backend 切換設定
- `agent/logging_utils.py`：`execution_log.jsonl` 逐行寫入
- `main.py`：CLI 進入點（`--coin` / `--coin2` / `--question` / `--dry-run`）
- `--dry-run` fixture 流程（不打任何真實 API/LLM，供賽前排練）

### Stage 2：五類真實 collector
- `agent/collectors/base.py`：統一 timeout（預設 75 秒）＋ try/except 隔離，單一來源失敗不影響全流程
- `price`：主辦方 OHLCV CSV ＋ 純 Python 技術指標（SMA7/14、RSI14、波動率、量能趨勢，零 LLM/API 成本）＋ CoinGecko（備援 CryptoCompare）
- `onchain`：依鏈路由（BTC→Blockchair／ETH,BNB→EVM RPC／SOL→Solana RPC／XRP→XRPL RPC），皆為免 key 端點，有 Etherscan/BscScan key 時疊加補充證據
- `news`：每幣官方發布源優先，BTC/ETH/SOL 走官方 RSS，BNB/XRP 無官方 RSS 退階解析官方頁面
- `social`：Reddit 公開 `.json` 搜尋端點
- `macro`：Fear & Greed Index（近 30 天百分位）＋ Frankfurter 匯率（美元強弱代理），有 FRED key 時疊加美債殖利率
- `social`：Reddit 搜尋。**2026-07-28 改版**——Reddit 已全面封鎖未認證的 `.json` 端點
  （實測 `www`／`old` 子網域、自訂 UA 與瀏覽器 UA 一律 403，本機直連同樣被擋，
  非先前記錄的「雲端 IP 封鎖」），改走仍開放的 `.rss`（Atom）端點，實測可穩定取得
  10 筆／幣。代價是 RSS 不含 score／留言數，熱度降級為「則數＋標題＋時間分布」，
  已在 `source` 欄誠實標示。若 `.env` 設 `REDDIT_CLIENT_ID`／`REDDIT_CLIENT_SECRET`
  則自動改走 OAuth 取回完整欄位（免費申請，額度也較寬），沒設定就用 RSS，不中斷

### Stage 3：LLM backend 抽象層與四步推理鏈（含多輪辯論）
- `agent/reasoning/llm_client.py`：`LLMClient` 介面 ＋ `build_llm_client()` 工廠，依 `.env` 的 `LLM_BACKEND` 切換
  - `bedrock`：**競賽正式規定唯一合法後端**，已完整打通並用真實模型驗證（見下方「Bedrock 驗證」）
  - `gemini`：開發階段暫代後端，已修正 thinking token 佔用輸出額度、額度耗盡快速失敗（不做無意義重試）
- `agent/reasoning/pipeline.py`：事實層 → 交叉驗證層 → **推論層（正方 vs 反方多輪辯論，上限 2 輪）** → 結論層
  - 反方每輪誠實回報是否還有新論點（`has_new_points`），沒有就提前收斂，不必固定燒滿輪數
  - 正方在後續輪次會針對反方批評逐項回應、修正論證（而非重複自己第一輪的話）
  - 裁判（Step D）看得到完整逐輪辯論紀錄與反方批評，不會漏看反駁就下結論
  - 時間預算防護：辯論輪次之間會檢查剩餘時間是否足夠再跑一輪，不夠就提前收在當輪進裁判
  - 任一步失敗都有對應降級路徑（保留已完成輪次／退回單模型 fallback），不會讓整條推理鏈中斷
  - 所有步驟的 evidence id 引用都會過濾模型幻覺
- 支援三種題型分支（多源整合／假設驗證／比較分析），比較分析會自動偵測題目中的第二幣種並雙幣種平行蒐集

### Stage 3.5：資料層信任評分改版（採用 Ken 的四因子設計）
- `agent/filters/dedup.py`：Phase 2 標題相似度去重（news/social，本地字串級），算出 raw/deduped/dedup_rate 並隨證據保存，被去重者標記但不刪除（保留可回溯）
- `agent/filters/source_weights.py`：`w = 新鮮度 × 來源等級 × 覆蓋度 × dedup_penalty`，來源等級查 `static/source_reputation.json`（賽前信譽表，含分級理由，印進報告附錄）；信譽表載入失敗自動退回舊制規則表，不中斷流程
- 拉盤話術命中改為「來源等級降一級」（取代舊制 ×0.5），與 dedup_penalty 是獨立維度、允許疊加
- `agent/filters/content.py`：F9 情緒分布分析詞典法 MVP（正/負面詞典、樣本去重後計算、單向占比過高標羊群警示）

### Stage 4：報告生成
- `agent/report/builder.py`：組裝 `report.md`（執行摘要／結論／關鍵依據／正反方多輪辯論與矛盾訊號／信心說明／後續觀察重點／信源分級附錄），強制檢查引用的 evidence id 必須存在
- `agent/report/text_formatting.py`：LLM 長文（市場判斷／正反方論證）改用 markdown 渲染，處理內嵌括號編號與中文序數詞（首先/其次/第三...）兩種列點寫法，解決長篇論述變成一整面文字牆的問題

### Stage 5：整合測試
- 5 幣種（BTC/ETH/SOL/BNB/XRP）collector 皆重新驗證
- **真實 Bedrock 端到端驗證**（2026-07-24，Claude Sonnet 4.5，region `ap-northeast-1`）：多源整合（BTC）、假設驗證（ETH）、比較分析（BTC vs SOL）三種題型皆完整跑完多輪辯論，report.md／四面板渲染正確
- Degraded mode 與跨 5 幣種推理鏈離線測試（FakeLLMClient，不耗真實額度）
- 256 個 pytest 全數通過

### Stage 6：Web UI 與 Docker
- `webapp/app.py`：FastAPI Web UI，與 CLI 共用同一個 `run_pipeline()`
- 四面板檢視（`/view/{run_id}`）：原始證據流／未過濾基準對照／信任提煉流水線（逐層 log、多輪辯論逐輪顯示，L5 層預設展開）／分析報告（含執行摘要卡片）
- `report.md` 的「報告」分頁改為排版化 HTML 顯示（原本是把 markdown 原始碼塞進純文字框）
- Dockerfile／`.dockerignore`：本機已驗證 build 成功、容器內完整跑過 dry-run 分析
- **Docker image 已 push 到 ECR**（`hoyabit-agent:latest`，`ap-northeast-1`）
- App Runner 所需 IAM role（ECR 存取角色＋Bedrock 呼叫用 instance role）已建立

## 尚未完成 / 待辦

1. ~~**App Runner service 建立**（阻塞項，非程式問題）~~
   ✅ **已解決（2026-08-01，改用 EC2 部署於主辦方帳號）**

   **公開網址：http://52.33.16.251/**（Elastic IP，固定不變）

   | 項目 | 值 |
   |---|---|
   | 帳號 | `149255038012`（主辦方 Workshop Studio） |
   | Region | `us-west-2` |
   | 執行個體 | `i-0f7f925714b7e2b30`（t3.small, AL2023） |
   | IAM 角色 | `hoyabit-agent-ec2-role`（僅 `bedrock:InvokeModel`／`Converse`） |
   | 安全群組 | `hoyabit-agent-sg`（僅開 80，未開 SSH） |
   | 管理方式 | SSM Run Command（`AmazonSSMManagedInstanceCore`），不開 22 port |
   | 模型 | `global.anthropic.claude-opus-4-6-v1` |

   **為什麼不是 App Runner**：主辦方帳號的 App Runner 被 SCP 擋
   （`AccessDeniedException`），與先前 Alan 個人帳號卡 Free plan 是不同原因。
   實測該帳號 ECR／ECS／Lambda／EC2／S3／CloudFront 皆可用，**只有 App Runner 被擋**。
   選 EC2 是因為行為與本機完全一致、不必改任何程式碼，30 分鐘可上線。

   **為什麼從 GitHub clone 而不是推 Docker image**：會場網路壅塞，推送含全部依賴的
   image 太慢；讓 EC2 用 AWS 自己的網路 clone + pip install 快得多。

   **憑證處理**：機器上**不存任何金鑰**，走 EC2 執行個體角色。
   Workshop 的 STS 臨時憑證會過期，寫進機器等於埋一顆定時炸彈。

   **驗收（三項皆通過）**：
   - 四次真實執行結果可瀏覽（已隨 repo 一起部署）
   - dry-run 0.7 秒完成，**不需任何 AWS 憑證**，評審可自行下題
   - 真實 Bedrock 執行 230 秒完成、零錯誤 → `/view/b7f36505`

   ⚠ 測試時若偶發連線中斷，是**會場網路**問題不是伺服器——同一端點加 `--retry`
   即恢復，且回傳位元組數與本機渲染完全一致（78981／72459／99011／79673）。
2. **Live Demo 錄影**：決賽交付項目要求的現場執行錄製影片
3. **提案簡報**：解題方向、AI 技術應用、數據資料應用、AWS 架構圖（圖片形式）、Kiro 工作流截圖、AgentCore 取捨說明
4. **跟 Ken 對齊兩件事**：(a) `agent/collectors/relative.py` 與已合併進來的 `pipeline/compute_relative_strength.py` 功能重疊，需決定用誰的；(b) `static/source_reputation.json` 裡兩個暫定值（dedup 分級曲線、min_sample 門檻）需要校準定案
5. **news.py 命中則數改用去重後數量**：屬於 Kevin／Ken 的 collector 範圍，`origin/ken` 分支已合併，可以開始做
6. **衍生品 collector 正式實作**：Ken 目前只有獨立 prototype 腳本＋範例資料（`pipeline/fetch_*.py`），還沒包成 `agent/collectors/` 底下的正式 Collector、沒接進 orchestrator
7. **賽前完整排練**：用 Bedrock + 正式 App Runner 網址跑一次完整流程，確認時間與穩定性
8. **向主辦方確認比賽當日執行環境**：包括是否會提供官方 AWS 帳號（目前只是 Alan 的假設，PDF 未提及）、網路出口 IP（影響 Reddit/交易所地理封鎖）、Bedrock 帳號是否已預先開通。若確定要換成主辦方帳號，務必提前（非當天）用該帳號實際跑過一次完整流程，避免重踩這次自己帳號遇過的 Bedrock/IAM/App Runner 各種帳號層級的坑

   **另外要一併問的資料集問題（2026-07-25 新增，來自 `horizon-aware-confidence` spec）**：
   命題範例題型要求分析「過去兩週」，但共同基準資料集止於 **2026-05-31**，
   距今已 55 天（BTC 期間跌 −13.0%、SOL −10.2%、ETH −7.4%，實測驗證）。
   僅用官方 CSV 在物理上無法回答該題型。要問：
   - (a) 比賽當日是否會提供更新至比賽日的資料集？
   - (b) 若否，參賽隊伍自行補充公開來源的近期 OHLCV 是否符合規則？

   目前團隊裁定走**雙軌**（官方 CSV 為長歷史基準 + Binance 公開日線補缺口 + 報告揭露接縫）。
   無論答案為何先做都不會白做——補齊邏輯是「有缺口才補」，主辦方若給新資料即自動不觸發。

9. **辯論機制待 LLM 驗證的項目**（原記於 `HANDOFF_debate-dev.md`，該檔已於 2026-07-27
   刪除，內容過時；以下是刪除時仍未解決的部分）：
   - **收斂判定缺客觀後備**：目前完全信任反方自報 `has_new_points`
     （`agent/reasoning/pipeline.py` 的 `_coerce_bool`）。反方是被指派立場的對抗方，
     自評「還有沒有話講」本身有利益衝突；且正方沒有對等的收斂權。可用
     `agent/filters/content.py` 既有的 Jaccard 比對前後輪論證強制收斂，
     **但建議先看真實模型行為再決定**，避免解決不存在的問題
   - **辯論品質需重驗**：反方是否濫用收斂權、第 2 輪正方是真反駁還是換句話說、
     實際延遲是否合乎時間預算的 1.5 倍係數、`has_new_points` 的格式遵從度。
     PR #8 改過 Step B/D 的 prompt，先前用 Bedrock 驗過的三題型結果已失效，需重跑

10. **`raw_data/` 與 `pipeline/*.py` 沒有接進 agent**（2026-07-27 複查仍成立）：
    `agent/collectors/*.py` 自己用 httpx 打即時 API，`pipeline/fetch_*.py` 是獨立腳本
    把資料寫進 `raw_data/`。`agent/` 底下只有兩處**註解**提到 `raw_data`
    （`collectors/horizon.py`、`collectors/news.py` 指向 `_meta/window_policy.md`），
    **沒有任何一行程式讀它**。也就是 2026-07-22 merge 進來的衍生品／期限結構／
    CME COT／鏈上歷史 CSV，對 LLM 推理鏈一筆都沒進去。這可能是刻意的 prototype
    階段安排，但若團隊以為那些資料已在餵 agent，需要及早澄清

11. ~~**正方第 1 輪的 prompt 缺結構，產出品質明顯低於第 2 輪**~~
    **已處理（2026-07-30，alanchang `af3cd3e`）**：(a)(b) 照做——刪掉「可以是一段
    完整的話」、抽出 `DEBATE_LENGTH_RULE` 讓三個辯論位置共用 600 字上限；
    **(c) 輕量骨架依實際輸出資料否決**：07-29 10:05 那次真實跑的正方第 1 輪是
    1487 字 6 點條列、第 2 輪 1280 字 6 點條列，兩輪結構相同且第 1 輪更長，
    「第 1 輪排版較差」在該樣本上不成立。與下方原記錄的「待決定」傾向一致
    （骨架給越細，四題輸出越像同一個模子）。原始分析保留供對帳：

    隊員反映第 2 輪論證的排版明顯比第 1 輪好。查下來不是錯覺，
    也不是設計取捨，是**累積出來的不對稱**——四個辯論 prompt 裡只有 C1 第 1 輪
    （`build_step_c1_bull_prompt`）沒有任務拆解：
    - **無任務區塊**：第 2 輪有【任務】四點（「逐項回應反方的批評」等），反方有
      三段式（critique／argument／has_new_points），第 1 輪從角色宣告**直接跳到規則**。
      「逐項回應」這類措辭本身就在誘導條列輸出，第 1 輪沒有任何等價物。
    - **JSON 說明在反向誘導**：第 1 輪寫 `"argument": "正方完整論證（可以是一段完整的話…）"`，
      「可以是一段完整的話」讀起來就是允許寫成一坨散文。第 2 輪沒有這句。
    - **無長度上限**：600 字那條只加在第 2 輪，而且是 alanchang Task 3.8 實測踩到
      「27 筆證據時輸出被 max_tokens 截斷、燒掉 6 分鐘且整輪作廢」才補的。
      **第 1 輪面對同樣 27 筆證據，且沒有前輪逐字稿約束它，其實承擔同一個截斷風險。**
      這不只是排版問題。

    **修法**：第 2 輪的任務清單不能直接複製（第 1 輪沒有東西可以「逐項回應」）。
    最小改動是 (a) 刪掉「可以是一段完整的話」，(b) 補上與第 2 輪對齊的長度上限，
    (c) 給第 1 輪自己的輕量骨架。

    **待決定**：骨架要給多細。給越細排版越整齊，但四題跑出來的論證會越像同一個模子
    ——第 2 輪之所以自然，是因為它在回應真實存在的批評，內容本身就是分歧的。
    vic 傾向只要求「分點陳述、每點掛 evidence id」，不規定點數與各點內容。
    建議先看隊員手上那份第 1 輪實際輸出再定案。

12. **反方在結構上系統性強於正方**（2026-07-29 隊員回報，vic 複查）：隊員反映
    反方論證明顯比正方強。**注意隊員提出的假設「每一輪的信心程度有規定」在程式裡
    不存在**——`prompts.py` 全檔「信心」只出現三次（`SYSTEM_PROMPT` 第 3 條與
    Step D 兩行），C1／C2 沒有任何逐輪信心欄位。效應是真的，機制不是這個。

    **最大成因已於 2026-07-29 10:59 移除（commit `698a89e`）**：在那之前只有正方帶
    「你的論證必須誠實…**不要誇大成過度肯定的語氣**」，反方無對等條款。一方被明文
    要求別聽起來太肯定，另一方沒有。Alan 的 7.2 驗收跑於 07-28 20:53（`e7b46f7`），
    **早於修正 14 小時**。
    ⚠️ **待確認：隊員看的是哪一次跑的輸出？** 若是 07-29 上午之前，主因已修，
    這條可能不需再動；貿然再修會從相反方向把同一件事修兩次，變成正方過強。

    修正後仍存在的結構性優勢（**皆未經真實輸出驗證**）：
    - **① 資訊不對稱（每輪）**：反方 prompt 收 `bull_argument` 為必填參數；正方拿不到
      反方當輪論證，第 2 輪也只有前一輪逐字稿。反方永遠在資訊嚴格較多的狀態下發言。
    - **② 反方多一把武器**：反方輸出 `critique` ＋ `argument`（攻擊＋建構），
      正方只有 `argument`。**正方全程沒有任何欄位可以攻擊反方的論證**，
      第 2 輪的「逐項回應批評」是防守不是攻擊。
    - ~~**③ 裁判守則單向傾斜 ← 最實質**~~ **已修（2026-07-30，alanchang `af3cd3e`）**：
      守則 1 改為雙向都要有結論，補「正方以具體事實擋下批評 → debate_adjustment 上調」
      的觸發條件；`debate_adjustment` 說明補「不對稱指的是幅度不是方向，
      批評大多不成立時 0 分是錯的答案」。
      ⚠️ **實證支持這條原本就被低估**：四次真實 Bedrock 執行的 `debate_adjustment`
      是 −10／−12／−6／−10，**全部為負**，「辯論後信心」實際上只是「辯論後扣分」。
      **修正只驗證過字串存在，正值到底會不會出現尚未實測**——已併入 tasks.md 9.7
      的驗收條件。原始記錄：守則 1 只保護反方（「不可略過批評直接採信正方」），
      無對等條款；且獎懲不對稱——反方批評成立明文要求**下修**，正方成功防守只換來
      「說明為何不採納」，**回到中性、沒有上修**。反方打中有收益，正方擋住沒有。
    - **④ 最後發言權**：每輪正方先反方後，且反方最末段無人反駁。`698a89e` 已在裁判
      守則補兩點讓裁判自行檢視，但沒有給正方反駁權。
    - **⑤ 收斂權只有反方有**（`has_new_points`）——同待辦 9①。
    - **⑥ 版面音量 2:1（Alan 範圍）— 部分處理，生成側仍在**：
      `report/view_builder.py:282-284` 與 `report/builder.py:92-100` 給反方兩個區塊
      （`bear_critique` + `bear_argument`）、正方一個。**讀者「感覺反方較強」有一部分
      純粹是字數造成的**，與論證品質無關。
      - ✅ 讀者側（alanchang `af3cd3e`）：多輪辯論前加版面說明「篇幅差異來自輸出結構
        而非論據強弱」，第 2 輪起正方標成「正方回應反方批評並修正論證」。
      - ✅ 裁判側（vic，本次）：裁判守則 3 補一句——反方兩段、正方一段是版面格式造成的，
        不可因字數較多就認為份量較重。**打分的是裁判，只對讀者揭露擋不住偏誤。**
      - ⬜ **生成側仍是 2:1**：`DEBATE_LENGTH_RULE` 對反方明訂「critique 與 argument
        分別計算，不是合計 600 字」＝反方 1200 字額度；正方第 2 輪要在同一個 600 字
        欄位裡同時做「逐項回應批評」與「完整論證」兩件事。
        **刻意不動**：600 是 Task 3.8 實測截斷踩出來的數字，改成 1200 只是為了讓比例
        好看、沒有任何實測依據，且會重新逼近截斷風險。要真正對稱的作法是 ② 的
        「給正方 critique 欄位」（動到 debate 契約），不是調字數。

    **撤回一項**：`debate_adjustment` 的 −15～+5 看似偏向反方，但 prompt 明講那是
    「對這份分析報告本身的信心調整，不是對市場的看多看空」，屬 ADR-5 刻意的防灌分
    設計，與正反方無關。它真正對應的問題已併入 ③。

    **建議順序**：~~先確認隊員看的版本 → 若仍成立，優先修 ③~~（③ 已於 2026-07-30 修完）
    → **下一步是 ②**（要給正方第 2 輪加 `critique` 欄位，動到 debate 契約與下游，較大），
    但 ② 動手前必須先有 9.7 的真實跑資料——①②④⑤ 至今**全部只有結構推論、沒有輸出實證**，
    而 ③ 的實證（四次全負）正是靠真實資料才浮出來的。

    ⚠️ **仍未回答**：上面「隊員看的是哪一次跑的輸出」到現在沒人回答，alanchang 在
    `af3cd3e` 的 commit 訊息裡也標明這題只有隊員能答。若那份輸出在 07-29 10:59
    （`698a89e`）之後仍成立，才需要動 ②；在那之前的話主因已除，再修會變成正方過強。

13. **`report.md` 有辯論重點摘要、四面板④ 沒有（Alan 範圍，2026-07-30 vic 複查發現）**：
    `3929328` 新增的 `debate_summary` 只接到 `report/builder.py`——報告現在把
    「## 辯論重點摘要」放在執行摘要之後、結論之前當作主要入口，但
    `report/view_builder.py:340-432` 的 `_build_panel4()` 是自己從 `conclusion`
    逐欄取值組出來的，**沒有 `debate_summary`**。結果是同一次執行的兩個交付面
    對「有沒有辯論重點摘要」講法不一致：`/result` 看得到、`/view/{run_id}` 面板④
    看不到，而面板④ 正是「分析報告」那一格。
    改法就是在 `_build_panel4()` 的回傳 dict 加一個欄位＋前端 `view.html` 補一段，
    屬於 `view_builder.py`／`webapp/` 的範圍。
    ✅ **已修（2026-07-31，alanchang `6bb862f`）**：`_build_panel4()` 加
    `debate_summary`（含 fingerprint）與 `summary.has_debate_summary`；有摘要時
    面板卡片改指向重點整理、不再整段倒貼正反方全文（與 report.md 同一套取捨），
    無摘要時維持原行為。實跑確認面板④已出現 5 點摘要。

14. **`debate_adjustment` 沒有鑑別度——七次真實執行有五次剛好是 −10（2026-07-31 alanchang）**：
    這是待辦 12 ③「四次全負」的後續。今天又跑三次，全部仍為負，且數值高度集中：

    | # | 題目主視野 | `debate_adjustment` | 備註 |
    |---|---|---:|---|
    | 1–4 | （歷史） | −10／−12／−6／−10 | vic 於 STATUS 12 記錄 |
    | 5 | structural | −10 | 移除 direction_matrix **之前** |
    | 6 | structural | −10 | 移除 direction_matrix **之後**（同一題） |
    | 7 | short | −10 | 換短視野題目 |

    **關鍵觀察不是「全負」，是「不同的辯論結果換得同一個分數」**：
    - 第 6 次：反方 3 點全成立、正方 0 點 → −10
    - 第 7 次：反方 3 點成立＋**正方 1 點有效**＋1 點雙方平手 → 仍然 −10

    裁判的**質性推理是紮實的**（第 7 次具體抓到正方拿收盤價迴避最低點、擠壓論
    缺價格支撐、算力矛盾未解釋，並明確寫出「正方對時間窗口的辯護部分有效」），
    問題在那個**數字沒有跟著質性判斷走**。`af3cd3e` 補的雙向守則在文字層有作用、
    在計分層沒有。

    **已排除的假設**：不是 `direction_matrix` 錨定造成的——移除前後同一題都是 −10
    （`6bb862f`）。

    **未排除、且無法只靠這批資料分辨的**：BTC 這一年跌 44%、現價跌破 MA60／MA120、
    近 10 日破前低，**反方在這兩題上本來就真的比較有理**。想用「正方有實料的題目」
    來分辨偏誤與正確行為的嘗試失敗了，因為當前盤勢本身偏空。要真正分辨，得挑一個
    **上漲中的幣種**或改用歷史某段多頭期間的題目。

    **找到一個具體嫌疑並已修（`prompts.py` 裁判區塊）**：裁判守則的散文要求雙向，
    但底下的 JSON 範例只示範了一個方向——
    ```
    "debate_adjustment": -8,
    "debate_adjustment_reason": "調整理由（例：反方對鏈上活躍度的批評成立，正方第二輪未有效回應）"
    ```
    **數字是負的、理由範例是反方獲勝**。這正是 vic 在 `8a30734` 修 `debate_summary`
    fallback 時用的同一套推理：模型抄格式範例的傾向強過讀散文。已補上兩個方向
    各一個具體範例（`-10` 與 `+3`）、把理由範例改成含上調案例，並明講
    「先數清楚哪幾點成立、再決定數字，不要先挑數字再補理由」。

    ⚠️ **這個假設只成立一半，別當定論**：若 `-8` 是強錨點，觀測值應該落在 -8，
    但實際七次是 -10（×5）／-12／-6。所以範例教會模型的比較像是**方向**
    （「負的才是正常結果」）而不是**數值**。真正的數值從哪來仍未知。

    **修完後第 8 次（同一題「最近一週」，`84aa0c9`）**：`debate_adjustment = -7`，
    理由寫「反方三項核心批評成立…**正方僅在量能解讀上擋住批評**但未能提供決定性證據」。
    這是八次裡**第一次數字跟著質性盤點走**——正方擋下一項，扣分就從 -10 減到 -7。
    同一題修改前是 -10（第 7 次），差別只有裁判區塊的範例。

    ⚠️ **n=1，不能當證實**：歷史上也出現過 -6，所以 -7 未必超出自然變異。
    要確認得再跑幾次同題比較分佈。但至少方向是對的：**問題從來不是「必須出現正值」，
    而是「數字要能分辨不同的辯論結果」**，這次它做到了。

    **仍待做**：換一個**上漲中的幣種**或多頭期間的題目，才能分辨「裁判偏空」
    與「這幾題反方本來就有理」。BTC 近一年 -44%、跌破 MA60／MA120、近 10 日破前低，
    用它測正方本來就不公平。

## 開發過程中的重要修正紀錄

- CoinDesk RSS 308 redirect → 加 `follow_redirects=True`
- Stooq 已加 JS 反爬蟲驗證 → 改用 Frankfurter 免 key 匯率 API
- Gemini 2.5 系列 thinking 佔用輸出額度導致空回應 → 關閉 thinking budget
- Gemini 免費層配額為「每專案每模型每日」計算，非帳號總量 → 建議獨立 GCP 專案；且需注意額度是綁「專案」不是綁「key」，換 key 不換專案沒有用
- Starlette 新版 `TemplateResponse` 簽名變更（`(request, name, context)`）→ 已配合更新呼叫方式
- Jinja `{{ obj.items }}` 會被解析成 dict 內建方法而非取 "items" key，導致四面板頁面 500 → 改用 `obj["items"]`
- **Bedrock `max_tokens=2048` 太低，辯論長論證輸出被截斷導致 JSON 解析失敗** → 提升到 4096，並補上 `stopReason`／空回應檢查給出明確錯誤訊息（而非讓呼叫端從 JSONDecodeError 自己猜原因）
- Bedrock 呼叫需要呼叫端 IAM 身份本身具備 `bedrock:InvokeModel` 權限，不是只有正式部署的 instance role 才需要——本機測試時容易忽略這點
- Claude Sonnet 5 在自助帳號被 `AccessDeniedException` 擋下（需聯繫 AWS Sales）；Claude 3.5/4 裸模型與其 region 推論設定檔都因「provider 標記為 legacy 且帳號無使用紀錄」被拒——最後選用 Sonnet 4.5 的日本專屬推論設定檔（`jp.anthropic...`）解決

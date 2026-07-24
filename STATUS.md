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
- 已知限制：**Reddit 會封鎖部分雲端/機房 IP（403），與程式碼無關**，會被正確標記 skipped 並在報告中揭露

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

1. **App Runner service 建立**（阻塞項，非程式問題）：ECR image 與 IAM role 都已就緒，但建立 service 被 AWS 帳號「Free plan」限制擋住（`SubscriptionRequiredException`），需要完成帳號驗證或升級方案才能繼續
2. **Live Demo 錄影**：決賽交付項目要求的現場執行錄製影片
3. **提案簡報**：解題方向、AI 技術應用、數據資料應用、AWS 架構圖（圖片形式）、Kiro 工作流截圖、AgentCore 取捨說明
4. **跟 Ken 對齊兩件事**：(a) `agent/collectors/relative.py` 與已合併進來的 `pipeline/compute_relative_strength.py` 功能重疊，需決定用誰的；(b) `static/source_reputation.json` 裡兩個暫定值（dedup 分級曲線、min_sample 門檻）需要校準定案
5. **news.py 命中則數改用去重後數量**：屬於 Kevin／Ken 的 collector 範圍，`origin/ken` 分支已合併，可以開始做
6. **衍生品 collector 正式實作**：Ken 目前只有獨立 prototype 腳本＋範例資料（`pipeline/fetch_*.py`），還沒包成 `agent/collectors/` 底下的正式 Collector、沒接進 orchestrator
7. **賽前完整排練**：用 Bedrock + 正式 App Runner 網址跑一次完整流程，確認時間與穩定性
8. **向主辦方確認比賽當日執行環境**：包括是否會提供官方 AWS 帳號（目前只是 Alan 的假設，PDF 未提及）、網路出口 IP（影響 Reddit/交易所地理封鎖）、Bedrock 帳號是否已預先開通。若確定要換成主辦方帳號，務必提前（非當天）用該帳號實際跑過一次完整流程，避免重踩這次自己帳號遇過的 Bedrock/IAM/App Runner 各種帳號層級的坑

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

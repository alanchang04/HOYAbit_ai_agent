# 完整盤點審計報告

> 產出日期：2026-07-18。純讀取審查，未修改任何專案檔案。
> 範圍：全部追蹤中原始碼（54 檔）＋ 2 個未追蹤文件（PITCH_REFERENCE.md、UPGRADE_SPEC_execution_logs.md）
> ＋命題 PDF＋資料集。`.env` 僅核對變數名稱；`.git`/`.venv`/`__pycache__` 不逐檔審查。

---

## 1. 檔案清單與盤點範圍

| 類別 | 內容 | 狀態 |
|---|---|---|
| 核心程式 | `agent/`（schemas、config、logging、orchestrator、collectors×7、reasoning×5、report） | 已逐檔審查 |
| 進入點 | `main.py`（CLI）、`webapp/app.py`＋templates＋static（Web UI） | 已審查 |
| 測試 | `tests/` 8 檔，**41 個測試本次重跑全數通過** | 已驗證 |
| 部署 | `Dockerfile`、`.dockerignore`（image 曾本機 build/run 驗證） | 已審查 |
| 設定 | `.env`（14 個變數，與 `.env.example` 名稱一致，含 1 個已填的 GEMINI_API_KEY——值未輸出） | 已核對名稱 |
| 資料集 | 5 幣種 CSV，欄位 `date,open,high,low,close,volume`，各 1,826 列，**2021-06-01 ~ 2026-05-31**，與 `dataset_metadata.json` 宣告一致 | 已驗證 |
| 文件 | README、STATUS、PITCH_REFERENCE、UPGRADE_SPEC_execution_logs（v2）、**DATA_SOURCES.md（隊友 Ken 的資料筆記，2026-07-09）** | 已審查 |
| 修改計畫 | UPGRADE_SPEC v2（execution log 可視化）＋ Ken 筆記中的待補項目 | 已逐項核對（§8） |

**盤點新發現**：Ken 的 `DATA_SOURCES.md` 指出兩個現有程式 bug（經核對原始碼**屬實**）：
1. `news.py` 的 `_matches_coin()` 用小寫短別名做子字串比對——`"eth"` 會誤中 method/synthetic、`"sol"` 誤中 solution/console，與 `coin_map.py` 的 `detect_coins_in_text()` 特別做過的大小寫敏感防護**不一致**。影響：ETH/SOL 的新聞證據可能混入無關文章。
2. `orchestrator.py` 的 `collect_all()` 是「每 collector × 每幣種」全積，macro（不分幣種）在比較題型會抓兩次，產生一模一樣的 Fear & Greed／匯率重複證據（實測 BTC vs ETH 報告中 ev-026/ev-028、ev-027/ev-029 確實重複）。影響：證據獨立性——評分明文觀察「避免同一來源重複引用」。

---

## 2. 命題文件解析（強制／加分／推測／未明確）

### 強制（PDF 明文）
| 要求 | 出處 |
|---|---|
| 針對指定幣種＋題目，限時蒐集/整理/分析，產出證據支撐的分析報告 | 命題說明 |
| 五項能力：多源整合、分層推理（事實→推論→結論）、不確定性說明、證據可回溯、洞察角度 | 參賽作品應展現 |
| 報告至少含：市場判斷、關鍵依據（來源+時間+解釋）、信心說明（含限制） | 題目模板 |
| Evidence 每筆至少：source、fetched_at、content_reference、related_claim（API 類需可回溯的 endpoint/參數/區間） | 提交項目 |
| Execution Log：任意格式，需時間戳、主要工具呼叫、資料取得紀錄、分析流程摘要 | 提交項目 |
| 15 分鐘上限；原則上一次正式執行機會 | 執行限制 |
| 不得把第三方完整市場判斷/交易訊號/買賣建議當主要結果；推理鏈由自有 agent 流程產生 | 資料規範 |
| 付費資料需揭露、不得為唯一關鍵依據 | 資料規範 |
| 決賽交付：提案簡報（含 AWS 架構圖）、**Live Demo 部署網址**＋現場執行錄影、GitHub、數據資源文件 | 決賽交付內容 |

### 加分（PDF 明文）
- **AWS Kiro 作為 AI 整合開發環境：+10%**（唯一被點名的具體加分項）
- 正反方分析、風險不確定性、後續觀察重點（「不強制，但納入推理品質觀察」）

### 推測（合理但 PDF 未明文，需確認出處）
- **「LLM 推理僅能用 Bedrock」——本 PDF 沒有這句話**。PDF 僅說參賽者可用自備 API key 存取「模型推理服務」（資料取得脈絡）、評分提到「若使用 AWS 服務…需展現合理架構」。此硬性限制來自你最初提供的比賽說明（大會總則層級，「違反即扣分或失格」）。**專案繼續按 Bedrock-only 執行（正確的保守做法），但建議向窗口 Mars Li 確認條款原文出處**，避免簡報引用時被挑戰。
- 比賽當日環境（網路、機器、AWS 憑證形式）：PDF 未描述，僅知「主辦方環境問題可重跑一次」。

### 未明確規定（不要誤判為硬性要求）
- **UI 不是硬性要求**（報告格式自由，Dashboard 只是選項之一）——但「Live Demo 部署網址」是決賽交付物，所以**某種可公開訪問的部署是必要的**，形式不限
- **AgentCore：全文未提及**，不是要求也不是加分
- 特定 AWS 服務組合（App Runner/EC2/Lambda）：未指定，僅簡報需架構圖

---

## 3. 目前系統實際行為（重建自原始碼）

```
main.py --coin BTC [--coin2 ETH] --question "..." [--dry-run]
 └─ run_pipeline()（orchestrator.py）
     ├─ 題型分類（關鍵字）→ comparison 時自動偵測/採用第二幣種
     ├─ Phase 1 蒐集：5 collectors × N 幣種 asyncio.gather 平行
     │    每 collector 獨立 75s timeout＋例外隔離；子來源層級備援
     │    （CoinGecko→CryptoCompare、EVM RPC 多端點、XRPL 多端點）
     ├─ Phase 2 證據化：全域統一分配 ev-NNN → evidence.json
     ├─ Phase 3 推理（LLM_BACKEND 決定 bedrock/gemini，同一 LLMClient 介面）：
     │    A 事實層 → B 交叉驗證 → C1 正方/C2 反方辯論（失敗退單模型 C）→ D 結論
     │    每步 JSON 輸出＋解析重試＋幻覺 evidence id 過濾
     │    整鏈失敗 → 誠實揭露失敗原因的降級報告（不崩潰）
     ├─ Phase 4 報告：report.md 五節；引用 id 強制存在性檢查
     └─ 全程 execution_log.jsonl（ts/phase/action/detail/status）；
        超過 12 分鐘門檻 → degraded mode 跳過蒐集（有單元測試）
```

- **已具備**：CLI ✅、Web UI（共用 run_pipeline）✅、Docker ✅、dry-run ✅、報告展示（result.html 顯示全文＋三檔下載）✅
- **尚無**：API-only endpoint（無 JSON API，僅表單 POST——夠用）、執行中即時狀態（同步阻塞執行）、execution log 的視覺化（UPGRADE_SPEC 的主題）
- 實測效能：真實跑 20–40 秒（Gemini），遠低於 15 分鐘；collectors 單獨 ~2 秒

---

## 4. 命題要求差異表

狀態：✅已完成｜🟡部分完成｜❌尚未完成｜❔無法確認
優先級：P0=比賽必要缺口｜P1=高價值展示/品質｜P2=加分優化

| # | 要求 | 狀態 | 現有證據 | 缺口/風險 | 優先級 | 驗收方式 |
|---|---|---|---|---|---|---|
| 1 | 多源資料整合（5 類） | 🟡 | 5 collectors 實測可跑 | social 受 Reddit 403 地理封鎖（雲端 IP 大概率也被擋）；news 僅 2 個 RSS 且 SOL/BNB 有「當日零命中」實例；**news 誤匹配 bug** | P0(bug)/P1(來源) | 修 bug 後以 5 幣種重跑 collectors 檢查證據相關性 |
| 2 | 分層推理（事實→推論→結論） | ✅ | 四步鏈＋辯論，3 題型真實驗證過 | 僅 Gemini 驗證，Claude 格式遵從度未驗 | P0 | Bedrock 上重跑 3 題型 |
| 3 | 不確定性與限制說明 | ✅ | 信心等級＋限制＋可推翻條件，實測輸出具體 | — | — | 抽查報告 |
| 4 | 證據可回溯 | 🟡 | schema 含全必要欄位＋query 參數；報告 id 強制檢查 | 無原文快照/雜湊；比較題 macro 重複證據損害「來源獨立性」 | P1(重複)/P2(快照) | 修重複後檢查 evidence.json 無重複；快照屬 UPGRADE_SPEC |
| 5 | 洞察角度 | ✅ | 辯論交鋒、技術指標、跨來源矛盾偵測實例 | Ken 的雙幣相對指標/衍生品構想可再強化 | P1/P2 | 新指標逐項 dry-run＋實測 |
| 6 | 報告三必要章節 | ✅ | report.md 五節結構 | — | — | — |
| 7 | Evidence List 格式 | ✅ | evidence.json 符合 schema | — | — | — |
| 8 | Execution Log 格式 | ✅ | jsonl 含時間戳/工具/狀態 | 可視化升級屬加分（UPGRADE_SPEC） | P1 | — |
| 9 | 15 分鐘/一次執行穩定性 | 🟡 | 20-40s 實測；隔離/備援/degraded 有測試 | **Bedrock 路徑零實測**；比賽環境網路未知 | **P0** | Bedrock 端到端＋部署環境實測 |
| 10 | 不用第三方完整判斷 | ✅ | 全部原始數據＋自有推理鏈 | — | — | — |
| 11 | LLM 僅 Bedrock（依你的簡報） | ❌ | 抽象層＋警告機制已備；BedrockClient 已寫 | **從未成功呼叫過 Bedrock**（帳號未開通） | **P0（唯一技術阻塞）** | `check_llm.py` 通過＋完整 pipeline 跑通 |
| 12 | Live Demo 部署網址 | ❌ | Docker image 驗證可用；App Runner 步驟已文件化 | 未實際部署 | **P0** | 公網 URL 跑通一次 |
| 13 | 現場執行錄影 | ❌ | — | 未錄 | P0（賽前） | 影片連結 |
| 14 | 簡報＋AWS 架構圖（圖檔） | 🟡 | PITCH_REFERENCE.md 素材＋ASCII 圖 | 需畫正式圖、做簡報 | P0（賽前） | 簡報成品 |
| 15 | AWS Kiro（+10%） | ❌ | 未使用 | **白放棄的 10%**——需團隊決策 | 決策點 | 簡報展示 Kiro 使用證據 |
| 16 | 付費資料揭露 | ✅ | 全免費來源；CryptoPanic 選用且標註揭露 | — | — | — |
| 17 | 報告語言（繁中） | ✅ | 實測輸出繁中、引用保留英文原文 | — | — | — |

**比賽必要缺口總結（P0）**：Bedrock 實測（#11，阻塞 #2/#9）、實際部署（#12）、news 誤匹配 bug（#1，會污染證據品質）、錄影/簡報（#13/#14，賽前完成即可）。
**展示/加分（P1/P2）**：execution log 四面板、macro 重複修正、雙幣相對指標、Kiro 決策、其餘 Ken 構想。

---

## 5. Gemini → Bedrock 切換策略驗證

### 5.1 介面中立性：真正中立 ✅

`LLMClient` 介面只有 `converse(system_prompt, user_prompt, max_tokens) -> str`——純文字進出。我們**不使用** tool calling、streaming、原生 structured output（JSON 靠 prompt 約定＋`extract_json()` 正則容錯＋一次格式重試），所以兩個 provider 之間**沒有功能面的耦合**。`pipeline.py` 對 backend 零感知，切換僅動 `.env`。

### 5.2 逐項差異核對

| 面向 | Gemini（已實測） | Bedrock（未實測） | 風險/對策 |
|---|---|---|---|
| 認證 | API key（env） | **boto3 預設憑證鏈**：env keys → `~/.aws` → **IAM role**。App Runner 用 instance role（無金鑰落地）、本機用 `aws configure` | 比賽環境較可能給 IAM role/臨時憑證而非 API key——現有 boto3 寫法天然支援，無需改碼 ✅ |
| 模型 ID | `gemini-2.5-flash` | `anthropic.claude-3-5-sonnet-20241022-v2:0`——**部分帳號/region 需改用 inference profile（`us.anthropic....`）** | `check_llm.py` 第一時間暴露；切換清單列入 |
| 輸入輸出 | generate_content(text)→text | converse(messages)→text，**回應解析路徑已寫好但未驗證** | 煙霧測試即可確認 |
| structured output | prompt 約定 JSON（實測遵從佳） | 同一套 prompt；Claude 對「只輸出 JSON」遵從度通常更好，但**需實測確認**，`extract_json` 的 code-fence 容錯兩邊通用 | Bedrock 驗證跑 3 題型各一次 |
| max_tokens | 2048（實測辯論長文未截斷） | 2048 可能偏緊（Claude 傾向更長論述）；**現有程式未檢查 `stopReason`** | 建議：切換驗證時觀察，必要時升 4096＋補 stopReason 檢查 |
| context window | 1M | 200K | 實際 prompt 峰值（雙幣 29 證據＋辯論史）粗估 <15K tokens，兩者都遠夠 ✅ |
| 限流 | 免費層 20 req/天（已兩度撞牆） | on-demand TPM/RPM 配額；**新帳號對 Claude 3.5 Sonnet 配額可能偏低** | 單次執行僅 5-7 call，正常夠用；既有 3 次 exponential backoff 可擋偶發 throttle；賽前確認帳號配額 |
| usage 統計 | 有 metadata（未採集） | `converse` 回傳 `usage`（未採集） | P1：兩邊都補採集（UPGRADE_SPEC §11.8） |
| 串流 | 未用 | 不需要 | — |

### 5.3 三份清單

**賽前 Gemini 例行測試**（維持現狀能力，注意每日 20 次額度）：
`pytest -q`（離線 41 測試）→ `scripts/test_collectors.py --coin <X>`（不耗 LLM）→ 必要時一次真實 pipeline。

**Bedrock 最小煙霧測試**（開通後第一件事，約 10 分鐘）：
1. `.env`：`LLM_BACKEND=bedrock`、`AWS_REGION`、`BEDROCK_MODEL_ID`
2. 憑證就緒（`aws sts get-caller-identity` 確認身分）
3. `python scripts/check_llm.py` → 期望「連線成功」；若 ValidationException 提及 on-demand 不支援 → 改用 inference profile ID 重試
4. 一次真實 pipeline（BTC 多源整合）→ 檢查 report.md 五節齊全、evidence 引用、耗時、log 無 JSON 解析重試

**比賽當日切換清單**：
1. `.env` 三變數確認（backend/region/model id）＋憑證生效
2. `check_llm.py` 通過
3. `--dry-run` 一次（確認檔案系統/輸出目錄正常）
4. 用練習題真實跑一次（確認格式遵從、耗時、無截斷、無 throttle）
5. 清空 `output/`，正式執行
6. 保底方案：若 Bedrock 現場異常，degraded 報告仍會產出三檔案——但**不可**臨場切回 gemini（違規）

---

## 6. UI 與 AgentCore 評估

### 6.1 前提釐清
- 命題**不要求 UI**；但**要求 Live Demo 部署網址**（決賽交付物）→ 需要某種可公開訪問的東西
- **AgentCore 是 agent 基礎設施（Runtime 託管/Memory/Gateway 工具閘道/Identity/Observability 追蹤/Browser/Code Interpreter），不是終端使用者 UI**——就算全套接上，評審看到的畫面仍需自己做（Streamlit/Gradio/現有 FastAPI）

### 6.2 三方案比較

| 方案 | 成本 | 競賽價值 | 判定 |
|---|---|---|---|
| 不做 UI（CLI＋靜態報告頁） | 0（現有 result.html 已超過此標準） | 勉強滿足 demo 網址，展示力弱 | 不採 |
| **最小展示 UI＋execution log 四面板升級** | 中（前端為主，後端 view_builder；UPGRADE_SPEC 已規格化，dry-run 假資料可先行開發前端） | 高——「信任提煉流水線」可視化直接對應命題主題與評分的透明化要求；完成度/商業應用性直接加分 | **✅ 採用** |
| AgentCore 整合 | 高——自刻 pipeline 需重新包裝進 Runtime；Observability 與自建 log 可視化功能重疊；學習曲線＋新故障面 | 低——命題未提及、不加分；Observability 的 trace 畫面反而不如自建四面板貼題（我們要展示的是「信任提煉」語意，不是 infra trace） | ❌ 本屆不採；簡報「未來規劃」一句帶過即可 |

### 6.3 被忽略的真加分：AWS Kiro（+10%）
命題唯一點名的加分是「採用 AWS Kiro 作為 AI 整合開發環境」。目前完全未使用＝白放棄 10%。
**建議決策**：接下來的開發（例如 execution log 四面板前端）改在 Kiro 中進行部分工作、保留 spec/截圖證據，成本低、名目成立。**需要你們團隊決定**。

---

## 7. 資料來源與可追溯性審查

### 7.1 現役來源可靠度（實測記錄為準）

| 來源 | 授權/成本 | 限流 | 實測狀態 | 失效風險 |
|---|---|---|---|---|
| 主辦方 CSV＋本地技術指標 | 官方提供 | 無（本地） | ✅ 穩定 | 零（最可靠證據源）；注意資料止於 2026-05-31，與執行日有時間差，推理已能正確處理並揭露 |
| CoinGecko `/simple/price` | 免費層 | ~10-30 req/min | ✅ | 中；備援 CryptoCompare 已接 |
| Blockchair／EVM RPC／Solana RPC／XRPL | 公開免 key | 各自寬鬆 | ✅ 5 鏈全通 | 中；EVM/XRPL 已多端點備援 |
| CoinDesk/Cointelegraph RSS | 公開 | 無明確 | ✅（曾修 308 redirect） | 中；單日命中數不穩（SOL/BNB 有零命中日）→ Ken 建議把「命中則數」本身輸出為關注度證據 |
| Reddit 公開 JSON | 公開 | — | ❌ 本機/機房 IP 403 | **高**；App Runner IP 大概率同樣被擋。對策：接受並誠實揭露（現行），或改官方 OAuth API（免費 app 憑證，P1 可選） |
| alternative.me F&G／Frankfurter | 公開免 key | 寬鬆 | ✅ | 低；Ken 提議 `limit=30` 升級成百分位（一行改動，P1） |

### 7.2 Ken 筆記中的擴充構想審查（`DATA_SOURCES.md`）

方向正確且紀律原則（garnish 不是主菜、每源都是出包點）與本審計一致。優先序評估：
- **CSV 再榨（雙幣相對指標：相關係數/beta/最大回撤/相對強弱位置）**：零 API 風險、純本地、直接補「比較題唯一可量化共同尺度」缺口——**P1，最值得先做**
- 微結構流動性（Kraken/Coinbase 深度）：免 key、不擋美國 IP，「流動性」直接命中題目字面——P1/P2
- 衍生品（Hyperliquid/Binance funding、OI）：洞察力強，但**Binance 擋美國 IP** → 牽動 App Runner region 決策（us-east-1 vs ap-northeast-1），需先實測再定——P2，賽前有餘裕才上
- 事件日曆預快取／穩定幣供給／BTC dominance：低風險 garnish——P2
- 月相/週間效應：當「可證偽性展示」放限制欄的用法聰明，但屬彩蛋——P2 末位

### 7.3 RAG 的正確角色（回應你的分工）
RAG（同伴負責）能做：檢索補充證據、對 claim 找佐證/反證（`rag_verified`/`rag_support` 欄位已在 UPGRADE_SPEC §4.1 預留）。
RAG **不能取代** provenance：完整追溯還需要——來源 URL＋query 參數（✅已有）、抓取時間（✅已有）、原文片段（✅已有 content_reference）、引用 ID（✅ ev-NNN）、執行紀錄（✅ jsonl）、**原文快照與內容雜湊（❌未有，P2）**、資料版本（CSV 有 metadata ✅）。結論：現有可追溯性已滿足 PDF 最低要求，快照/雜湊屬 UPGRADE_SPEC 的強化項而非合規缺口。

---

## 8. 可視化與修改計畫審查（P0/P1/P2 定級）

核對對象：UPGRADE_SPEC_execution_logs.md（v2）＋ Ken 待補清單。結論：**方向正確、與比賽規則無衝突（v2 已修正 v1 兩處合規風險）、但它整份屬 P1/P2——不可排在 P0 之前**。

| 項目 | 出處 | 定級 | 說明 |
|---|---|---|---|
| Bedrock 煙測＋全題型驗證 | STATUS | **P0** | 唯一技術阻塞 |
| ECR＋App Runner 實際部署 | STATUS | **P0** | Live Demo 交付物 |
| news `_matches_coin` bug 修復 | Ken | **P0** | 直接影響證據正確性，改動小（比對邏輯對齊 coin_map） |
| 錄影＋簡報＋架構圖 | STATUS | **P0**（賽前） | 交付物 |
| macro 比較題重複抓取修復 | Ken | **P1** | 證據獨立性；改動小（macro 只跑一次） |
| schemas/logger 擴充（weight/layer/metrics） | SPEC §4 | **P1** | 四面板地基，向後相容 |
| view_builder＋report_view.json＋dry-run 假資料 | SPEC §6/§9 | **P1** | 你的主戰場；先假資料讓前端平行開發 |
| 四面板前端＋Raw Log 分頁 | SPEC §2/§6 | **P1** | 展示核心 |
| 雙幣相對指標（CSV 本地計算） | Ken | **P1** | 比較題共同尺度缺口 |
| L1 權重（靜態表）＋L3 剔除統計＋數值信心公式＋token 採集 | SPEC §5/§11 | **P1** | 純程式、低風險 |
| PR 話術＋模板相似度（英文詞典） | SPEC §5 L2 | **P1 後段** | 純本地；詞典從小做起 |
| F&G limit=30、新聞命中數量化 | Ken | **P1 後段** | 一行級改動 |
| 未過濾基準對照面板（多一次 LLM call） | SPEC §8 | **P2** | 可開關；Demo 錄影時才開 |
| 情緒分布 F9（英文詞典品質難保證） | SPEC §5 | **P2** | 與同伴 RAG 分工待定（SPEC §11.7） |
| 衍生品/微結構 collector | Ken | **P2** | 需部署環境實測地理封鎖後再定 |
| 原文快照＋雜湊 provenance | 本審計 §7.3 | **P2** | 合規已達標，此為強化 |
| Reddit 官方 OAuth API | 本審計 §7.1 | **P2** | 或維持誠實揭露 |
| AgentCore | — | **不做** | §6.2 |

**過重架構警示**：SPEC 的 L2 內容層若走 LLM 或引入 ML 情緒模型即屬過重——維持純詞典/相似度；四面板前端先吃 dry-run 假資料，避免開發期消耗 LLM 額度；`report_view.json` schema 儘早凍結（v1.0）讓前後端解耦。

---

## 9. 其他風險與待確認問題

1. **「Bedrock-only」條款原文出處**——向主辦確認（§2）；在確認前繼續按硬性限制執行
2. **比賽當日執行環境**：自帶筆電或主辦環境？網路出口 IP？（影響 Reddit/交易所地理封鎖、及是否需預先部署好一切）
3. **正式資料包是否更新**：目前 CSV 止於 2026-05-31；比賽日若給新資料包，路徑/檔名格式需確認不變
4. **App Runner region**：若要上衍生品資料（Binance 擋美 IP）→ 考慮 ap-northeast-1（該區也有 Claude）；不上則 us-east-1 最單純。**這個決策卡在衍生品要不要做，建議儘早定**
5. **Bedrock 帳號配額**：新帳號對 Claude 3.5 Sonnet 的 on-demand 配額可能偏低，開通後順手確認
6. **Gemini 排練額度**：每日 20 次（已兩度撞牆）——排練用 dry-run＋離線測試為主
7. **Kiro +10% 要不要拿**：團隊決策（§6.3）
8. **SPEC §11.7 內容層分工**：PR/模板歸誰、情緒歸誰，與同伴儘早定案
9. `check_llm.py` 未涵蓋 `stopReason`/截斷檢查——併入 Bedrock 驗證時處理

---

## 10. 分階段修改計畫（提案，待你確認後才動檔案）

### Phase 0：小 bug 修復（半天內，不依賴任何外部條件）
1. `news.py` 幣種比對邏輯對齊 `coin_map.py`（大小寫敏感 ticker＋全名別名）＋新增誤匹配回歸測試
2. `orchestrator.py` 比較題型 macro 只抓一次＋測試（比較題 evidence 無重複）

### Phase 1：P0 比賽必要（依賴：Bedrock 開通、AWS CLI 憑證）
3. Bedrock 煙測（§5.3 清單）→ 必要時補 inference profile ID／`stopReason` 檢查／max_tokens 調整
4. Bedrock 全題型端到端驗證（3 題型 × 代表幣種）
5. ECR push ＋ App Runner 部署（region 依 §9-4 決策）＋公網 URL 端到端
6. Demo 錄影、簡報、架構圖（人工為主，我出素材）

### Phase 2：P1 展示升級（可與 Phase 1 平行，前端先行）
7. schemas/logger 擴充 → dry-run 假 `report_view.json` → view_builder → 四面板＋Raw Log 前端
8. 雙幣相對指標（CSV 本地）＋ L1 權重表 ＋ L3 剔除統計 ＋ 數值信心公式 ＋ token 採集
9. F&G 30 天百分位、新聞命中數量化、PR/模板過濾（英文詞典）

### Phase 3：P2 選配（賽前有餘裕才做，逐項過 dry-run＋部署環境實測）
10. 基準對照面板（可開關）、情緒詞典或 RAG 情緒、微結構/衍生品 collector、快照雜湊、Reddit OAuth

---

*本審計未修改任何專案檔案。Phase 0-3 每一項動工前都會先經你確認。*

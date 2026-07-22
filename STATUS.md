# 專案進度說明（HOYA BIT 2026 雲湧智生黑客松）

> 最後更新：2026-07-08

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
- `news`：每幣官方發布源優先（2026-07-20 改版，取代原 CoinDesk／Cointelegraph 全站 RSS＋別名過濾）——BTC/ETH/SOL 走官方 RSS，BNB/XRP 無官方 RSS 退階解析官方頁面
- `social`：Reddit 公開 `.json` 搜尋端點
- `macro`：Fear & Greed Index ＋ Frankfurter 匯率（美元強弱代理），有 FRED key 時疊加美債殖利率
- 已知限制：**Reddit 會封鎖部分雲端/機房 IP（403），與程式碼無關**，會被正確標記 skipped 並在報告中揭露

### Stage 3：LLM backend 抽象層與四步推理鏈
- `agent/reasoning/llm_client.py`：`LLMClient` 介面 ＋ `build_llm_client()` 工廠，依 `.env` 的 `LLM_BACKEND` 切換
  - `bedrock`：**競賽正式規定唯一合法後端**（`bedrock_client.py`，含 exponential backoff retry）
  - `gemini`：開發階段暫代後端（`gemini_client.py`），已修正 Gemini 2.5 系列 thinking token 佔用輸出額度導致空回應的問題
- `agent/reasoning/pipeline.py`：事實層 → 交叉驗證層 → **推論層（正方分析師 vs 反方分析師辯論）** → 結論層（含後續觀察重點）
  - 反方可看到正方論證並具體批評其漏洞，而非各說各話
  - 辯論任一步失敗會退回單模型一次產出多假設的 fallback，不影響整體穩定性
  - 所有步驟的 evidence id 引用都會過濾模型幻覺，避免拖垮後續報告檢查
  - 推理鏈整體失敗（LLM 呼叫或解析）都會被 orchestrator 捕捉，退化為誠實揭露失敗原因的報告，不會讓程式崩潰
- 支援三種題型分支（多源整合／假設驗證／比較分析），比較分析會自動偵測題目中的第二幣種並雙幣種平行蒐集，辯論框架改為「正方挺 coin、反方挺 coin2」的具體對抗

### Stage 4：報告生成
- `agent/report/builder.py`：組裝 `report.md`（結論／關鍵依據／正反方辯論與矛盾訊號／信心說明／後續觀察重點），強制檢查引用的 evidence id 必須存在，比較分析題型標題與內容會標示雙幣種

### Stage 5：整合測試
- 5 幣種（BTC/ETH/SOL/BNB/XRP）collector 皆重新驗證，2 秒內完成
- 真實 LLM 端到端驗證：BTC 多源整合、BTC 假設驗證、BTC vs ETH 比較分析，皆在 40 秒內完成、品質良好
- Degraded mode（超時跳過剩餘蒐集）與跨 5 幣種推理鏈離線測試（FakeLLMClient，不耗真實額度）
- 41 個 pytest 全數通過

### Stage 6：Web UI 與 Docker（部分完成）
- `webapp/app.py`：FastAPI Web UI，與 CLI 共用同一個 `run_pipeline()`
- Dockerfile／`.dockerignore`：本機已驗證 build 成功、容器內真實 collector 網路連線正常
- README 已補上 AWS 架構圖（文字版）與 App Runner 部署步驟（指令腳本）

## 尚未完成 / 待辦

1. **Bedrock 存取確認**（阻塞項）：目前仍卡在 AWS Bedrock model access 開通，開發期間用 `LLM_BACKEND=gemini` 暫代驗證
2. **用 Bedrock 做最終端到端驗證**：目前所有真實 LLM 測試都是用 Gemini 跑的，Bedrock 開通後需要重新跑一輪確認 Claude 在同樣的 prompt 下輸出品質、格式遵從度沒有落差
3. **實際部署到 AWS App Runner**：Docker image 已驗證可用，但還沒真的 `docker push` 到 ECR、建立 App Runner service（README 已有完整指令，等 AWS CLI 存取確認後即可執行）
4. **Live Demo 錄影**：決賽交付項目要求的現場執行錄製影片
5. **提案簡報**：解題方向、AI 技術應用、數據資料應用、AWS 架構圖（圖片形式，README 目前只有文字 ASCII 圖）
6. **賽前完整排練**：用 Bedrock + 正式 App Runner 網址跑一次完整流程，確認 10 分鐘內完成、無需人工介入
7. （加分項，非必要）Gemini 額度限制導致部分幣種×題型組合尚未用真實 LLM 逐一驗證，已用離線測試補足邏輯正確性，正式驗證建議在 Bedrock 上一次做完

## 開發過程中的重要修正紀錄

- CoinDesk RSS 308 redirect → 加 `follow_redirects=True`
- Stooq 已加 JS 反爬蟲驗證 → 改用 Frankfurter 免 key 匯率 API
- Gemini 2.5 系列 thinking 佔用輸出額度導致空回應 → 關閉 thinking budget
- Gemini 免費層配額為「每專案每模型每日」計算，非帳號總量 → 建議獨立 GCP 專案
- Starlette 新版 `TemplateResponse` 簽名變更（`(request, name, context)`）→ 已配合更新呼叫方式

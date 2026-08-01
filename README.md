# 加密市場分析 AI Agent（HOYA BIT 2026 雲湧智生黑客松）

多源資訊信任提煉系統：針對指定幣種與題目，在時限內蒐集價格／鏈上／新聞／社群／總經資料，
產出具備分層推理（事實 → 交叉驗證 → 推論 → 結論）與可回溯證據的市場分析報告。

> **目前版本：v1.1（可回退的正式展示版）**。六類真實 collector、信源權重／去重、
> 正反方多輪辯論、可解釋信心、Web UI、Docker、AWS Bedrock 與 EC2 公開部署均已實測。
> v2 將依 `11流程圖模板.md` 另行開發；本 README 描述的是目前可用的 v1.1。

## 安裝

```bash
py -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
cp .env.example .env   # 之後依需求填入 API key / Bedrock 設定
```

## 執行

```bash
# dry-run：賽前排練，不打真實 API/LLM
.venv/Scripts/python.exe main.py --coin BTC --question "分析 BTC 過去兩週的市場表現..." --dry-run

# 正式執行：真實 collector + LLM 推理（LLM_BACKEND 依 .env 設定）
.venv/Scripts/python.exe main.py --coin BTC --question "分析 BTC 過去兩週的市場表現..."

# 比較分析題型：--coin2 可省略，會自動從題目文字偵測第二個幣種
.venv/Scripts/python.exe main.py --coin BTC --question "比較 BTC 與 ETH 在流動性與風險敞口上的差異..."
```

輸出於 `output/` 目錄：

- `report.md`：分析報告
- `evidence.json`：證據清單
- `execution_log.jsonl`：執行紀錄
- `report.html`：Final Report 的 standalone 離線閱讀版
- `evidence.html`：Evidence List 的 standalone 離線閱讀版
- `execution_log.html`：Execution Log 的 standalone 離線閱讀版
- `deliverables.html`：評審交付物索引與原始檔／HTML 對照

前三份原始檔仍是權威、機器可讀的正式交付物；HTML 只是方便評審直接用瀏覽器閱讀的補充。
Source / Config 則以 GitHub repository、`README.md`、`.env.example` 與原始碼樹交付，不以 HTML 取代。

### 決賽提交檢查

依命題文件，最終提交不能只交單次分析輸出，應包含以下四項：

1. 提案簡報：以 `PITCH_REFERENCE.md` 為內容底稿，正式提交投影片或 PDF；須涵蓋解題方向、AI 技術應用、數據資料應用與 AWS 架構圖。
2. Live Demo 部署網址及現場執行錄製影片連結。
3. GitHub 連結：完整原始碼、設定檔與執行說明。
4. 數據與資源文件：每次正式執行產生的 Final Report、Evidence List、Execution Log；`deliverables.html` 會列出原檔與 HTML 閱讀版對照。

其中第 4 項可附 HTML 閱讀版；第 1 項仍以投影片／PDF 交付，第 2 項是網址與影片，第 3 項必須保留可執行的 GitHub repository，不能只轉成 HTML。

## LLM backend

`.env` 的 `LLM_BACKEND` 控制推理鏈實際呼叫哪個模型：

- `bedrock`（**競賽正式規定唯一合法後端**，正式執行/繳交前必須是這個）
- `gemini`（僅供尚未取得 Bedrock 存取權限前的開發階段暫代測試 prompt 用；CLI 執行時若偵測到非 bedrock 會印出醒目警告提醒切換）

```bash
.venv/Scripts/python.exe scripts/check_llm.py   # 驗證目前設定的 backend 是否能連線
```

## 測試

```bash
.venv/Scripts/python.exe -m pytest -q
```

## Web UI（本機）

與 CLI 共用同一個 `agent/orchestrator.py` 的 `run_pipeline()`，不是兩套邏輯。

```bash
.venv/Scripts/python.exe -m uvicorn webapp.app:app --host 0.0.0.0 --port 8000
```

開啟 http://localhost:8000 ，填入幣種／題目（比較分析可留空第二幣種讓系統自動偵測）、
可勾選 dry-run。執行完成後頁面會顯示完整 `report.md` 內容，並提供原始交付檔及 standalone HTML 閱讀版的下載連結。
`GET /healthz` 供 EC2 服務與外部監控做健康檢查。

首頁提供「一鍵觀看信任提煉 Demo」：使用明確標記的 dry-run 假資料注入重複轉載與
拉盤話術，約 1 秒完成，可直接對照 Baseline、去重與降權結果，不消耗 Bedrock 額度。
分析頁預設先顯示投資者一頁摘要；完整四面板、逐輪辯論與 Evidence 可再展開。

完整性分成三種狀態：`INTACT`（六類齊全）、`PARTIAL`（流程完成但缺整類資料）、
`DEGRADED`（deadline、推理或管線層失敗）。

## Docker

```bash
docker build -t hoyabit-agent .
docker run --rm -p 8000:8000 --env-file .env hoyabit-agent
```

開啟 http://localhost:8000 即可使用，行為與本機執行 Web UI 完全相同。CLI 也可以在容器內執行：

```bash
docker run --rm --env-file .env hoyabit-agent \
  python main.py --coin BTC --question "..." --dry-run
```

## 驗證真實 collector（Stage 2，不經過推理/報告）

```bash
.venv/Scripts/python.exe scripts/test_collectors.py --coin BTC
```

會平行執行六類真實 collector 並印出各自取得的證據與總耗時，方便賽前確認各資料來源是否可連線。

### 各 collector 資料來源與已知限制

| Collector | 主要來源（免 key） | 備援 / 補充 | 已知限制 |
|---|---|---|---|
| price | 主辦方 OHLCV CSV（`data/`）＋已驗證 `raw_data/price/` 快取＋本地技術指標＋CoinGecko `/simple/price` | 快取後仍缺日才依序用 Coinbase Exchange USD、Binance Spot USDT；即時報價用 CryptoCompare | 快取必須保留官方前綴且符合 manifest；當日未收盤 UTC 日 K 一律剔除；官方 CSV 保持不可變 |
| onchain | BTC: Blockchair／ETH: publicnode EVM RPC／BNB: bsc-dataseed RPC／SOL: Solana 公開 RPC／XRP: XRPL 公開 JSON-RPC | Etherscan/BscScan（需免費 key，補充總供給量） | 免 key 端點僅提供區塊高度、Gas、TPS 等網路層指標，非地址級鏈上活躍度，如需更細緻指標建議申請 Etherscan/BscScan key |
| news | 每幣官方發布源：BTC Bitcoin Optech Newsletter／ETH Ethereum Foundation Blog／SOL Solana Foundation News（皆 RSS）／BNB BNB Chain Blog／XRP Ripple Insights（無 RSS，退階 HTML 解析） | 無 | 2026-07-20 起改為官方源優先，不再用 CoinDesk/Cointelegraph/CryptoPanic 第三方聚合；BNB/XRP 無官方 RSS，HTML 結構若改版會失效；BTC 無單一官方實體，只有 Optech 一條技術公告管道 |
| social | Reddit `r/<subreddit>/search.json` | 無 | **已知限制：Reddit 會封鎖部分雲端/機房 IP（回傳 403），與 User-Agent 無關。** 若比賽現場網路環境被封鎖，此來源會被標記 skipped，報告中需揭露社群資料缺失 |
| macro | Fear & Greed Index（alternative.me）＋ Frankfurter 匯率（USD 強弱代理） | FRED 10年期美債殖利率（需免費 key） | 無 |

單一來源失敗（如 Reddit 403）不會中斷整體流程，會記錄於 `execution_log.jsonl` 並在報告中揭露該類資料缺失。

## Agent 架構

```
                        ┌───────────────────────────┐
 CLI (main.py)          │  agent/orchestrator.py    │
 --coin / --question ──▶│  run_pipeline()           │
 --dry-run              │  （計時、deadline 控管）   │
                        └────────────┬──────────────┘
                                     │
        ┌────────────────────────────────────────────────────┐
        │ Phase 1：資料蒐集（asyncio.gather 平行執行）          │
        │                                                      │
        │  price_collector    ─┐  各自獨立 timeout（預設75秒）   │
        │  onchain_collector  ─┤  + try/except 隔離             │
        │  news_collector     ─┤  失敗 → 記 execution_log       │
        │  social_collector   ─┤     並標記 skipped/error       │
        │  macro_collector    ─┘  （不中斷其他 collector）       │
        └────────────────────────┬─────────────────────────────┘
                                  │ list[EvidenceDraft]
                                  ▼
        ┌──────────────────────────────────────────┐
        │ Phase 2：證據化                            │
        │ assign_evidence_ids()                     │
        │ → 統一分配 ev-001, ev-002... → evidence.json│
        └────────────────────────┬───────────────────┘
                                  │ list[Evidence]
                                  ▼
        ┌──────────────────────────────────────────┐
        │ Phase 3：分層推理（agent/reasoning/）        │
        │ prompts.classify_question_type()          │
        │   → 多源整合 / 假設驗證 / 比較分析           │
        │   （比較分析會自動偵測題目中的第二幣種，        │
        │    Phase 1 平行蒐集兩幣種證據）              │
        │ pipeline.run_reasoning()                  │
        │   事實層 → 交叉驗證層                        │
        │   → 推論層：正方分析師 vs 反方分析師辯論        │
        │     （反方可見正方論證並具體批評，失敗時         │
        │      退回單模型一次產出多假設）                │
        │   → 結論層（含後續觀察重點）                   │
        │   （llm_client.py：bedrock 或 gemini）      │
        └────────────────────────┬───────────────────┘
                                  │ ReasoningResult
                                  ▼
        ┌──────────────────────────────────────────┐
        │ Phase 4：報告生成（agent/report/builder.py）│
        │ 組裝 report.md，強制檢查引用的 evidence id   │
        │ 必須存在於 evidence.json（否則 fail fast）   │
        └────────────────────────┬───────────────────┘
                                  ▼
              report.md ／ evidence.json ／ execution_log.jsonl
```

**設計重點：**
- **Orchestrator 是自刻的輕量 asyncio pipeline**（不用 LangGraph/Strands），理由是 15 分鐘硬性 deadline 下需要精確控制「哪個 collector 超時該直接跳過」「幾分鐘後進入 degraded mode」，框架的抽象層在這種場景下反而增加除錯與相依風險。
- **失敗隔離發生在兩層**：collector 層級（`agent/collectors/base.py` 的 `run()`）與單一 collector 內的子來源層級（如 price_collector 內 CoinGecko 失敗會退 CryptoCompare，但不影響同一 collector 已取得的本地 CSV 證據）。
- **evidence id 是全域統一分配**（Phase 2），不是各 collector 自行編號，避免跨 collector id 衝突，也讓 Phase 4 的引用檢查可以用一個簡單的集合比對完成。
- Web UI（Stage 6）與 CLI 共用同一個 `run_pipeline()`，不會有兩套邏輯。

## 專案結構

```
agent/
  config.py            # .env 載入、選用 API key 缺漏檢查
  logging_utils.py      # execution_log.jsonl 寫入
  schemas.py             # Evidence / LogEntry pydantic schema
  orchestrator.py        # Phase 1-4 控制、15 分鐘 deadline 與 degraded mode
  collectors/            # 各資料來源 collector（base.py 提供 timeout/失敗隔離）
    coin_map.py            # 幣種代號對照各來源 id/別名/所屬鏈，detect_coins_in_text() 自動偵測第二幣種
    price.py / onchain.py / news.py / social.py / macro.py
    dry_run.py             # --dry-run 用假資料 collector
  reasoning/
    llm_client.py           # LLMClient 介面 + build_llm_client() backend 工廠
    bedrock_client.py        # Bedrock 實作（競賽正式後端）
    gemini_client.py         # Gemini 實作（開發階段暫代後端）
    prompts.py               # 四步推理 prompt 模板、題型分支、正反方 framing
    pipeline.py               # 四步推理鏈組裝（含辯論與 fallback）
  report/                 # report.md 組裝與 evidence 對應檢查
  fixtures/               # --dry-run 用假資料
webapp/
  app.py                    # FastAPI：與 CLI 共用 run_pipeline()
  templates/                # index.html（表單）、result.html（報告顯示）
  static/style.css
data/                      # 主辦方提供之 5 幣種 Daily OHLCV 共同基準資料
scripts/
  test_collectors.py       # 獨立驗證腳本：單獨執行六類真實 collector
  check_llm.py              # 驗證目前 LLM_BACKEND 是否能連線
tests/                     # pytest：schema、collector 失敗隔離、report-evidence 對應、
                            # OHLCV/技術指標邏輯、推理鏈辯論與 fallback、comparison 雙幣種
main.py                    # CLI 進入點（--coin / --coin2 / --question / --dry-run）
Dockerfile / .dockerignore  # Web UI 與 CLI 共用同一個 image
```

## 硬性限制

- LLM 推理僅使用 AWS Bedrock 上的模型（正式執行前 `.env` 的 `LLM_BACKEND` 必須是 `bedrock`）。
- 15 分鐘執行時限，超過 `DEGRADED_MODE_TRIGGER_SECONDS`（預設 720 秒）會跳過剩餘資料蒐集直接進入推理。
- 每個 collector 皆有獨立 timeout 與例外隔離，單一來源失敗不影響全流程（見 `agent/collectors/base.py`）。
- 推理鏈任一步驟（含辯論）失敗都會被捕捉並退化為誠實揭露失敗原因的報告，不會讓整個流程崩潰。

## AWS 部署（EC2，已上線）

```
使用者瀏覽器 ──HTTP:80──▶ EC2 t3.small（FastAPI Web UI）
                              │
                              ├──InvokeModel / Converse──▶ Bedrock global inference profile
                              │                            （Claude Opus 4.6）
                              └──HTTPS──▶ Coinbase / CoinGecko / 公開 RPC / RSS /
                                           Reddit / Fear&Greed / 衍生品 API

管理者 ──SSM Run Command──▶ EC2（安全群組不開 SSH 22）
```

公開網址：<http://52.33.16.251/>；健康檢查：<http://52.33.16.251/healthz>。

主辦方 Workshop 帳號的 App Runner 受 SCP 限制，因此正式 v1 改用 `us-west-2`
EC2。程式透過執行個體角色呼叫 Bedrock，主機不保存 AWS access key；安全群組只開
HTTP 80，管理操作走 SSM，不開 SSH。

### 更新方式

正式環境由 EC2 從 GitHub 的 v1 分支／標籤更新，安裝相依套件後重啟既有服務。
部署前後至少驗證：

```bash
python -m pytest -q
python main.py --coin BTC --question "分析 BTC 過去兩週市場狀況" --dry-run
curl http://52.33.16.251/healthz
```

實際 AWS 資源、IAM 最小權限、SSM 管理方式與驗收紀錄見 `STATUS.md`。不要在文件、
EC2 或環境變數中保存 Workshop 的 STS 臨時憑證。

> 目前公開入口為 HTTP；若轉為正式長期產品，應在前方加 CloudFront／ALB 與 HTTPS。

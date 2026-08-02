# 文件索引

專案的說明文件分三層。根目錄只留評審與新進者最先需要的四份，其餘按性質收在這裡。

## 根目錄（先看這些）

| 檔案 | 用途 |
|---|---|
| `README.md` | 安裝、執行、LLM 後端切換、交付檔位置 |
| `STATUS.md` | 目前完成度與待辦，專案現況的權威來源 |
| `DATA_SOURCES.md` | 五類資料來源設計、`data/` 與 `raw_data/` 的分工 |
| `PITCH_REFERENCE.md` | 決賽簡報素材庫（解題方向／AI 技術／數據應用／AWS 架構） |

## 驗證與安全記錄

| 檔案 | 內容 |
|---|---|
| `JUDGE_TEST_REPORT.md` | 命題三種範例題型的真實 Bedrock 實跑結果與敏感度探針。`output/` 不進版控，這份是那些執行的唯一版本控紀錄 |
| `SECURITY_prompt_injection.md` | 外部文字（新聞／社群）的提示注入防護設計，對應 `agent/filters/injection.py` |

## design/ — 設計沿革

Ken 與團隊的架構迭代筆記，是 `Stage 2 — Feature Extraction/` 等 runtime 規格檔的設計依據。
原稿在 Obsidian vault，帶 frontmatter 與 `[[wikilink]]`；wikilink 在本 repo 內不會解析，屬正常現象。

| 檔案 | 內容 |
|---|---|
| `design/07_流程圖迭代定案.md` | Round 6 流程圖定案，資料層信任評分（R12）的設計權威 |
| `design/09_權重改版草案.md` | Layer A／Layer B 權重拆分草案。**設計稿，未實作** |
| `design/10_v3提案評估回覆.md` | 對「HOYA Research Agent v3」12-Stage 架構提案的逐 Stage 可行性評估 |
| `design/11流程圖模板.md` | Statistical／Event／Sentiment 三型 factor 的 feature／knowledge／weight 模板骨架 |

## archive/ — 歷史快照與內部交接

保留以維持可追溯性，但內容已被上面的文件取代，讀現況請不要從這裡開始。

| 檔案 | 內容 | 注意 |
|---|---|---|
| `archive/AUDIT.md` | 2026-07-18 的逐檔原始碼盤點 | 當時 54 檔／41 測試，數字早已過期 |
| `archive/HANDOFF_judge-deadline.md` | 裁判機制與 15 分鐘上限修正的交接索引 | 內容已併入 `JUDGE_TEST_REPORT.md` |
| `archive/UPGRADE_SPEC_execution_logs.md` | 五層信任提煉與四面板資料契約的原始規格 | 已由 `.kiro/specs/trust-refinement-upgrade/` 取代 |
| `archive/docs_v1_rollback.md` | v1.1 的回退方案與 EC2 部署位置 | v1 時期的作業手冊 |
| `archive/docs_v1_2_v2_reference.md` | v1.2 併入 research sidecar 的整合說明 | 對應 `agent/research/` 的由來 |

## 規格與引導檔

`.kiro/specs/` 是需求／設計／任務三件套，`.kiro/steering/` 是專案引導規範。
兩者都刻意進版控，作為開發過程的紀錄。

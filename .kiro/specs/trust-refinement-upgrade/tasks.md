# Implementation Plan: 全專案升級——信任提煉流水線與 Execution Logs 可視化

> 對應 `requirements.md`（R1–R12）與 `design.md`。

## Overview

本檔案是 `trust-refinement-upgrade` spec 的執行清單，按 Phase 0–7 依序執行。
Phase 0–5 已完成並經程式碼審查＋實測驗證；Phase 6 因 Bedrock 帳號未開通而
blocked；Phase 7（R12，資料層改版）因實作歸屬未定而 blocked，見下方 Notes。

## Task Dependency Graph

```
Phase 0（bug 修復＋Kiro 證據，無依賴）
  └─▶ Phase 1（schema 地基）
        └─▶ Phase 2（過濾與指標，純本地）
              └─▶ Phase 3（view_builder＋dry-run）
                    └─▶ Phase 4（前端 MVP）
                          └─▶ Phase 5（完整四面板）
                                └─▶ Phase 6（Bedrock 最終驗證）[BLOCKED: bedrock 帳號]
Phase 7（資料層改版，R12）── 設計依賴 Phase 1-2 的 schema，
                              但實作前置條件是「團隊拍板歸屬」，非技術依賴
                              [BLOCKED: 實作歸屬未定]
```

```json
{
  "waves": [
    {"wave": 1, "phases": ["Phase 0"], "description": "Kiro 證據與 bug 修復，無依賴"},
    {"wave": 2, "phases": ["Phase 1"], "description": "Schema 地基，依賴 Phase 0"},
    {"wave": 3, "phases": ["Phase 2"], "description": "過濾與指標（純本地），依賴 Phase 1"},
    {"wave": 4, "phases": ["Phase 3"], "description": "view_builder 與 dry-run，依賴 Phase 2"},
    {"wave": 5, "phases": ["Phase 4"], "description": "前端 MVP，依賴 Phase 3"},
    {"wave": 6, "phases": ["Phase 5"], "description": "完整四面板，依賴 Phase 4"},
    {"wave": 7, "phases": ["Phase 6", "Phase 7"], "description": "Phase 6 依賴 Phase 5 完成＋Bedrock 帳號開通；Phase 7 技術上只依賴 Phase 1-2 的 schema，但需先由團隊拍板實作歸屬才能開工——兩者互不依賴、可平行推進"}
  ]
}
```

## Tasks

### 執行慣例
每個 task 完成即跑 `pytest -q` 確認測試全綠再進下一個；需要消耗 LLM 額度的驗證
一律排在最後、優先用 `--dry-run`。標記 `[BLOCKED: ...]` 的 task 等條件解除才執行。

## Phase 0 — Kiro 證據與 bug 修復（無依賴，先做）

- [x] 0.1 建立 `.kiro/steering/` 三檔（product.md：命題目標與合規紅線／tech.md：技術棧與
      LLM 抽象層約束／structure.md：目錄結構與擴充慣例）＿R11-2
- [x] 0.2 設定 agent hook：儲存 `agent/**/*.py` 或 `tests/**/*.py` 時自動執行 `pytest -q`＿R11-3
- [x] 0.3 修復 news 比對：`coin_map.py` 匯出 `FULL_NAME_ALIASES`；`news.py` `_matches_coin()`
      改雙軌比對（ticker 大小寫敏感＋全名小寫）；回歸測試（method/solution 不誤中；
      Ethereum/SOL 正常命中）＿R1-1, R1-2
- [x] 0.4 修復 macro 重複：`collect_all()` macro 只建一次 task；更新比較題測試斷言
      「macro 證據無重複」＿R1-3

## Phase 1 — Schema 與 log 地基（向後相容）

- [x] 1.1 `schemas.py` 新增：`PipelineLayer`、`FilterVerdict`、`FilterDecision`、`RunMetrics`；
      `EvidenceDraft` 加 `source_weight`/`weight_reason`/`rag_verified`/`rag_support`；
      `LogEntry` 加 `layer`/`metrics`（全預設值）＿R3-1~3
- [x] 1.2 `logging_utils.py` `log()` 接受選用 `layer`/`metrics`；驗證既有測試零修改通過＿R3-4, R3-5
- [x] 1.3 schema 單元測試：新欄位預設值、FilterDecision/RunMetrics 驗證＿R3

## Phase 2 — 流水線指標與過濾（純本地，零 LLM 成本）

- [x] 2.1 `agent/filters/source_weights.py`：L1 靜態權重表＋orchestrator 於證據化後統一補權重
      ＋L1 彙總 log；單元測試（查表規則）＿R4-1
- [x] 2.2 `agent/filters/content.py`：PR 英文詞典降權＋模板 Jaccard 相似度（≥0.8 標非獨立）；
      FilterDecision 逐筆＋彙總 log；F9 佔位（enabled:false）；單元測試＿R4-2
- [x] 2.3 `pipeline.py`：Step A 後補 L3 metrics（input/kept/removed/removal_rate）、
      Step B 後補 L4 metrics＿R4-3, R4-4
- [x] 2.4 `pipeline.py`：L5 數值信心公式（base＋權威加成−矛盾−缺口，夾 5–95），
      分項寫 log；單元測試（手算樣本）＿R4-5
- [x] 2.5 兩個 LLM client 累計 usage；orchestrator 讀取 → RunMetrics.total_tokens；
      FakeLLMClient 補假 usage 測試＿R4-6
- [x] 2.6 `agent/collectors/relative.py`：雙幣相對指標（相關係數/beta/最大回撤/相對強弱
      90 日位置），比較題型時 orchestrator 呼叫，失敗隔離；數學單元測試＿R2-1, R2-4
- [x] 2.7 macro F&G `limit=30` 百分位；news 命中則數量化證據；測試＿R2-2, R2-3

## Phase 3 — view_builder 與 dry-run

- [x] 3.1 `agent/report/view_builder.py`：組 `report_view.json`（schema_version 1.0，
      指紋映射 F1..Fn、log_events_by_layer、confidence_breakdown）；組裝失敗只記 log
      不影響三個命題交付檔＿R5-1~5
- [x] 3.2 dry-run fixtures 擴充（權重/假 FilterDecision/假 usage/假 baseline 文案）；
      dry-run 端到端測試斷言 report_view.json 全欄位非空＿R8
- [x] 3.3 degraded 整合：任一層跳過 → integrity_status=DEGRADED＋view 註明；測試＿R4-7

## Phase 4 — 前端 Stage 1（MVP）

- [x] 4.1 result.html 分頁化：報告｜執行時間線｜Raw Log；header 摘要列（讀 RunMetrics）＿R6-1~3
- [x] 4.2 app.py 傳入 log entries 與 view model；dry-run 表單路徑目視驗收＿R6-4

## Phase 5 — 前端 Stage 2（完整四面板）

- [x] 5.1 `agent/reasoning/baseline.py`：可開關對照組（--with-baseline／表單 checkbox，
      同一 LLMClient，prompt 禁投資建議，失敗隔離）＿R7-2
- [x] 5.2 view.html 四面板版面（`/view/{run_id}` 路由）；面板③逐層 `<details>` 展開 log 事件；
      缺資料誠實顯示＿R7-1, R7-3, R7-4
- [x] 5.3 合規檢查：全部面板文案無投資建議語彙；INTACT=分析完整性；效能實測新增耗時
      （不含 baseline）<2 秒＿R9

## Phase 6 — 最終驗證 [BLOCKED: bedrock]

- [-] 6.1 Bedrock 煙測（sts → check_llm.py → 必要時 inference profile／max_tokens 4096／
      stopReason 檢查）＿R10-2
- [~] 6.2 Bedrock 3 題型端到端＋四面板／usage 核對；Gemini 額度允許時先預演一次＿R10-2
- [~] 6.3 簡報素材：Kiro 工作流截圖＋AgentCore 取捨說明段落＿R11-4

## Phase 7 — 資料層改版：採用 Ken 的信任評分設計 [BLOCKED: 實作歸屬未定]

> 2026-07-20 架構決策：資料層（信源分級／去重／權重公式）採用 Ken 的
> `07_流程圖迭代定案.md` 設計，取代 Phase 2.1/2.2 現行實作（design.md §3.9）。
> LLM 結論產生邏輯不受影響、不變（辯論鏈維持裁判角色）。
> **實作歸屬（Kevin／Alan／協作）尚未拍板，見 `team-division.md`「邊界待對齊」，
> 有結論前不要動手實作，避免跟其他人重工。**

- [ ] 7.1 Phase 2 新增標題相似度去重（本地字串級），算出 `raw_count`／`deduped_count`／
      `dedup_rate` 隨證據傳遞＿R12-1
- [ ] 7.2 news 命中則數改用去重後數量（現行 R2-3 實作是去重前計數，需修正）＿R12-2
- [ ] 7.3 建立 `static/source_reputation.json`（賽前信譽表＋分級理由）＋改寫
      `source_weights.py` 為四因子公式（新鮮度×來源等級×覆蓋度×dedup_penalty）＿R12-3
- [ ] 7.4 `dedup_penalty` 獨立計算＋最小樣本門檻防呆（<5 則固定=1）＿R12-3c/3d
- [ ] 7.5 拉盤話術詞庫命中改為「來源等級降一級」（取代現行權重 ×0.5），與
      `dedup_penalty` 降權允許疊加，文件/報告註明避免誤認為 bug＿R12-4
- [ ] 7.6 Fallback：靜態表或去重邏輯失敗時退回現行 Phase 2.1 規則表，不中斷流程＿R12-5
- [ ] 7.7 更新受影響測試（`test_source_weights.py`／`test_content_filter.py`／
      `test_macro_news_upgrade.py`）＋新增覆蓋度 vs 覆蓋率不混用的回歸測試
- [ ] 7.8 Bedrock 開通後（Phase 6 之後）用真實 pipeline 確認四面板數字仍可對帳
      （L1/L3 metrics 改版後 view_builder 是否仍正確組裝）

## Notes

- Phase 0–5 已於 2026-07-20 完成並經完整程式碼審查＋實際執行驗證（198→200 個
  pytest 全綠，含 3 次真實 dry-run 場景手動驗證：比較題型+baseline、degraded mode、
  L3 removed_items）。詳見 `team-division.md`「已完成里程碑對照」。
- Phase 6／Phase 7 的 blocked 條件不同：Phase 6 是外部帳號依賴（等 AWS Bedrock
  開通即可解除）；Phase 7 是團隊協調依賴（等分工拍板即可解除），兩者互不影響，
  Phase 7 拍板後可以在 Phase 6 仍 blocked 的情況下先行開工。
- Phase 7 的設計權威是隊友 Ken（`07_流程圖迭代定案.md`），實作前務必先讀過該檔案
  全文，尤其「未完全收斂項目」章節列出的三個 Ken 自己也還沒定案的細節（信譽表
  檔名、dedup 最小樣本門檻、dedup_penalty 分級曲線），遇到時要跟 Ken 對一次，
  不要自行拍板。
- 架構層級決策（資料層採用 Ken 設計／LLM 結論產生權維持辯論鏈）已於 2026-07-20
  裁定並記錄於 `requirements.md`（架構決策記錄）、`design.md`（文件頂部＋
  Property 6）、`team-division.md`（架構分歧章節），三份文件互為交叉引用，
  修改其中一份時建議一併檢查其餘兩份是否同步。

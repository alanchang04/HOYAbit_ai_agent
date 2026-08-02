# HANDOFF：裁判機制實測與 15 分鐘上限硬保證（2026-08-01）

> 這份文件是給**接手的人／新的 AI session** 看的完整交接記錄。
> 讀完這份就能接著做，不需要回頭翻對話紀錄。
>
> 詳細的實測數據、逐條診斷與判斷依據在 **`JUDGE_TEST_REPORT.md`**（§1–§12）。
> 本文是索引與行動清單，遇到「為什麼這樣改」的問題一律去查那份報告的對應章節。

---

## 0. TL;DR

以命題文件的三種範例題型實跑 Bedrock，發現裁判機制的核心計分欄位在真實區間內
**是個常數**、以及一次 Bedrock 卡頓會讓整跑**超過 15 分鐘硬性上限**。
兩者都已修好並實跑驗證。

| commit | 內容 |
|---|---|
| `35b0939` | 裁判機制四項修正 ＋ Bedrock 時間邊界 |
| `e8e3020` | 15 分鐘上限改為硬保證 |
| （本次） | 實測報告與本交接文件進版控 |

分支：**`security/prompt-injection-filter`**（見 §5 的注意事項）。

---

## 1. 這次做了什麼

### 1.1 三題型真實 Bedrock 實跑

用命題文件的範例一／二／三**逐字**當題目，幣種取自幣種池：

| | 題型 | 幣種 | 結果 |
|---|---|---|---|
| Q1 | 多源整合 `multi_source` | BTC | 251.7s / 31 筆證據 |
| Q2 | 假設驗證 `hypothesis_test` | ETH | 221.9s / 30 筆 |
| Q3 | 比較分析 `comparison` | SOL vs XRP（自動偵測） | 274.2s / 45 筆 |

三題題型分類、`coin2` 偵測、辯論輪數、degraded 判定全部正確。

**方法上的一個要點**（後續要再測請沿用）：用一支 scratchpad 腳本在
`pipeline._call_json_step` 外面包一層 tee，把 Step A–D **消毒前**的原始 JSON
側錄進 `llm_steps.jsonl`。**repo 程式碼不動**，走的是 `run_pipeline()` 同一條路徑。
沒有這個側錄，「摘要只有 N 點」分不出是裁判沒講還是消毒器吃掉了。

### 1.2 裁判機制的四項修正（`35b0939`）

| # | 問題 | 修法 |
|---|---|---|
| 1 | `debate_adjustment` 沒有鑑別力 | 改由 `debate_summary` 逐點 `verdict` 加總 |
| 2 | 裁判被要求依權重評斷，卻拿不到權重表 | `build_step_d_prompt()` 補 `evidences` 參數 |
| 3 | 信心分數與等級是兩套獨立系統 | 等級改由分數決定性推得，分歧時揭露 |
| 4 | 摘要點可以沒有 evidence id 而不留痕跡 | 渲染時加「⚠ 未附可回溯的 evidence id」 |
| 5 | 推論層 compact 區塊用跨輪聯集配末輪文字 | 改用末輪 id |

**第 1 項的實證**（`JUDGE_TEST_REPORT.md` §3）：同輸入重打 5 次全是 −3、
三種題型全是 −3、把「反方打中兩項」削成「打中一項」也是 −3，
只有把反方整段換成無證據空話才翻成 +3。**±3 是「中等調整」的語意代號，
不是嚴重程度的刻度。**

新級距（`confidence.VERDICT_SCORES`）：

| verdict | 分數 | 意義 |
|---|---:|---|
| `bear_valid` | −3 | 反方批評成立且正方未有效回應 |
| `bear_partial` | −1 | 部分成立／雙方各有道理 |
| `draw` | 0 | 未分勝負（也是判讀不出來時的落點） |
| `bull_defended` | +1 | 正方擋下、通過壓力測試 |

摘要 3–5 點，5×(−3) = −15、5×(+1) = +5，兩端對齊既有的
`DEBATE_ADJUSTMENT_MIN/MAX`，不需另定夾值語意。
**無有效判定時回 `None` 而非 0**，退回舊的自報整數路徑——回 0 會讓報告寫成
「裁判未提供有效的調整值」，但實際上是這次根本沒有辯論。

### 1.3 辯士「先判定再讓步」（`35b0939`）

正方第 2 輪普遍先「承認…批評成立」再換一組新證據重講。病因是任務指示本身：

> 逐項回應反方的批評。批評成立的部分要誠實承認並修正你的論證，**不要硬拗**。

把讓步當預設、把防守叫硬拗。**改寫任務本身**（只加規則會與任務清單打架，
模型跟的是任務清單）成「先判定成不成立，再三選一」，另加正反方共用的
`DEBATE_REBUTTAL_STANDARD`（三項檢驗），掛在 C1 反駁輪與 C2 第 2 輪起。

同題連續三跑的行為變化：

| | 改動前 | 逐點判定版 | ＋判定標準版 |
|---|---|---|---|
| 正方 R2 讓步詞 | 10 | 13 | **4** |
| 正方 R2 明確反駁詞 | 0 | 0 | **3** |
| `bull_defended` | — | 0 | **1** |

**`bear_valid` 仍有 2 條是合格線**——掉到 0 代表被教成拒絕有效批評，那是失敗。

### 1.4 15 分鐘上限硬保證（`35b0939` + `e8e3020`）

一次實跑 1189 秒（`step_a_facts` 單一次呼叫卡 1020 秒）。成因鏈：

1. boto3 預設 `read_timeout=60s`，而實測最慢的正常呼叫（`step_d_conclusion`）
   是 **56.5s**——**只剩 6% 餘裕**。
2. botocore 預設 `retries={'mode':'legacy'}`、`max_attempts=5`，且
   `general_socket_errors` 的 `EXCEPTION_MAP` **含 `ReadTimeoutError`**。
3. `ReadTimeoutError` 又是 `BotoCoreError` 子類，被應用層再接住重試 3 次。
4. 兩層相乘 ≈ 15 次 × 60s ≈ 900s，**且全程零 log**。

修法是**兩層保證，缺一不可**：

| 層 | 保證 | 位置 |
|---|---|---|
| 不啟動 | 剩餘 < `MIN_LLM_STEP_SECONDS`(20s) 就放棄該步驟 | `pipeline._call_json_step()` |
| 不超時 | 依剩餘預算收緊該次 socket read timeout | `BedrockClient._effective_timeout()` |

只擋啟動是不夠的——截止前 1 秒發出的請求照樣能跑滿 150s。
botocore 的 timeout 綁在 client 建構時，故改為依 timeout 值快取多個 client。

其餘預留：報告收尾 20s（`orchestrator.REPORT_RESERVE_SECONDS`）、
裁判 120s（`pipeline.STEP_D_RESERVE_SECONDS`，不夠就整段跳過辯論直接進結論）。

### 1.5 順手抓到的計時 bug

第 1 輪的正方呼叫在辯論迴圈**外**，而 `round_started` 設在迴圈**內**——
第 1 輪只量到反方、**低估四成**，而那個值正是下一輪 deadline gate 的分母
（實測 gate 記 `needed=70.3s`，÷2.2 = 31.95s ＝ 反方單獨耗時）。已修。

⚠️ **連帶影響**：`DEBATE_ROUND_TIME_FACTOR = 2.2` 是拿**被低估的分母**算出來的
（1.68/1.91/2.09），校準基礎不乾淨。等有足夠的乾淨樣本應回頭重算。

---

## 2. 改了哪些檔案

```
agent/config.py               LLM_READ_TIMEOUT_SECONDS / LLM_CONNECT_TIMEOUT_SECONDS
agent/orchestrator.py         REPORT_RESERVE_SECONDS、deadline 與 on_retry 接線
agent/reasoning/bedrock_client.py  Config(timeout/retries)、_effective_timeout()、
                                   deadline、on_retry、依 timeout 快取 client
agent/reasoning/confidence.py VERDICT_SCORES、tally_debate_verdicts()、
                              confidence_label()、CONFIDENCE_TIER_*
agent/reasoning/pipeline.py   MIN_LLM_STEP_SECONDS、STEP_D_RESERVE_SECONDS、
                              DEBATE_ROUND_TIME_FACTOR、_call_json_step(deadline=)、
                              第1輪計時、_sanitize_debate_summary 收 verdict
agent/reasoning/prompts.py    build_step_d_prompt(evidences=)、verdict schema 與說明、
                              DEBATE_REBUTTAL_STANDARD、C1 反駁輪任務改寫、
                              _format_inference_section 改用末輪 id
agent/report/builder.py       _confidence_label_of()、_confidence_divergence_note()、
                              verdict 加總式進表格、無 id 摘要點加註記
agent/report/view_builder.py  panel4 的 confidence_label 改讀同一來源
.env.example                  新增兩個 timeout 設定
tests/test_judge_verdict_tally.py   新檔，本次全部改動的測試（8 組）
tests/test_reasoning_pipeline.py    deadline 契約變更 + 新增 expired-deadline 測試
```

`pytest` **560 → 613 全綠**（在獨立 worktree 對 `e8e3020` 驗過，確認提交出去的
那份 tree 本身自洽，不是靠工作區其他未提交的東西才過）。

---

## 3. 還沒做 / 沒驗到的（接手者的行動清單）

### 3.1 未被任何測試涵蓋

- **真實 `ReadTimeoutError` 的行為**——無法按需重現。新增的測試驗的是設定值與
  預算邏輯的分支，不是「真的遇到 socket 逾時會怎樣」。
- **fallback 路徑**（`_has_debate_transcript() == False` → `debate_summary=[]` →
  退回自報整數）只有單元測試，沒有真實跑過。
- `stopped_reason` 的 `bull_failed` / `bear_failed` 分支。
- `step_c_inference_fallback`（正方首輪失敗整段退回單模型）。

要驗這些需要**強制失敗的 run**，正常執行踩不進去。

### 3.2 已知仍開放的問題

| 項目 | 狀態 |
|---|---|
| 面板④ 缺辯論重點摘要 | `report_view.json` 的 `panel4_report` 沒有 `debate_summary` key，`report.md` 有。三題實測確認成立（STATUS.md 待辦 13） |
| `DEBATE_ROUND_TIME_FACTOR` 校準基礎不乾淨 | 見 §1.5 |
| 信心等級門檻 80/60 | 取自「不改變 2026-08-01 三題呈現」（79/78/74 → 中/中/中）。分數落在門檻附近的行為樣本裡沒有 |
| `converged` 分支很少觸發 | 累計 8 輪觸發 1 次。反方被要求只管建構己方論證，卻又要它自報「我沒新東西了」＝要它自己認輸 |
| Reddit 429 限流 | `.env` 未設 `REDDIT_CLIENT_ID`/`SECRET`，走免 key RSS，每題白花約 20s |

### 3.3 題型適配性的徹底檢視（`JUDGE_TEST_REPORT.md` §13）

專門針對「這套機制能不能正確回應各種題型」做過一次徹底檢視，結論是
**推理品質好，但整套機制是繞著多源整合題長出來的**。優先序：

1. ✅ **已完成**：用新機制重跑 Q2／Q3（§14）。verdict 合法率 15/15，
   逐點加總實測出現 −1／−7／−11 三個量級（舊機制在真實區間是常數 −3）。
   Q2 的裁判自報純量首次轉正（+1），與判定標準的改動方向一致。
2. ✅ **已完成**（`86e3380`）：分類器加幣種數量覆寫——題目出現 2 個以上幣種池
   成員 → 直接判 comparison，優先於關鍵字。判錯代價不對稱（漏判救不回來、
   誤判只是多蒐集一個幣種），所以刻意偏向誤判。範例題與題目模板分類不變。
> ⚠️ **2026-08-01 後續：自建四題擴充測試（§15）後，下列第 3 項的根因已擴大。**
> 實測確認 `verdict` 級距假設「反方＝質疑者」，而這個假設在**比較題**
> （兩邊都是倡議者）與**假設驗證題**（正方被指派論證一個可能為假的命題）
> **都不成立**。假設驗證題的激勵方向甚至是反的：假設越明顯為假，正方被打得越慘、
> 信心扣得越多（T4 給出九次跑最明確的答案，卻拿到最大扣分 −11）。
> 兩者應一起修，不要各打各的補丁。

3. 🔴 **比較題的 verdict 級距不對稱——實測確認，且比原診斷更深一層**（§14.3）。
   不只幅度（`bear_valid=−3` vs `bull_defended=+1`），**連粒度都不對稱：
   反方有兩個得分等級（−3／−1），正方只有一個——沒有 `bull_partial`。**
   多源整合／假設驗證題可自圓其說（反方＝質疑者），但比較題兩邊都是倡議者，
   於是這套級距能表達「XRP 方部分成立」卻無法表達「SOL 方部分成立」。
   用 Q3 真實 verdict 試算主幣對調：−7 vs −1～−3，**4–6 分落差純來自題目語序**。
   最小改動是為比較題啟用對稱級距（補 `bull_partial`，或改用 {−2,−1,0,+1,+2}），
   **不是只調數值大小**。
4. 🟠 比較題的 `direction_matrix` 改分幣種——現況以 `source_type` 去重，
   Q3 實測恰好 6 列且 basis 橫跨兩幣，`signal_consensus`（佔基底 40%）
   量到的是「兩幣是否一起看空」而非「兩者差異」。
5. 🟠 資料完整度門檻改 per-coin——Q3 的 onchain 每幣 1 筆卻判 tier 1.0，
   單幣題同樣 1 筆判 0.6。改 per-coin 後 Q3 資料品質為 80.0 而非 93.3。

⚠️ 3–5 動到計分核心且距競賽已近。時間有限時做完 1、2 並在報告「已知限制」
誠實揭露其餘三項，比倉促改計分公式安全——評分標準明列「對不確定性與限制的
清楚說明」，揭露本身就是得分項。

### 3.4 明確**不建議**做的

STATUS.md 待辦 12② 「給正方 `critique` 欄位」（動 debate 契約）——
本次資料不支持。15 條裁判摘要人工歸類是**反方 8 / 正方 5 / 打平 2**，
反方確實佔優但沒有壓倒。53:33 的落差不足以支撐破壞性變更。
（詳見 `JUDGE_TEST_REPORT.md` §6.4）

---

## 4. 環境狀態（換帳號／換機器必讀）

- `.env` **未進版控**，不會跟著 git 走。新機器要自己建（照 `.env.example`）。
- `.env` 裡的 AWS 憑證是 **STS 臨時憑證**（`ASIA...` 開頭 + `AWS_SESSION_TOKEN`），
  幾小時就過期。過期後 `scripts/check_llm.py` 會噴 `ExpiredToken`，
  重跑原本取得憑證的方式（`aws sso login` / `aws sts assume-role`）換掉三行即可。
- 目前設定：`LLM_BACKEND=bedrock`、`AWS_REGION=us-west-2`、
  `BEDROCK_MODEL_ID=global.anthropic.claude-opus-4-6-v1`（已實打驗證可用）。
- `output/` 被 gitignore 擋著。三題實跑的原始產出（`llm_steps.jsonl`、
  `evidence.json`、`report.md`、`report_view.json`）**只存在原本那台機器上**，
  換機器就沒了。`JUDGE_TEST_REPORT.md` 是唯一進版控的記錄。

### 常用指令

```bash
.venv/Scripts/python.exe -m pytest -q                    # 全套測試
.venv/Scripts/python.exe scripts/check_llm.py            # Bedrock 連線實打驗證
.venv/Scripts/python.exe main.py --coin BTC --question "..." --dry-run
.venv/Scripts/python.exe -m uvicorn webapp.app:app --host 127.0.0.1 --port 8000
```

---

## 5. ⚠️ 分支狀態（重要）

這兩個 commit 落在 **`security/prompt-injection-filter`**，
parent 是 `fix-judge-summary-fallback` 的 tip（`a668830`）。

**同一棵樹上有另一份進行中的 prompt-injection filter 工作**——
`agent/filters/injection.py`、`tests/test_injection_filter.py`，以及
`prompts.py`／`builder.py`／`view_builder.py`／`schemas.py`／`baseline.py`／
`webapp/templates/view.html` 的相應改動。**那不是本次工作的一部分，沒有被 commit。**

`agent/orchestrator.py` 兩邊都有改到，本次是**逐 hunk 只取 deadline 相關的改動**
入 index，工作區隨即還原，對方的 WIP 完好。

接手時請先 `git status` 確認那份 WIP 的狀態，不要誤以為是自己的改動。
（交接當下該份工作有 1 個測試未過：`test_view_renders_injection_panel_and_escapes_payload`）

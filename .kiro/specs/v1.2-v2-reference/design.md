# v1.2 V2 Reference — Design

## Architecture

```text
Evidence[] + ReasoningResult
          │
          ├─ deterministic feature adapters
          │      └─ StructuredFeature[]
          │
          ├─ reviewed knowledge catalog
          │      └─ KnowledgeCard[]
          │
          └─ relationship builder
                 └─ EvidenceGraph

                       ↓
              ResearchContext v1.0
                       ↓
             research_context.json
```

## Isolation boundary

`ResearchContext` 是唯讀 sidecar。它不修改 Evidence、不修改 `ReasoningResult`、不重算 confidence，也不進入 LLM prompt。正式合併時只需在 reasoning 完成後呼叫一次 writer；若 writer 失敗，orchestrator 應記錄錯誤後繼續產出既有交付檔。

## Compatibility adapter

Evidence 可能處於三種狀態：

1. 現行 v1.2：只有 `related_claim` topic 與 injection／dedup 欄位。
2. Claude 完成版：可能新增 `validation_status`、`validation_issues`、`related_claims`。
3. 未來 producer：直接提供 `structured_features`。

adapter 使用安全的 attribute／dict 讀取，優先順序如下：

```text
explicit structured_features > deterministic parser > skip
explicit validation fields > injection/dedup inference > valid fallback
related_claims > legacy related_claim as topic
```

## Feature extraction policy

- 僅解析明確標籤或 key-value，例如 `RSI14=63.2`、`最新資金費率 +0.00316%`。
- 不從「偏熱」「可能擁擠」等敘事推回數值或方向。
- 數值、單位與 window 不完整時可保留已知欄位，但不得填造未知值。
- stable feature id：`feature:{evidence_id}:{name}`；同一 Evidence 同名 feature 只保留第一筆。

## Graph policy

Node kinds：`evidence`、`claim`、`topic`、`signal`。

Edge relations：`supports`、`contradicts`、`cited_by`、`about`、`duplicate_of`、`contributes_to_direction`。

Graph 不推導新方向，只轉錄 reasoning 已存在的關係。若 invalid/quarantined Evidence 仍被推理引用，edge 保留並標記 `validation_violation=true`，讓驗收能直接發現 gate 漏洞。

## Merge strategy

本 branch 不修改 `agent/schemas.py`、`agent/orchestrator.py`、`agent/report/view_builder.py`，降低與 Claude 工作的衝突。合併後再以單一 integration commit：

1. reasoning 完成後呼叫 `write_research_context()`；
2. Execution Log 記錄 sidecar 成功／失敗；
3. Web UI 選擇性讀取 graph，不影響舊 schema。


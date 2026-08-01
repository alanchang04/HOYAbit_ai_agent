# v1.2 吸收 v2 Reference 的整合說明

## 本 branch 提供什麼

`feat/v1.2-v2-reference` 刻意只新增 sidecar 模組，不修改 Claude 正在處理的 Validation gate、claim mapping、Execution Log、Evidence schema 或 orchestrator。

新增輸出 `research_context.json`，內容包含：

1. `structured_features`：從 Evidence 顯式欄位或固定標籤決定性抽取的數值。
2. `knowledge_cards`：中立的定義、適用範圍、限制與參考資料。
3. `evidence_graph`：Evidence 與 topic、mapped claims、facts、inference、conclusion、debate、direction matrix 的關係。

這份 sidecar 是決賽展示與稽核資料，不改變 v1.2 的推理、judge 或 confidence。

## Claude 完成後的合併順序

1. Claude 先把 v1.2 變更 commit 到 `release/v1.2`。
2. 在新的 integration branch 合併／cherry-pick本 branch。
3. 先跑 `tests/test_research_features.py` 與 `tests/test_research_context.py`。
4. 檢查 Claude 的新欄位名稱；若與 adapter 預設不同，只修改 `agent/research/graph.py` 的 `_validation_status()`、`_validation_issues()` 或 `_related_claims()`。
5. 完整 pytest 通過後，再做唯一的 runtime integration commit。

## 建議的 runtime integration

在 `reasoning_result` 已完成、`evidences` 已通過 v1.2 gate、既有正式交付檔不受影響的位置加入：

```python
from agent.research.context import write_research_context

try:
    research_path, research_context = write_research_context(
        out_dir,
        evidences,
        reasoning_result,
        question=question,
        question_type=reasoning_result.question_type,
    )
    logger.log(
        phase=LogPhase.REPORT,
        action="research_context_written",
        detail=str(research_path),
        status=LogStatus.OK,
        metrics={
            "features": len(research_context.structured_features),
            "knowledge_cards": len(research_context.knowledge_cards),
            "graph_nodes": len(research_context.evidence_graph.nodes),
            "graph_edges": len(research_context.evidence_graph.edges),
            "validation_violations": research_context.evidence_graph.stats.get(
                "validation_violations", 0
            ),
        },
    )
except Exception as exc:  # sidecar 失敗隔離，不影響正式交付
    logger.log(
        phase=LogPhase.REPORT,
        action="research_context_written",
        detail=f"error={type(exc).__name__}: {exc}",
        status=LogStatus.ERROR,
    )
```

若 `validation_violations > 0`，integration test 應失敗或至少把 `integrity_status` 降為 PARTIAL；它表示 invalid/quarantined Evidence 仍被 facts、inference、conclusion、debate 或 direction matrix 引用。

## 決賽 UI 的低風險接法

- Structured Features：用表格顯示指標、值、單位、window、Evidence ID。
- Knowledge Card：點開指標時顯示定義與限制，不放方向字眼。
- Evidence Graph：只做唯讀視覺化；Evidence node 依 valid／duplicate／quarantined 著色。
- Claim node 點擊後列出 supports／contradicts Evidence。
- 不讓前端 graph 回寫推理、不從 graph 重新計算 confidence。

## 完整 v2 暫不合併

- Dynamic Weight Engine／Market Regime：需要回測與校準。
- Hypothesis Generator：會改動已驗證的三題型核心。
- Graph-based reasoning：目前 graph 僅展示與稽核。


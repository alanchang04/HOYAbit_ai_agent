# v1.2 吸收 v2 Reference 的整合說明

## 本 branch 提供什麼

原始 `feat/v1.2-v2-reference` 刻意只新增 sidecar 模組，沒有修改 Claude 當時正在處理的 Validation gate、claim mapping、Execution Log、Evidence schema 或 orchestrator。最終整合版已在 Claude v1.2 完成後接上 orchestrator 與 Web 下載介面。

新增輸出 `research_context.json`，內容包含：

1. `structured_features`：從 Evidence 顯式欄位或固定標籤決定性抽取的數值。
2. `knowledge_cards`：中立的定義、適用範圍、限制與參考資料。
3. `evidence_graph`：Evidence 與 topic、mapped claims、facts、inference、conclusion、debate、direction matrix 的關係。

這份 sidecar 是決賽展示與稽核資料，不改變 v1.2 的推理、judge 或 confidence。

## 本次採用的合併順序

1. 以 Claude 發布的 `v1.2` tag 為基線。
2. 只 cherry-pick sidecar commit，避免重複合併兩邊 P0/P1 歷史。
3. adapter 直接接收 Claude 的 `validation_results`，並讀取 `ReasoningResult.related_claims`。
4. Structured Features 僅從 validated、非 duplicate Evidence 產生。
5. orchestrator 在 reasoning consistency 校正後寫入 `research_context.json`；失敗隔離，gate violation 則降級揭露。
6. Web／HTML 索引開放下載 `validation_results.json` 與 `research_context.json`。

## 已採用的 runtime integration

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
        validation_results=validation_results,
        quarantined_drafts=quarantined_drafts,
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


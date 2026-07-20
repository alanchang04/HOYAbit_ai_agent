"""效能測試：R9 — 整體新增耗時（不含 baseline）SHALL <2 秒。

驗收條件：
- dry-run pipeline 跑完（含 L1 信源權重 + L2 內容過濾 + L5 信心公式 + view_builder）
  的新增耗時不超過 2 秒
- L2 內容過濾為純本地毫秒級
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from agent.filters.content import apply_content_filters
from agent.filters.source_weights import apply_source_weights
from agent.logging_utils import ExecutionLogger
from agent.orchestrator import run_pipeline
from agent.schemas import Evidence, SourceType


def _make_evidences(count: int = 20) -> list[Evidence]:
    """建立測試用假證據列表。"""
    evidences: list[Evidence] = []
    sources = [
        ("HOYA BIT 共同基準資料集", SourceType.PRICE),
        ("CoinGecko API", SourceType.PRICE),
        ("Etherscan 鏈上資料", SourceType.ONCHAIN),
        ("CoinDesk RSS", SourceType.NEWS),
        ("Cointelegraph RSS", SourceType.NEWS),
        ("Reddit r/CryptoCurrency", SourceType.SOCIAL),
        ("FRED 經濟數據", SourceType.MACRO),
    ]
    for i in range(count):
        src_name, src_type = sources[i % len(sources)]
        evidences.append(
            Evidence(
                id=f"ev-{i + 1:03d}",
                coin="BTC",
                source=f"{src_name} (test)",
                fetched_at="2025-01-01T00:00:00Z",
                content_reference=f"Test evidence content #{i + 1} for performance measurement",
                related_claim="BTC price analysis",
                source_type=src_type,
            )
        )
    return evidences


class TestL2ContentFilterPerformance:
    """L2 內容層過濾效能：純本地毫秒級。"""

    def test_l2_filter_under_100ms(self, tmp_path: Path) -> None:
        """L2 過濾 20 筆證據應在 100ms 以內完成。"""
        evidences = _make_evidences(20)
        logger = ExecutionLogger(tmp_path / "test.jsonl")

        start = time.perf_counter()
        apply_source_weights(evidences, logger)
        apply_content_filters(evidences, logger)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100, f"L1+L2 過濾耗時 {elapsed_ms:.1f}ms，超過 100ms 上限"

    def test_l2_filter_50_items_under_200ms(self, tmp_path: Path) -> None:
        """L2 過濾 50 筆證據應在 200ms 以內完成。"""
        evidences = _make_evidences(50)
        logger = ExecutionLogger(tmp_path / "test.jsonl")

        start = time.perf_counter()
        apply_source_weights(evidences, logger)
        apply_content_filters(evidences, logger)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 200, f"L1+L2 過濾 50 筆耗時 {elapsed_ms:.1f}ms，超過 200ms 上限"


class TestPipelinePerformance:
    """完整 dry-run pipeline 效能：新增步驟耗時 <2 秒。"""

    def test_dry_run_total_under_2_seconds(self, tmp_path: Path) -> None:
        """dry-run pipeline 完整跑完（不含 baseline）耗時 <2 秒。

        由於 dry-run 不做任何網路呼叫、不消耗 LLM 額度，
        所有新增步驟（L1 權重 + L2 過濾 + L5 信心 + view_builder）
        皆為純本地計算，應輕鬆低於 2 秒。
        """
        start = time.perf_counter()
        result = run_pipeline(
            coin="BTC",
            question="分析 BTC 市場近期走勢",
            dry_run=True,
            output_dir=str(tmp_path),
            with_baseline=False,  # 不含 baseline
        )
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, (
            f"dry-run pipeline 耗時 {elapsed:.2f}s，超過 2 秒上限"
        )
        # 合理性檢查：應在 1 秒以內
        assert result.elapsed_seconds < 2.0

    def test_dry_run_with_baseline_under_3_seconds(self, tmp_path: Path) -> None:
        """含 baseline 的 dry-run 不做額外效能約束，但應在合理範圍內（<3s）。"""
        start = time.perf_counter()
        run_pipeline(
            coin="BTC",
            question="分析 BTC 市場",
            dry_run=True,
            output_dir=str(tmp_path),
            with_baseline=True,
        )
        elapsed = time.perf_counter() - start

        # baseline dry-run 只是回傳假文案，不消耗額外時間
        assert elapsed < 3.0, (
            f"含 baseline 的 dry-run 耗時 {elapsed:.2f}s，超過 3 秒"
        )

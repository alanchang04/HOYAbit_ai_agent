"""Tests for agent/filters/content.py — L2 內容層過濾。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.filters.content import (
    F9_STATUS,
    PR_TERMS,
    _jaccard_similarity,
    apply_content_filters,
    check_pr_language,
    check_template_similarity,
)
from agent.logging_utils import ExecutionLogger
from agent.schemas import Evidence, FilterVerdict, PipelineLayer, SourceType


def _make_evidence(
    ev_id: str = "ev-001",
    content: str = "BTC price is rising steadily",
    source_type: SourceType = SourceType.NEWS,
    source_weight: float = 0.60,
    source: str = "CryptoPanic RSS",
) -> Evidence:
    """建立測試用 Evidence 物件。"""
    return Evidence(
        id=ev_id,
        coin="BTC",
        source=source,
        source_url=None,
        fetched_at="2025-01-01T00:00:00Z",
        content_reference=content,
        related_claim="test claim",
        source_type=source_type,
        source_weight=source_weight,
    )


# --- PR 話術偵測測試 ---


class TestCheckPRLanguage:
    """測試 PR 詞典比對。"""

    def test_hit_skyrocket_downweighted(self):
        """命中 'skyrocket' → downweighted，weight × 0.5。"""
        ev = _make_evidence(content="BTC will skyrocket next week")
        decisions = check_pr_language([ev])

        assert len(decisions) == 1
        d = decisions[0]
        assert d.evidence_id == "ev-001"
        assert d.check_code == "PR"
        assert d.verdict == FilterVerdict.DOWNWEIGHTED
        assert d.weight_before == 0.60
        assert d.weight_after == 0.30
        assert "skyrocket" in d.reason

    def test_hit_to_the_moon(self):
        """命中 'to the moon' → downweighted。"""
        ev = _make_evidence(content="ETH is going to the moon")
        decisions = check_pr_language([ev])

        assert len(decisions) == 1
        assert "to the moon" in decisions[0].reason

    def test_hit_guaranteed(self):
        """命中 'guaranteed' → downweighted。"""
        ev = _make_evidence(content="guaranteed 10x returns")
        decisions = check_pr_language([ev])

        assert len(decisions) == 1
        assert "guaranteed" in decisions[0].reason

    def test_hit_chinese_term(self):
        """命中中文詞彙 '暴漲' → downweighted。"""
        ev = _make_evidence(content="BTC 即將暴漲！")
        decisions = check_pr_language([ev])

        assert len(decisions) == 1
        assert "暴漲" in decisions[0].reason

    def test_no_hit_no_decision(self):
        """未命中任何 PR 詞 → 不產出 FilterDecision。"""
        ev = _make_evidence(content="BTC traded at $65000 with moderate volume")
        decisions = check_pr_language([ev])

        assert len(decisions) == 0

    def test_multiple_terms_single_decision(self):
        """命中多個 PR 詞 → 只產出一個 FilterDecision（第一個命中詞）。"""
        ev = _make_evidence(
            content="BTC will skyrocket to the moon, guaranteed 100x returns"
        )
        decisions = check_pr_language([ev])

        assert len(decisions) == 1
        # 應命中第一個出現在 PR_TERMS 清單中的詞
        assert decisions[0].check_code == "PR"

    def test_weight_lower_bound_005(self):
        """權重 × 0.5 結果低於 0.05 時，應被限制在 0.05。"""
        ev = _make_evidence(content="guaranteed profits", source_weight=0.08)
        decisions = check_pr_language([ev])

        assert len(decisions) == 1
        assert decisions[0].weight_before == 0.08
        assert decisions[0].weight_after == 0.05  # max(0.08 * 0.5, 0.05) = 0.05

    def test_case_insensitive_matching(self):
        """PR 詞比對應為大小寫不敏感。"""
        ev = _make_evidence(content="BTC will SKYROCKET tomorrow")
        decisions = check_pr_language([ev])

        assert len(decisions) == 1
        assert "skyrocket" in decisions[0].reason.lower()

    def test_multiple_evidences_some_hit(self):
        """多筆證據中只有部分命中 → 只有命中者產出 decision。"""
        evs = [
            _make_evidence(ev_id="ev-001", content="BTC is going to the moon"),
            _make_evidence(ev_id="ev-002", content="ETH traded flat today"),
            _make_evidence(ev_id="ev-003", content="SOL guaranteed 100x"),
        ]
        decisions = check_pr_language(evs)

        assert len(decisions) == 2
        hit_ids = {d.evidence_id for d in decisions}
        assert hit_ids == {"ev-001", "ev-003"}


# --- 模板相似度測試 ---


class TestCheckTemplateSimilarity:
    """測試 Jaccard 相似度偵測非獨立來源。"""

    def test_high_similarity_marks_both(self):
        """Jaccard ≥ 0.8 → 兩筆都標 FilterDecision。"""
        # 兩筆幾乎相同的內容（Jaccard = 1.0）
        evs = [
            _make_evidence(
                ev_id="ev-001",
                content="Bitcoin surges past 70000 on institutional demand",
                source_type=SourceType.NEWS,
            ),
            _make_evidence(
                ev_id="ev-002",
                content="Bitcoin surges past 70000 on institutional demand",
                source_type=SourceType.SOCIAL,
            ),
        ]
        decisions = check_template_similarity(evs)

        assert len(decisions) == 2
        ids = {d.evidence_id for d in decisions}
        assert ids == {"ev-001", "ev-002"}

        # 所有 decision 的 check_code 都是 F10
        for d in decisions:
            assert d.check_code == "F10"
            assert d.verdict == FilterVerdict.DOWNWEIGHTED
            assert "非獨立來源" in d.reason

    def test_later_evidence_gets_weight_reduction(self):
        """後到者（index 較大者）權重 ×0.6。"""
        evs = [
            _make_evidence(
                ev_id="ev-001",
                content="Bitcoin surges past 70000 on institutional demand",
                source_type=SourceType.NEWS,
                source_weight=0.60,
            ),
            _make_evidence(
                ev_id="ev-002",
                content="Bitcoin surges past 70000 on institutional demand",
                source_type=SourceType.NEWS,
                source_weight=0.60,
            ),
        ]
        decisions = check_template_similarity(evs)

        # ev-001 (先到) weight 不變
        d_first = next(d for d in decisions if d.evidence_id == "ev-001")
        assert d_first.weight_after == d_first.weight_before  # 先到者不調權

        # ev-002 (後到) weight × 0.6
        d_later = next(d for d in decisions if d.evidence_id == "ev-002")
        assert d_later.weight_after == pytest.approx(0.60 * 0.6)

    def test_low_similarity_no_marking(self):
        """Jaccard < 0.8 → 不標記。"""
        evs = [
            _make_evidence(
                ev_id="ev-001",
                content="Bitcoin price climbed above resistance level today",
                source_type=SourceType.NEWS,
            ),
            _make_evidence(
                ev_id="ev-002",
                content="Ethereum developers announce new protocol upgrade schedule",
                source_type=SourceType.NEWS,
            ),
        ]
        decisions = check_template_similarity(evs)

        assert len(decisions) == 0

    def test_only_news_social_compared(self):
        """只有 news/social 的證據會被比較相似度。"""
        evs = [
            _make_evidence(
                ev_id="ev-001",
                content="Bitcoin surges past 70000 on institutional demand",
                source_type=SourceType.PRICE,  # 不比較
            ),
            _make_evidence(
                ev_id="ev-002",
                content="Bitcoin surges past 70000 on institutional demand",
                source_type=SourceType.ONCHAIN,  # 不比較
            ),
            _make_evidence(
                ev_id="ev-003",
                content="Bitcoin surges past 70000 on institutional demand",
                source_type=SourceType.MACRO,  # 不比較
            ),
        ]
        decisions = check_template_similarity(evs)

        assert len(decisions) == 0

    def test_mixed_types_only_eligible_compared(self):
        """混合類型中只有 news/social 被比較。"""
        evs = [
            _make_evidence(
                ev_id="ev-001",
                content="Bitcoin surges past 70000 on institutional demand",
                source_type=SourceType.PRICE,  # 不納入比較
            ),
            _make_evidence(
                ev_id="ev-002",
                content="Bitcoin surges past 70000 on institutional demand",
                source_type=SourceType.NEWS,
            ),
            _make_evidence(
                ev_id="ev-003",
                content="Bitcoin surges past 70000 on institutional demand",
                source_type=SourceType.SOCIAL,
            ),
        ]
        decisions = check_template_similarity(evs)

        # 只有 ev-002 和 ev-003 被比較並標記
        assert len(decisions) == 2
        ids = {d.evidence_id for d in decisions}
        assert ids == {"ev-002", "ev-003"}

    def test_boundary_similarity_08(self):
        """Jaccard 恰好 0.8 → 應標記。"""
        # 建構 Jaccard = 0.8 的內容：5 個共同 token / (5 + 1 unique) ≈ 需要精確控制
        # 4 共同 / 5 聯集 = 0.8
        evs = [
            _make_evidence(
                ev_id="ev-001",
                content="alpha beta gamma delta",
                source_type=SourceType.NEWS,
            ),
            _make_evidence(
                ev_id="ev-002",
                content="alpha beta gamma delta epsilon",
                source_type=SourceType.NEWS,
            ),
        ]
        # Jaccard: {alpha,beta,gamma,delta} ∩ {alpha,beta,gamma,delta,epsilon}
        #  = 4 / 5 = 0.8
        decisions = check_template_similarity(evs)

        assert len(decisions) == 2

    def test_boundary_similarity_below_08(self):
        """Jaccard 略低於 0.8 → 不標記。"""
        # 3 共同 / 5 聯集 = 0.6 < 0.8
        evs = [
            _make_evidence(
                ev_id="ev-001",
                content="alpha beta gamma",
                source_type=SourceType.NEWS,
            ),
            _make_evidence(
                ev_id="ev-002",
                content="alpha beta gamma delta epsilon",
                source_type=SourceType.NEWS,
            ),
        ]
        decisions = check_template_similarity(evs)

        assert len(decisions) == 0


# --- Jaccard 相似度單元測試 ---


class TestJaccardSimilarity:
    """測試 _jaccard_similarity 內部函式。"""

    def test_identical_text(self):
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert _jaccard_similarity("alpha beta", "gamma delta") == 0.0

    def test_partial_overlap(self):
        # {hello, world} ∩ {hello, there} = {hello}, union = {hello, world, there}
        assert _jaccard_similarity("hello world", "hello there") == pytest.approx(1 / 3)

    def test_empty_text_a(self):
        assert _jaccard_similarity("", "hello world") == 0.0

    def test_empty_text_b(self):
        assert _jaccard_similarity("hello world", "") == 0.0

    def test_both_empty(self):
        assert _jaccard_similarity("", "") == 0.0

    def test_case_insensitive(self):
        assert _jaccard_similarity("Hello World", "hello world") == 1.0


# --- F9 佔位測試 ---


class TestF9Placeholder:
    """確認 F9 情緒分布佔位不會造成模組崩潰。"""

    def test_f9_status_disabled(self):
        """F9 應標記 enabled: false。"""
        assert F9_STATUS == {"enabled": False}

    def test_module_import_does_not_crash(self):
        """模組匯入正常，不因缺少 F9 實作而錯誤。"""
        from agent.filters.content import F9_STATUS, apply_content_filters

        assert F9_STATUS["enabled"] is False


# --- apply_content_filters 整合測試 ---


class TestApplyContentFilters:
    """測試整合函式：執行全部 L2 過濾、套用權重、寫 log。"""

    def test_pr_weight_applied_to_evidence(self, tmp_path: Path):
        """PR 命中的證據的 source_weight 應被實際修改。"""
        logger = ExecutionLogger(tmp_path / "test.jsonl")
        ev = _make_evidence(
            ev_id="ev-001",
            content="BTC will skyrocket to 100k",
            source_weight=0.60,
        )
        apply_content_filters([ev], logger)

        assert ev.source_weight == pytest.approx(0.30)

    def test_similarity_weight_applied(self, tmp_path: Path):
        """相似度標記的後到者 source_weight 應被修改。"""
        logger = ExecutionLogger(tmp_path / "test.jsonl")
        evs = [
            _make_evidence(
                ev_id="ev-001",
                content="Bitcoin surges past 70000 on institutional demand",
                source_type=SourceType.NEWS,
                source_weight=0.60,
            ),
            _make_evidence(
                ev_id="ev-002",
                content="Bitcoin surges past 70000 on institutional demand",
                source_type=SourceType.NEWS,
                source_weight=0.60,
            ),
        ]
        apply_content_filters(evs, logger)

        # ev-001 先到者不調權
        assert evs[0].source_weight == 0.60
        # ev-002 後到者 × 0.6
        assert evs[1].source_weight == pytest.approx(0.36)

    def test_log_entries_written(self, tmp_path: Path):
        """每筆 FilterDecision 都應寫入 log，最後一筆為彙總。"""
        logger = ExecutionLogger(tmp_path / "test.jsonl")
        ev = _make_evidence(
            ev_id="ev-001",
            content="This is guaranteed to 100x",
            source_weight=0.60,
        )
        decisions = apply_content_filters([ev], logger)

        entries = logger.read_all()
        l2_entries = [e for e in entries if e.layer == PipelineLayer.CONTENT]

        # 至少有個別 decision log + summary
        assert len(l2_entries) >= 2

        # 彙總 log
        summary = [e for e in l2_entries if e.action == "l2_content_summary"]
        assert len(summary) == 1
        assert "pr_hits" in summary[0].metrics
        assert summary[0].metrics["f9"] == {"enabled": False}

    def test_no_hit_still_logs_summary(self, tmp_path: Path):
        """即使無命中，仍應寫入彙總 log。"""
        logger = ExecutionLogger(tmp_path / "test.jsonl")
        ev = _make_evidence(
            ev_id="ev-001",
            content="BTC traded at 65000 with moderate volume",
        )
        decisions = apply_content_filters([ev], logger)

        assert len(decisions) == 0

        entries = logger.read_all()
        l2_entries = [e for e in entries if e.layer == PipelineLayer.CONTENT]
        assert len(l2_entries) == 1  # 只有 summary
        assert l2_entries[0].action == "l2_content_summary"
        assert l2_entries[0].metrics["pr_hits"] == 0
        assert l2_entries[0].metrics["similarity_marks"] == 0

    def test_combined_pr_and_similarity(self, tmp_path: Path):
        """PR + 相似度同時命中時，權重取最低值。"""
        logger = ExecutionLogger(tmp_path / "test.jsonl")
        evs = [
            _make_evidence(
                ev_id="ev-001",
                content="Bitcoin will skyrocket guaranteed moonshot explosion",
                source_type=SourceType.NEWS,
                source_weight=0.60,
            ),
            _make_evidence(
                ev_id="ev-002",
                content="Bitcoin will skyrocket guaranteed moonshot explosion",
                source_type=SourceType.NEWS,
                source_weight=0.60,
            ),
        ]
        decisions = apply_content_filters(evs, logger)

        # ev-001: PR hit → 0.30, similarity 先到者不調 → min(0.30, 0.60) = 0.30
        assert evs[0].source_weight == pytest.approx(0.30)
        # ev-002: PR hit → 0.30, similarity 後到 → 0.36 → min(0.30, 0.36) = 0.30
        assert evs[1].source_weight == pytest.approx(0.30)

    def test_empty_evidences(self, tmp_path: Path):
        """空列表不報錯。"""
        logger = ExecutionLogger(tmp_path / "test.jsonl")
        decisions = apply_content_filters([], logger)

        assert decisions == []
        entries = logger.read_all()
        l2_entries = [e for e in entries if e.layer == PipelineLayer.CONTENT]
        assert len(l2_entries) == 1  # summary only

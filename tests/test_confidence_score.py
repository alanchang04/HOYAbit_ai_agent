"""L5 三維可解釋信心公式單元測試（horizon-aware-confidence R3）。

    Final = 0.4×資料品質 + 0.4×訊號一致性 + 0.2×證據強度 + 辯論調整(−15~+5)

本檔取代舊制「base(高75/中55/低35) + 權威加成 − 矛盾 − 缺口」的測試。
依 R6-4，舊測試案例**改寫為新公式的等價驗證而非刪除**——每個 class 上方註明
它對應舊制的哪一項，方便對帳：

| 舊制概念 | 新制對應 |
|---|---|
| base（LLM 自報高/中/低） | 已移除；base 改由三維加權算出，不再吃 LLM 主觀標籤 |
| auth_bonus（權威源占比） | Evidence Strength（各類平均 source_weight × 覆蓋度） |
| gap_penalty（缺失來源類別） | Data Confidence 的 missing 檔（該類得 0） |
| contradiction_penalty | 已移除；改由 Signal Consensus 反映方向分歧 |
| clamp 5–95 | 不變 |
"""

from __future__ import annotations

import pytest

from agent.reasoning.confidence import (
    CONSENSUS_NEUTRAL,
    DATA_COMPLETENESS_THRESHOLD,
    SOURCE_TYPE_CATEGORIES,
    TIER_COMPLETE,
    TIER_MISSING,
    TIER_PARTIAL,
    build_why_lines,
    compute_confidence,
    compute_data_confidence,
    compute_evidence_strength,
    compute_signal_consensus,
)
from agent.schemas import Evidence, HorizonClass, SourceType, now_iso


def _make_evidence(
    source_type: SourceType = SourceType.PRICE,
    source_weight: float = 0.5,
    eid: str = "ev-001",
    horizon: HorizonClass = HorizonClass.MEDIUM,
    window: tuple[str, str] | None = ("2026-07-01", "2026-07-30"),
) -> Evidence:
    return Evidence(
        id=eid,
        coin="BTC",
        source="test",
        fetched_at=now_iso(),
        content_reference="ref",
        related_claim="claim",
        source_type=source_type,
        source_weight=source_weight,
        horizon_class=horizon,
        window_start=window[0] if window else None,
        window_end=window[1] if window else None,
    )


def _full_coverage_evidences() -> list[Evidence]:
    """六類都達「完整」門檻的證據集合（source_weight 一律 0.8）。"""
    out: list[Evidence] = []
    n = 0
    for source_type in sorted(SOURCE_TYPE_CATEGORIES, key=lambda t: t.value):
        min_count, _ = DATA_COMPLETENESS_THRESHOLD[source_type]
        for _ in range(min_count):
            n += 1
            out.append(_make_evidence(source_type=source_type, eid=f"ev-{n:03d}", source_weight=0.8))
    return out


def _matrix(*pairs) -> list[dict]:
    return [{"source_type": t, "direction": d, "basis": []} for t, d in pairs]


def _all_bullish_matrix() -> dict:
    return {"direction_matrix": _matrix(*[(t.value, 1) for t in SOURCE_TYPE_CATEGORIES])}


# --- 資料品質（對應舊制 gap_penalty）---


class TestDataConfidence:
    def test_six_categories_include_derivatives(self):
        """D7 回歸：舊制 SOURCE_TYPE_CATEGORIES 只有五類，漏了 derivatives，
        導致 Ken 的衍生品資料再完整也不改善分數。新制必須是六類。"""
        assert SourceType.DERIVATIVES in SOURCE_TYPE_CATEGORIES
        assert len(SOURCE_TYPE_CATEGORIES) == 6

    def test_full_coverage_scores_100(self):
        score, detail = compute_data_confidence(_full_coverage_evidences())
        assert score == pytest.approx(100.0, abs=0.1)
        assert all(item["tier"] == TIER_COMPLETE for item in detail.values())

    def test_missing_type_scores_zero_for_that_type(self):
        evidences = [e for e in _full_coverage_evidences() if e.source_type != SourceType.SOCIAL]
        score, detail = compute_data_confidence(evidences)
        assert detail["social"]["tier"] == TIER_MISSING
        assert detail["social"]["score"] == 0
        assert score == pytest.approx(100.0 * 5 / 6, abs=0.1)

    def test_insufficient_count_is_partial_not_full(self):
        """需求方明講的情境：只有 2 篇新聞不能算 High Confidence。"""
        min_count, _ = DATA_COMPLETENESS_THRESHOLD[SourceType.NEWS]
        evidences = [
            _make_evidence(source_type=SourceType.NEWS, eid=f"ev-{i:03d}")
            for i in range(min_count - 1)
        ]
        _, detail = compute_data_confidence(evidences)
        assert detail["news"]["tier"] == TIER_PARTIAL
        assert "需" in detail["news"]["reason"]

    def test_insufficient_window_is_partial(self):
        min_count, min_window = DATA_COMPLETENESS_THRESHOLD[SourceType.PRICE]
        assert min_window > 0
        evidences = [
            _make_evidence(
                source_type=SourceType.PRICE, eid=f"ev-{i:03d}", window=("2026-07-29", "2026-07-30")
            )
            for i in range(min_count)
        ]
        _, detail = compute_data_confidence(evidences)
        assert detail["price"]["tier"] == TIER_PARTIAL

    def test_all_missing_scores_zero(self):
        score, detail = compute_data_confidence([])
        assert score == 0.0
        assert all(item["tier"] == TIER_MISSING for item in detail.values())


# --- 訊號一致性（對應舊制 contradiction_penalty）---


class TestSignalConsensus:
    @pytest.mark.parametrize(
        "directions, expected",
        [
            ([1, 1, 1, 1], 100.0),
            ([1, -1, 0, 1], 41.67),
            ([1, -1, -1, 1], 33.33),
        ],
    )
    def test_design_doc_worked_examples(self, directions, expected):
        """design.md §3.6.2 的三組驗算值（兩兩一致度，2026-07-28 定案）。"""
        types = ["price", "onchain", "news", "social"]
        evidences = [
            _make_evidence(source_type=SourceType(t), eid=f"ev-{i:03d}")
            for i, t in enumerate(types, 1)
        ]
        score, _ = compute_signal_consensus(_matrix(*zip(types, directions)), evidences)
        assert score == pytest.approx(expected, abs=0.5)

    @pytest.mark.parametrize(
        "name, directions, expected",
        [
            ("全部看多", [1, 1, 1, 1, 1, 1], 100.0),
            ("五多一空", [1, 1, 1, 1, 1, -1], 66.67),
            ("四多兩空", [1, 1, 1, 1, -1, -1], 46.67),
            ("三多三空", [1, 1, 1, -1, -1, -1], 40.0),
            # 全部中性＝完美一致、只是沒方向，必須是高分。
            # 候選方案 100×|mean| 在這裡會給 0，語意錯誤，是它被否決的主因之一。
            ("全部中性", [0, 0, 0, 0, 0, 0], 100.0),
        ],
    )
    def test_practical_scenarios_keep_discrimination(self, name, directions, expected):
        """六來源實務情境：分數要開展、不能全擠在低分區。

        原設計的線性 stdev 映射在「五多一空」只給 25 分——6 個來源裡 5 個同向
        卻被判成低共識，這是它被否決的主因（實算 729 種組合有 35.7% 落在 0-20）。
        """
        types = [t.value for t in sorted(SOURCE_TYPE_CATEGORIES, key=lambda x: x.value)]
        evidences = [
            _make_evidence(source_type=SourceType(t), eid=f"ev-{i:03d}")
            for i, t in enumerate(types, 1)
        ]
        score, _ = compute_signal_consensus(_matrix(*zip(types, directions)), evidences)
        assert score == pytest.approx(expected, abs=0.5), name

    def test_structural_evidence_excluded_from_vote(self):
        """R3-4：結構脈絡不參與共識投票，否則假矛盾會從這條路徑復活。"""
        evidences = [
            _make_evidence(source_type=SourceType.PRICE, eid="ev-001", horizon=HorizonClass.MEDIUM),
            _make_evidence(source_type=SourceType.NEWS, eid="ev-002", horizon=HorizonClass.MEDIUM),
            _make_evidence(
                source_type=SourceType.MACRO, eid="ev-003", horizon=HorizonClass.STRUCTURAL
            ),
        ]
        # macro 方向與其他兩類相反，但它是結構脈絡 → 不該把共識拉低
        score, detail = compute_signal_consensus(
            _matrix(("price", 1), ("news", 1), ("macro", -1)), evidences
        )
        assert score == 100.0
        assert [row["source_type"] for row in detail["directions"]] == ["price", "news"]

    def test_dynamic_primary_horizon_promotes_long_to_current(self):
        """R7-3：問「最近一年」時主視野是 structural，long 帶就變成當前訊號。"""
        evidences = [
            _make_evidence(source_type=SourceType.PRICE, eid="ev-001", horizon=HorizonClass.LONG),
            _make_evidence(source_type=SourceType.NEWS, eid="ev-002", horizon=HorizonClass.MEDIUM),
        ]
        _, default_detail = compute_signal_consensus(
            _matrix(("price", 1), ("news", -1)), evidences
        )
        assert [r["source_type"] for r in default_detail["directions"]] == ["news"]

        _, yearly_detail = compute_signal_consensus(
            _matrix(("price", 1), ("news", -1)),
            evidences,
            primary_horizon=HorizonClass.STRUCTURAL,
        )
        assert {r["source_type"] for r in yearly_detail["directions"]} == {"price", "news"}

    def test_single_source_degrades_to_neutral(self):
        evidences = [_make_evidence(source_type=SourceType.PRICE, eid="ev-001")]
        score, detail = compute_signal_consensus(_matrix(("price", 1)), evidences)
        assert score == CONSENSUS_NEUTRAL
        assert detail["degraded"] is True

    def test_missing_matrix_degrades_to_neutral(self):
        """R3-15：Step B 沒產出 direction_matrix 時以中性 50 計算並揭露。"""
        score, detail = compute_signal_consensus([], _full_coverage_evidences())
        assert score == CONSENSUS_NEUTRAL
        assert detail["degraded"] is True

    def test_duplicate_source_type_counted_once(self):
        evidences = [
            _make_evidence(source_type=SourceType.PRICE, eid="ev-001"),
            _make_evidence(source_type=SourceType.NEWS, eid="ev-002"),
        ]
        _, detail = compute_signal_consensus(
            _matrix(("price", 1), ("price", -1), ("news", 1)), evidences
        )
        assert detail["sample_size"] == 2


# --- 證據強度（對應舊制 auth_bonus）---


class TestEvidenceStrength:
    def test_higher_weight_yields_higher_strength(self):
        low = [_make_evidence(source_weight=0.3, eid="ev-001")]
        high = [_make_evidence(source_weight=0.9, eid="ev-001")]
        assert compute_evidence_strength(high)[0] > compute_evidence_strength(low)[0]

    def test_broader_coverage_yields_higher_strength(self):
        narrow = [_make_evidence(source_type=SourceType.PRICE, source_weight=0.8, eid="ev-001")]
        broad = [
            _make_evidence(source_type=t, source_weight=0.8, eid=f"ev-{i:03d}")
            for i, t in enumerate(sorted(SOURCE_TYPE_CATEGORIES, key=lambda x: x.value), 1)
        ]
        assert compute_evidence_strength(broad)[0] > compute_evidence_strength(narrow)[0]

    def test_full_coverage_full_weight_is_100(self):
        evidences = [
            _make_evidence(source_type=t, source_weight=1.0, eid=f"ev-{i:03d}")
            for i, t in enumerate(sorted(SOURCE_TYPE_CATEGORIES, key=lambda x: x.value), 1)
        ]
        assert compute_evidence_strength(evidences)[0] == pytest.approx(100.0, abs=0.1)

    def test_empty_is_zero(self):
        assert compute_evidence_strength([])[0] == 0.0


# --- 辯論調整（新制，無舊制對應）---


class TestDebateAdjustment:
    def test_no_reason_forces_zero(self):
        """R3-10：無理由不得調整——強制可稽核。"""
        _, bd = compute_confidence(
            _full_coverage_evidences(), {}, debate_adjustment=-10, debate_adjustment_reason="  "
        )
        assert bd["debate_adjustment"] == 0
        assert "未提供調整理由" in bd["debate_adjustment_note"]

    @pytest.mark.parametrize("raw, expected", [(-99, -15), (99, 5), (-15, -15), (5, 5), (0, 0)])
    def test_clamped_to_asymmetric_range(self, raw, expected):
        """R3-9：範圍不對稱是刻意的——辯論只能大幅下修、小幅上調（ADR-5）。"""
        _, bd = compute_confidence(
            _full_coverage_evidences(), {}, debate_adjustment=raw, debate_adjustment_reason="理由"
        )
        assert bd["debate_adjustment"] == expected

    def test_out_of_range_logs_raw_value(self):
        _, bd = compute_confidence(
            _full_coverage_evidences(), {}, debate_adjustment=-99, debate_adjustment_reason="理由"
        )
        assert bd["debate_adjustment_raw"] == -99
        assert "已夾值" in bd["debate_adjustment_note"]

    def test_non_numeric_treated_as_zero(self):
        _, bd = compute_confidence(
            _full_coverage_evidences(), {}, debate_adjustment="很多", debate_adjustment_reason="理由"
        )
        assert bd["debate_adjustment"] == 0

    @pytest.mark.parametrize("raw, expected", [("-8", -8), (" -8 ", -8), ("-8.0", -8), ("5", 5), ("0", 0)])
    def test_numeric_string_is_honoured(self, raw, expected):
        """模型把數值包成字串是 JSON 輸出的常見偏差，不該讓整段辯論調整靜默歸零。

        pipeline 是把 Step D 的 `debate_adjustment` 原樣傳進來的，寬鬆度必須與
        `_coerce_direction()` 對齊——同一條鏈上不該有兩套標準。
        """
        _, bd = compute_confidence(
            _full_coverage_evidences(), {}, debate_adjustment=raw, debate_adjustment_reason="理由"
        )
        assert bd["debate_adjustment"] == expected
        assert bd["debate_adjustment_note"] == ""      # 正常受理，不該留「未提供有效調整值」

    @pytest.mark.parametrize("raw", [True, False, None, "很多", "", "-", float("nan"), float("inf")])
    def test_unreadable_values_stay_zero(self, raw):
        """bool 是 int 子類、inf/nan 會讓 int() 爆炸——放寬字串容忍後這些仍須擋住。"""
        _, bd = compute_confidence(
            _full_coverage_evidences(), {}, debate_adjustment=raw, debate_adjustment_reason="理由"
        )
        assert bd["debate_adjustment"] == 0
        assert bd["debate_adjustment_raw"] is None

    def test_out_of_range_numeric_string_still_clamped(self):
        """字串進來也要走同一條夾值路徑，並照樣把原始值記進 breakdown。"""
        _, bd = compute_confidence(
            _full_coverage_evidences(), {}, debate_adjustment="-99", debate_adjustment_reason="理由"
        )
        assert bd["debate_adjustment"] == -15
        assert bd["debate_adjustment_raw"] == -99
        assert "已夾值" in bd["debate_adjustment_note"]


# --- 夾值（沿用舊制概念，行為不變）---


class TestClamp:
    def test_never_above_95(self):
        evidences = [
            _make_evidence(source_type=t, source_weight=1.0, eid=f"ev-{i:03d}")
            for i, t in enumerate(sorted(SOURCE_TYPE_CATEGORIES, key=lambda x: x.value), 1)
        ]
        score, _ = compute_confidence(
            evidences, _all_bullish_matrix(), debate_adjustment=5, debate_adjustment_reason="理由"
        )
        assert score <= 95

    def test_never_below_5(self):
        score, _ = compute_confidence([], {}, debate_adjustment=-15, debate_adjustment_reason="理由")
        assert score >= 5


# --- 結構脈絡不扣分（R2-8，本規格的核心修正）---


class TestStructuralContextDoesNotPenalize:
    def test_structural_context_absent_from_any_penalty_path(self):
        """跨尺度差異是位置關係不是矛盾——有再多 structural_context 都不該扣分。"""
        evidences = _full_coverage_evidences()
        matrix = _all_bullish_matrix()

        clean, _ = compute_confidence(evidences, matrix)
        with_context, bd = compute_confidence(
            evidences, {**matrix, "structural_context": ["A", "B", "C", "D", "E"]}
        )
        assert clean == with_context
        assert bd["structural_context_count"] == 5

    def test_contradictions_no_longer_directly_penalize(self):
        """舊制 contradiction_penalty 直接照矛盾數扣分（最多 −15），新制移除——
        方向分歧改由 Signal Consensus 反映，避免假矛盾被二次懲罰。"""
        evidences = _full_coverage_evidences()
        matrix = _all_bullish_matrix()
        without, _ = compute_confidence(evidences, matrix)
        with_contradictions, _ = compute_confidence(
            evidences, {**matrix, "contradictions": ["x"] * 5}
        )
        assert without == with_contradictions


# --- Why this confidence（R3-13）---


class TestWhyLines:
    def test_missing_type_produces_warning_line(self):
        evidences = [e for e in _full_coverage_evidences() if e.source_type != SourceType.SOCIAL]
        _, bd = compute_confidence(evidences, {})
        assert any("social" in line and "無可用證據" in line for line in bd["why"])

    def test_complete_type_produces_check_line(self):
        _, bd = compute_confidence(_full_coverage_evidences(), {})
        assert any(line.startswith("✅") and "資料完整" in line for line in bd["why"])

    def test_debate_downgrade_produces_line_with_reason(self):
        _, bd = compute_confidence(
            _full_coverage_evidences(),
            {},
            debate_adjustment=-8,
            debate_adjustment_reason="反方對鏈上活躍度的批評成立",
        )
        assert any("辯論後下修 8 分" in line and "鏈上活躍度" in line for line in bd["why"])

    def test_high_consensus_produces_line(self):
        _, bd = compute_confidence(_full_coverage_evidences(), _all_bullish_matrix())
        assert any("訊號共識高" in line for line in bd["why"])

    def test_divergent_consensus_produces_warning(self):
        _, bd = compute_confidence(
            _full_coverage_evidences(),
            {"direction_matrix": _matrix(("price", 1), ("news", -1), ("social", -1), ("macro", 1))},
        )
        assert any("缺乏共識" in line for line in bd["why"])

    def test_is_deterministic(self):
        """R3-13：決定性生成，不呼叫 LLM——同輸入必同輸出。"""
        evidences = _full_coverage_evidences()
        cv = {"direction_matrix": _matrix(("price", 1), ("news", -1)), "structural_context": ["x"]}
        first = build_why_lines(compute_confidence(evidences, cv)[1])
        second = build_why_lines(compute_confidence(evidences, cv)[1])
        assert first == second


# --- 手算樣本（對應舊制 TestHandCalculatedSample）---


class TestHandCalculatedSample:
    def test_full_data_full_consensus_no_debate(self):
        """六類齊全（Data=100）＋方向全一致（Consensus=100）＋權重 0.8（Strength=80）
        → base = 0.4×100 + 0.4×100 + 0.2×80 = 96 → 夾到 95。"""
        score, bd = compute_confidence(_full_coverage_evidences(), _all_bullish_matrix())
        assert bd["data_confidence"] == pytest.approx(100.0, abs=0.1)
        assert bd["signal_consensus"] == pytest.approx(100.0, abs=0.1)
        assert bd["evidence_strength"] == pytest.approx(80.0, abs=0.1)
        assert bd["base"] == pytest.approx(96.0, abs=0.1)
        assert score == 95  # 夾值

    def test_sparse_data_drags_score_down(self):
        """需求方舉的反例：只有價格、沒有鏈上/社群、只有 2 篇新聞
        → 即使價格很漂亮也不能說 High Confidence。"""
        evidences = [
            _make_evidence(source_type=SourceType.PRICE, eid=f"ev-{i:03d}", source_weight=0.95)
            for i in range(1, 4)
        ] + [
            _make_evidence(source_type=SourceType.NEWS, eid="ev-010", source_weight=0.6),
            _make_evidence(source_type=SourceType.NEWS, eid="ev-011", source_weight=0.6),
        ]
        score, bd = compute_confidence(evidences, {})
        assert bd["data_confidence_detail"]["price"]["tier"] == TIER_COMPLETE
        assert bd["data_confidence_detail"]["news"]["tier"] == TIER_PARTIAL
        assert bd["data_confidence_detail"]["onchain"]["tier"] == TIER_MISSING
        assert score < 55, f"資料稀疏卻拿到 {score} 分，Data Confidence 沒發揮作用"

    def test_debate_adjustment_applied_on_top_of_base(self):
        """辯論調整加在 base 上、夾值在最後（R3-11）。

        刻意用「資料略有缺口」的集合而非滿分集合——滿分時 base=96 會先被夾到 95，
        `plain - 10` 這種算術就不成立了（夾值吃掉了 1 分）。
        """
        evidences = [e for e in _full_coverage_evidences() if e.source_type != SourceType.SOCIAL]
        cv = {"direction_matrix": _matrix(("price", 1), ("news", 1))}
        plain, bd_plain = compute_confidence(evidences, cv)
        adjusted, bd_adj = compute_confidence(
            evidences, cv, debate_adjustment=-10, debate_adjustment_reason="反方批評成立"
        )
        assert bd_plain["base"] == bd_adj["base"]
        assert plain < 95, "前提：未夾值，否則下面的算術不成立"
        assert adjusted == plain - 10
        assert bd_adj["final"] == round(bd_adj["base"] - 10)


class TestLongDebateReasonDoesNotBreakOutput:
    """回歸測試（2026-07-28 真實 Bedrock 執行發現）：prompt 雖限 80 字，
    但 LLM 不保證遵守——實測回過 700+ 字的辯論評析，把報告的信心分項表格整個撐爆。
    呈現層必須自己防守，不能假設模型會聽話。"""

    LONG_REASON = "反方對正方論證的五大批評全部成立且具毀滅性：" + "（詳細論述）" * 120

    def test_why_line_is_truncated(self):
        _, bd = compute_confidence(
            _full_coverage_evidences(),
            {},
            debate_adjustment=-12,
            debate_adjustment_reason=self.LONG_REASON,
        )
        line = next(l for l in bd["why"] if "辯論後下修" in l)
        assert len(line) < 200, f"why 條列被長理由淹掉：{len(line)} 字"
        assert "完整理由見" in line

    def test_full_reason_still_preserved_in_breakdown(self):
        """截斷只發生在呈現，breakdown 必須保留完整原文供稽核。"""
        _, bd = compute_confidence(
            _full_coverage_evidences(),
            {},
            debate_adjustment=-12,
            debate_adjustment_reason=self.LONG_REASON,
        )
        assert bd["debate_adjustment_reason"] == self.LONG_REASON

    def test_reason_with_pipe_does_not_break_markdown_table(self):
        """理由含 | 會把 markdown 表格的欄位切錯。"""
        from agent.report.builder import _table_safe

        assert "|" not in _table_safe("理由 A | 理由 B")

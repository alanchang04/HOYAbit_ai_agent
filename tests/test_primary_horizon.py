"""主視野判定與角色推導（horizon-aware-confidence R7-1/R7-2/R7-3）。

判定必須是決定性的規則式比對，不呼叫 LLM——可規則化的事不該花一次 LLM 呼叫，
而且 LLM 推斷不可複現（design.md ADR-7）。
"""

from __future__ import annotations

import pytest

from agent.collectors.horizon import resolve_primary_horizon
from agent.schemas import (
    DEFAULT_PRIMARY_HORIZON,
    HORIZON_ORDER,
    HORIZON_STANDARD_DAYS,
    HorizonClass,
    horizon_for_days,
    is_current_signal,
)


class TestStandardGranularity:
    """R7-1：五檔標準粒度（日／10日／月／季／年）與五帶一一對應。"""

    def test_five_bands_five_granularities(self):
        assert len(HORIZON_ORDER) == 5
        assert set(HORIZON_STANDARD_DAYS) == set(HORIZON_ORDER)

    @pytest.mark.parametrize(
        "days, expected",
        [
            (1, HorizonClass.SPOT),
            (10, HorizonClass.SHORT),
            (30, HorizonClass.MEDIUM),
            (90, HorizonClass.LONG),
            (365, HorizonClass.STRUCTURAL),
        ],
    )
    def test_standard_days_map_to_own_band(self, days, expected):
        assert horizon_for_days(days) == expected

    @pytest.mark.parametrize(
        "days, expected",
        [
            (1, HorizonClass.SPOT),
            (2, HorizonClass.SHORT),
            (10, HorizonClass.SHORT),
            (11, HorizonClass.MEDIUM),
            (30, HorizonClass.MEDIUM),
            (31, HorizonClass.LONG),
            (180, HorizonClass.LONG),
            (181, HorizonClass.STRUCTURAL),
        ],
    )
    def test_boundary_values(self, days, expected):
        assert horizon_for_days(days) == expected


class TestResolvePrimaryHorizon:
    """R7-2：題目文字 → 主視野。"""

    @pytest.mark.parametrize(
        "question, expected",
        [
            ("分析 BTC 最近兩週的整體市場狀態", HorizonClass.MEDIUM),
            ("過去一年 BTC 表現如何", HorizonClass.STRUCTURAL),
            ("最近半年的趨勢", HorizonClass.LONG),
            ("最近一季 ETH 的鏈上活躍度", HorizonClass.LONG),
            ("近一個月 SOL 走勢", HorizonClass.MEDIUM),
            ("過去一週的資金流向", HorizonClass.SHORT),
            ("今天 BTC 發生什麼事", HorizonClass.SPOT),
        ],
    )
    def test_keyword_detection(self, question, expected):
        horizon, fragment = resolve_primary_horizon(question)
        assert horizon == expected
        assert fragment, "必須回傳觸發判定的片段供報告揭露（R7-7）"

    def test_no_match_falls_back_to_default(self):
        horizon, fragment = resolve_primary_horizon("比較 BTC 與 ETH 的流動性")
        assert horizon == DEFAULT_PRIMARY_HORIZON
        assert fragment == ""

    def test_empty_question_falls_back(self):
        assert resolve_primary_horizon("")[0] == DEFAULT_PRIMARY_HORIZON

    def test_longer_phrase_wins_over_shorter(self):
        """「過去一年」不可被較短的「一年」以外樣式搶先命中而算出錯誤天數。"""
        assert resolve_primary_horizon("過去一年 BTC 表現")[0] == HorizonClass.STRUCTURAL
        assert resolve_primary_horizon("最近一週表現")[0] == HorizonClass.SHORT

    @pytest.mark.parametrize("question", ["BTC 現在的市場狀態如何", "目前 ETH 值得關注嗎", "當前市場情緒"])
    def test_framing_words_are_not_time_ranges(self, question):
        """「現在／目前／當前」是語氣詞不是時間範圍。

        若誤判成 spot，short/medium 全會被打成結構脈絡、排除在共識投票外，
        剛好與本規格要解決的問題相反——這是實作時實際踩到的坑。
        """
        assert resolve_primary_horizon(question)[0] == DEFAULT_PRIMARY_HORIZON

    def test_is_deterministic(self):
        question = "過去一季 BTC 的表現"
        assert resolve_primary_horizon(question) == resolve_primary_horizon(question)


class TestCurrentSignalRoleDerivation:
    """R7-3：角色相對主視野推導，不寫死綁帶。"""

    def test_default_matches_original_three_band_grouping(self):
        """主視野為預設 medium 時，推導結果與原設計完全相同（嚴格超集，不破壞既有行為）。"""
        for horizon in (HorizonClass.SPOT, HorizonClass.SHORT, HorizonClass.MEDIUM):
            assert is_current_signal(horizon) is True
        for horizon in (HorizonClass.LONG, HorizonClass.STRUCTURAL):
            assert is_current_signal(horizon) is False

    def test_yearly_question_promotes_structural_to_current(self):
        """問「最近一年」時，五年結構資料才是該用的資料，不該被排除在共識投票外。"""
        for horizon in HORIZON_ORDER:
            assert is_current_signal(horizon, HorizonClass.STRUCTURAL) is True

    def test_daily_question_demotes_everything_above_spot(self):
        assert is_current_signal(HorizonClass.SPOT, HorizonClass.SPOT) is True
        for horizon in HORIZON_ORDER[1:]:
            assert is_current_signal(horizon, HorizonClass.SPOT) is False

    def test_quarterly_question_includes_up_to_long(self):
        primary = HorizonClass.LONG
        assert is_current_signal(HorizonClass.MEDIUM, primary) is True
        assert is_current_signal(HorizonClass.LONG, primary) is True
        assert is_current_signal(HorizonClass.STRUCTURAL, primary) is False

    def test_none_primary_equals_default(self):
        for horizon in HORIZON_ORDER:
            assert is_current_signal(horizon, None) == is_current_signal(
                horizon, DEFAULT_PRIMARY_HORIZON
            )


class TestReportDisclosure:
    """R7-7：報告要揭露主判斷尺度與判定依據，讀者才能檢查系統有沒有誤解題目。"""

    def _report(self, question: str) -> str:
        from agent.orchestrator import run_pipeline
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            return run_pipeline(
                coin="BTC", question=question, dry_run=True, output_dir=tmp
            ).report_markdown

    def test_discloses_horizon_and_basis(self):
        md = self._report("過去一年 BTC 表現如何")
        assert "主判斷尺度" in md
        assert "近一年以上" in md
        assert "過去一年" in md, "必須寫出觸發判定的題目片段"

    def test_discloses_default_when_unspecified(self):
        md = self._report("比較 BTC 與 ETH 的流動性差異")
        assert "主判斷尺度" in md
        assert "未明示" in md

    def test_medium_question_says_monthly_scale(self):
        md = self._report("分析 BTC 最近兩週的整體市場狀態")
        assert "近一個月（中期）" in md

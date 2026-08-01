"""static/signal_importance.json 載入與查詢（R8-3）。

值本身是 alanchang 依 design.md 草擬的暫定值，尚未與 Ken 對過（見該 JSON 檔
$comment）——這裡測的是「載入機制正確、缺陷時優雅降級」，不是校準數值本身。
"""

from __future__ import annotations

import json

import pytest

from agent.filters.signal_importance import (
    DEFAULT_IMPORTANCE,
    get_base_importance,
    load_signal_importance_config,
)


class TestLoadConfig:
    def test_loads_real_file(self):
        """賽前實際使用的檔案要能載入成功，不是只有測試 fixture 過得了。"""
        config = load_signal_importance_config()
        assert config is not None
        assert "by_source_type" in config

    def test_missing_file_returns_none(self, tmp_path):
        config = load_signal_importance_config(tmp_path / "nope.json")
        assert config is None

    def test_malformed_json_returns_none(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        assert load_signal_importance_config(bad) is None

    def test_missing_by_source_type_returns_none(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"by_question_type": {}}), encoding="utf-8")
        assert load_signal_importance_config(p) is None

    def test_by_question_type_not_dict_returns_none(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(
            json.dumps({"by_source_type": {"price": 1.0}, "by_question_type": []}),
            encoding="utf-8",
        )
        assert load_signal_importance_config(p) is None


class TestGetBaseImportance:
    CONFIG = {
        "by_source_type": {"price": 1.0, "social": 0.5},
        "by_question_type": {"comparison": {"social": 0.3}},
    }

    def test_falls_back_to_by_source_type_when_no_override(self):
        assert get_base_importance("price", "multi_source", self.CONFIG) == 1.0
        assert get_base_importance("social", "multi_source", self.CONFIG) == 0.5

    def test_question_type_override_takes_priority(self):
        """比較題型下 social 該用覆寫值 0.3，不是全域預設 0.5。"""
        assert get_base_importance("social", "comparison", self.CONFIG) == 0.3

    def test_override_only_affects_listed_source_type(self):
        """comparison 覆寫層只列了 social，price 仍沿用全域預設。"""
        assert get_base_importance("price", "comparison", self.CONFIG) == 1.0

    def test_unmatched_source_type_uses_default(self):
        assert get_base_importance("unknown_type", "multi_source", self.CONFIG) == DEFAULT_IMPORTANCE

    def test_none_question_type_skips_override_lookup(self):
        assert get_base_importance("social", None, self.CONFIG) == 0.5

    def test_none_config_uses_default(self):
        """R6-1 降級優先：設定檔載入失敗時不得中斷，回保底值。"""
        assert get_base_importance("price", "comparison", None) == DEFAULT_IMPORTANCE

    def test_empty_config_dict_uses_default(self):
        assert get_base_importance("price", "comparison", {}) == DEFAULT_IMPORTANCE

    @pytest.mark.parametrize("bad_value", [{"by_source_type": {"price": "not-a-number"}}])
    def test_non_numeric_value_falls_back_to_default(self, bad_value):
        assert get_base_importance("price", None, bad_value) == DEFAULT_IMPORTANCE


class TestRealConfigValues:
    """鎖住 design.md §3.9.3 草擬的暫定值，數值變動（例如 Ken 校準後）時這裡會
    紅，提醒回頭確認變動是否符合預期——不是禁止改，是禁止悄悄改。"""

    def test_comparison_demotes_social_and_news(self):
        config = load_signal_importance_config()
        assert get_base_importance("social", "comparison", config) == 0.3
        assert get_base_importance("news", "comparison", config) == 0.6

    def test_price_is_highest_weighted_by_default(self):
        config = load_signal_importance_config()
        assert get_base_importance("price", None, config) == 1.0
        assert get_base_importance("social", None, config) == 0.5
        assert get_base_importance("price", None, config) > get_base_importance(
            "social", None, config
        )

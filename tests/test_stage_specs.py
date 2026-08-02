"""13_流程圖迭代定案v2.md Stage 2／Stage 5：規格檔必須是單一事實來源。

Stage 3（Knowledge）與 Stage 4（Weight）早就是「.md 是單一事實來源，程式只負責讀」，
Stage 2 的 `*.yaml` 跟 Stage 5 的卡片 `*.md` 卻只被寫在註解裡——端點、參數、欄位清單、
卡片有哪些格子全寫死在 `webapp/stage1_demo_api.py`。改規格檔不會改行為，等於同一件事
有兩份真相。`webapp/stage_specs.py` 補的就是這兩格，這份測試守住它。

這裡刻意不打網路：驗的是「規格檔讀不讀得起來、欄位分類對不對」，不是資料源可不可用。
"""

import pytest

from webapp.stage_specs import (
    SpecError,
    build_evidence_card,
    compute_series_features,
    load_card_spec,
    load_feature_spec,
    load_value_source,
    pct_change_vs_month,
    ranking_keys,
    render_params,
)

DEMO_FACTORS = ["funding_rate", "active_address", "cpi", "liquidation"]


# ---------------------------------------------------------------------------
# 規格檔本身讀得起來（liquidation 卡片曾經因為 traceability 底下直接縮排接 note
# 而是不合法 YAML，整份解析失敗——那種錯只有真的去讀才會被發現）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("factor_id", DEMO_FACTORS)
def test_feature_spec_loads(factor_id):
    spec = load_feature_spec(factor_id)
    assert spec["factor"] == factor_id


@pytest.mark.parametrize("factor_id", DEMO_FACTORS)
def test_card_spec_loads(factor_id):
    spec = load_card_spec(factor_id)
    assert "evidence" in spec


def test_missing_spec_raises_instead_of_falling_back():
    """讀不到規格檔要吵，不能退回預設值——靜靜用寫死的值跑起來就是這支模組要解決的問題本身。"""
    with pytest.raises(SpecError):
        load_feature_spec("factor_that_does_not_exist")


@pytest.mark.parametrize("factor_id", DEMO_FACTORS)
def test_ranking_key_matches_13_decision(factor_id):
    """13 拍板「一律照 evidence_weight 排序」，每張卡自己的 .md 都要宣告，排序層才驗證得了。"""
    assert ranking_keys()[factor_id] == "evidence_weight"


# ---------------------------------------------------------------------------
# Stage 2：yaml 決定端點、參數、有哪些欄位
# ---------------------------------------------------------------------------

def test_params_template_uses_this_run_values():
    spec = load_feature_spec("funding_rate")
    params = render_params(spec["params"], symbol="BTCUSDT", window_days=14)
    # limit = window（天）× 每天 3 筆結算，換算寫在 yaml 的 `{window * 3}` 樣板裡
    assert params == {"symbol": "BTCUSDT", "limit": "42"}


def test_params_template_renders_inline_suffix():
    spec = load_feature_spec("active_address")
    params = render_params(spec["params"], window_days=30)
    assert params["timespan"] == "30days"
    # yaml 的 `cors: true` 是 YAML bool，送進 query string 要是小寫字串
    assert params["cors"] == "true"


def test_unknown_placeholder_raises():
    with pytest.raises(SpecError):
        render_params({"x": "{horizon}"}, window_days=14)


def test_missing_value_for_placeholder_raises():
    with pytest.raises(SpecError):
        render_params({"symbol": "{symbol}"}, window_days=14)


def test_statistical_fields_are_computed_from_the_series():
    spec = load_feature_spec("active_address")
    series = [float(i) for i in range(1, 31)]  # 1..30，日頻
    features, report = compute_series_features(
        "active_address", spec, series, expected_count=30
    )
    assert features["current_value"] == 30
    assert features["previous_value"] == 29
    assert features["delta"] == 1
    assert features["sample_size"] == 30
    assert features["rolling_max"] == 30
    assert features["slope"] == pytest.approx(1.0)      # 完美線性，斜率就是 1
    assert features["slope_7d"] == pytest.approx(1.0)
    assert features["missing_ratio"] == 0.0
    assert report["fields_unimplemented"] == []


def test_samples_per_day_scales_the_n_day_windows():
    """funding rate 每 8 小時一筆，「近 7 天」＝近 21 筆，不是近 7 筆。
    這是它跟日頻 factor 真正的差別，寫在 yaml 的 samples_per_day 裡。"""
    spec = load_feature_spec("funding_rate")
    assert int(spec["samples_per_day"]) == 3

    # 前 21 筆固定 10、後 21 筆固定 20：近 7 天（21 筆）全在後半段，斜率必為 0；
    # 若誤用「近 7 筆」也同樣落在後半段——所以改用 roc_1d 檢查（回看 3 筆 vs 1 筆）
    series = [10.0] * 21 + [20.0] * 20 + [30.0]
    features, _ = compute_series_features("funding_rate", spec, series)
    # roc_1d 回看一天＝3 筆前（20.0），不是前一筆
    assert features["roc_1d"] == pytest.approx((30.0 - 20.0) / 20.0 * 100)
    # roc_7d 回看 7 天＝21 筆前（10.0）
    assert features["roc_7d"] == pytest.approx((30.0 - 10.0) / 10.0 * 100)


def test_null_fields_are_not_emitted_at_all():
    """liquidation 的 slope／roc／rolling_*／percentile 在 yaml 明寫 null＝結構性沒有
    （查歷史清算單的 REST API 已停用）。整格不存在才傳達得出「這個概念對這個 factor
    不成立」；放 None 會被讀成「這次剛好沒算出來，下次可能有」。"""
    spec = load_feature_spec("liquidation")
    features, report = compute_series_features("liquidation", spec, [1.0, 2.0, 3.0])
    for field in ("percentile", "slope", "roc_7d", "rolling_mean", "z_score"):
        assert field not in features
        assert field in report["fields_null_by_design"]


def test_spec_declared_value_beats_the_generic_algorithm():
    """同一個欄位名，規格檔宣告「值」還是「算法」決定行為：
    active_address.yaml 寫 `sample_size: len(series)`（算），
    liquidation.yaml 寫 `sample_size: 1`（每次執行就是一個觀察窗，不是多筆樣本）。
    通用算法不該蓋掉規格檔明講的數字。"""
    liq_spec = load_feature_spec("liquidation")
    features, report = compute_series_features("liquidation", liq_spec, [])
    assert features["sample_size"] == 1
    assert "sample_size" in report["fields_from_spec_literal"]

    aa_spec = load_feature_spec("active_address")
    features, _ = compute_series_features("active_address", aa_spec, [1.0, 2.0, 3.0])
    assert features["sample_size"] == 3


def test_event_skeleton_fields_come_straight_from_the_spec_file():
    """cpi.yaml 是 Event Factor 骨架：announcement_time／next_release 這些不是公式，
    規格檔寫的就是資料本身，照抄不另外算。"""
    spec = load_feature_spec("cpi")
    features, report = compute_series_features("cpi", spec, [])
    assert features["announcement_time"] == spec["announcement_time"]
    assert features["next_release"] == spec["next_release"]
    assert "announcement_time" in report["fields_from_spec_literal"]


def test_endpoint_supplied_fields_are_not_reported_as_missing():
    """crowd_label 由端點補（agent/collectors/derivatives.crowd_label），
    傳進來就不該再被列成「yaml 有定義但沒實作」。"""
    spec = load_feature_spec("funding_rate")
    features, report = compute_series_features(
        "funding_rate", spec, [0.0001] * 10, provided={"crowd_label": "crowded_long"}
    )
    assert features["crowd_label"] == "crowded_long"
    assert report["fields_unimplemented"] == []


def test_tiny_magnitudes_survive_rounding():
    """funding rate 量級 1e-5、斜率 1e-8。四捨五入到固定小數位會把整排 slope
    壓成 0.0，看起來像「趨勢是平的」——那是顯示造成的假結論。"""
    spec = load_feature_spec("funding_rate")
    series = [1e-5 + 1e-8 * i for i in range(30)]
    features, _ = compute_series_features("funding_rate", spec, series)
    assert features["slope_30d"] != 0
    assert features["slope_30d"] == pytest.approx(1e-8, rel=1e-3)


# ---------------------------------------------------------------------------
# cpi 的數值端點：Event 骨架沒有這格，另外開 value_source
# ---------------------------------------------------------------------------

def test_cpi_value_source_is_readable():
    """cpi.yaml 的 feature 是 Event 骨架（只有事件時程），數值端點放在 value_source。
    沒有這段，FRED 那支 URL 就只能繼續寫死在程式裡。"""
    vs = load_value_source("cpi")
    assert vs["endpoint"].startswith("https://fred.stlouisfed.org")
    assert vs["params"]["id"] == "CPIAUCSL"
    assert vs["window_unit"] == "month"
    assert set(vs["fields"]) == {"current_value", "percentile", "mom_pct", "yoy_pct"}


@pytest.mark.parametrize("factor_id", ["funding_rate", "active_address", "liquidation"])
def test_statistical_factors_have_no_value_source(factor_id):
    """value_source 是 Event Factor 特有的形狀，Statistical 的端點就在 feature.endpoint。"""
    assert load_value_source(factor_id) is None


def test_yoy_aligns_by_date_not_position():
    """FRED 的 CPIAUCSL 會缺月（實測缺 2025-10）。用 series[-13] 這種位置索引，
    缺一個月就整個位移一格，年增率會從 3.46% 變成 3.73%——數字合理、不會報錯，
    只有拿日期對照才看得出來錯了。"""
    dated = [
        ("2025-06-01", 321.435),
        ("2025-07-01", 322.0),
        ("2025-08-01", 323.0),
        ("2025-09-01", 324.0),
        # 2025-10 缺（資料源真的會這樣）
        ("2025-11-01", 326.0),
        ("2025-12-01", 327.0),
        ("2026-01-01", 328.0),
        ("2026-02-01", 329.0),
        ("2026-03-01", 330.0),
        ("2026-04-01", 332.407),
        ("2026-05-01", 333.979),
        ("2026-06-01", 332.568),
    ]
    value, note = pct_change_vs_month(dated, months_back=12)
    assert value == pytest.approx(3.4635, abs=1e-3)   # Stage 3 cpi.md 手動查證的那個數字
    assert "2025-06" in note

    # 位置索引在同一份資料上會拿到錯的那一格（缺月造成位移），這行記錄那個錯法
    assert dated[-13:][0][0] != "2025-06-01" or len(dated) < 13


def test_yoy_refuses_to_substitute_a_nearby_month():
    dated = [("2026-01-01", 100.0), ("2026-06-01", 110.0)]
    value, note = pct_change_vs_month(dated, months_back=12)
    assert value is None
    assert "缺月" in note


# ---------------------------------------------------------------------------
# Stage 5：卡片 .md 決定有哪些格子
# ---------------------------------------------------------------------------

def _stage2_stub():
    return {
        "source": "stub-source",
        "funding": "+0.0100%",
        "current_value": "527,596",
        "percentile": "85th",
        "trend": "Increasing（14-day window）",
        "observed_count": 0,
        "observed_notional": "0.00",
        "listen_seconds": 6,
        "mom_pct": "+0.10%",
        "yoy_pct": "+3.00%",
    }


def _knowledge_stub(**overrides):
    base = {
        "category": "statistical",
        "primary_horizon": "短期",
        "persistence": "中低",
        "reaction_window": "公布當下至 2-3 個交易日",
        "expected_duration": "數週至數月",
        "confirms": "open_interest",
        "conflicts": "long_short_ratio",
        "independent": "vol-compression",
    }
    base.update(overrides)
    return base


def test_card_fact_keys_come_from_the_card_file():
    card, _ = build_evidence_card(
        "liquidation",
        evidence_id="LIQUIDATION_BTC",
        stage2=_stage2_stub(),
        knowledge=_knowledge_stub(),
        evidence_weight=0.3,
    )
    assert set(card["fact"]) == {"observed_count", "observed_notional", "listen_seconds"}
    # 這張卡刻意沒有這兩格（不是放 null）——結構性沒有歷史序列
    assert "percentile" not in card["fact"]
    assert "trend" not in card["fact"]


def test_funding_rate_fact_alias():
    """Stage 2 把最新費率放在 `funding`，卡片那格叫 current_value。"""
    card, _ = build_evidence_card(
        "funding_rate",
        evidence_id="FUNDING_RATE_BTC",
        stage2=_stage2_stub(),
        knowledge=_knowledge_stub(),
        evidence_weight=0.11,
    )
    assert card["fact"]["current_value"] == "+0.0100%"


def test_event_factor_field_mapping_is_read_from_the_card_file():
    """cpi 走 Event Knowledge，沒有 primary_horizon／persistence 這兩個欄位名，
    卡片 .md 用 `→ reaction_window` 記下對應關係。這是讀檔讀出來的，不是程式裡的 if。"""
    knowledge = _knowledge_stub(category="event")
    knowledge.pop("primary_horizon")
    knowledge.pop("persistence")

    card, report = build_evidence_card(
        "cpi",
        evidence_id="CPI_BTC",
        stage2=_stage2_stub(),
        knowledge=knowledge,
        evidence_weight=0.8,
    )
    assert card["primary_horizon"] == knowledge["reaction_window"]
    assert card["persistence"] == knowledge["expected_duration"]
    assert report["mapped_fields"] == {
        "primary_horizon": "reaction_window",
        "persistence": "expected_duration",
    }


def test_liquidation_card_carries_the_downgrade_note_from_the_spec():
    """Stage 2 liquidation.yaml 的「降級處理」條款指定這段話要寫在 Evidence Card 上，
    Stage 5 liquidation.md 就是那個落實位置——內容來自規格檔，不是程式生成的字。"""
    card, _ = build_evidence_card(
        "liquidation",
        evidence_id="LIQUIDATION_BTC",
        stage2=_stage2_stub(),
        knowledge=_knowledge_stub(),
        evidence_weight=0.3,
    )
    assert card["traceability"]["source"] == "stub-source"
    assert "單次觀察窗，非統計訊號" in card["traceability"]["note"]


def test_unfillable_card_field_is_dropped_not_nulled():
    """2026-08-02 拍板：卡片 schema 有、但這次沒有來源填得出來的格子**整格不產生**。
    留 null 會被下游讀成「這次剛好沒算出來，下次可能有」——跟 liquidation 的 fact
    不放 percentile 是同一條原則。仍然要列進 report，不是靜靜消失。"""
    card, report = build_evidence_card(
        "active_address",
        evidence_id="ACTIVE_ADDRESS_BTC",
        stage2=_stage2_stub(),
        knowledge={"category": "statistical"},  # 缺 primary_horizon／persistence／關係欄位
        evidence_weight=0.004,
    )
    assert "primary_horizon" in report["unresolved_fields"]
    assert "primary_horizon" not in card


def test_runtime_value_fills_a_field_the_spec_files_cannot():
    """confidence 只有 panews 的卡片檔有這格，值是執行期才知道的（Stage 4 的樣本數判斷）。"""
    card, report = build_evidence_card(
        "panews_sentiment",
        evidence_id="PANEWS_SENTIMENT_BTC",
        stage2=_stage2_stub(),
        knowledge=_knowledge_stub(category="sentiment"),
        evidence_weight=0.051,
        runtime_values={"confidence": "low"},
    )
    assert card["confidence"] == "low"
    assert "confidence" not in report["unresolved_fields"]

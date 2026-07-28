from agent.collectors.onchain import HISTORY_TREND_DAYS, _history_trend


def _make_series(values: list[float]) -> list[tuple[str, float]]:
    return [(f"2026-01-{i+1:02d}", v) for i, v in enumerate(values)]


def test_history_trend_none_when_fewer_than_days_plus_one_points():
    series = _make_series([100.0] * HISTORY_TREND_DAYS)  # 剛好差一筆湊不滿
    assert _history_trend(series) is None


def test_history_trend_computes_latest_date_value_and_pct_change():
    series = _make_series([100.0] * HISTORY_TREND_DAYS + [110.0])
    result = _history_trend(series)
    assert result is not None
    latest_date, latest_val, pct = result
    assert latest_val == 110.0
    assert round(pct, 2) == 10.0  # (110-100)/100*100


def test_history_trend_zero_past_value_is_safe():
    series = _make_series([0.0] * HISTORY_TREND_DAYS + [5.0])
    _, latest_val, pct = _history_trend(series)
    assert latest_val == 5.0
    assert pct == 0.0  # 除以零時安全退回 0，不拋例外

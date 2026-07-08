from agent.collectors.price import (
    compute_technical_indicators,
    load_ohlcv_tail,
    summarize_ohlcv,
    summarize_technical_indicators,
)


def test_load_ohlcv_tail_returns_last_n_rows():
    rows = load_ohlcv_tail("BTC", data_dir="data", n=14)
    assert len(rows) == 14
    assert rows[-1]["date"] == "2026-05-31"


def test_summarize_ohlcv_reports_pct_change_and_range():
    rows = [
        {"date": "2026-01-01", "open": "100", "high": "110", "low": "95", "close": "100", "volume": "10"},
        {"date": "2026-01-02", "open": "100", "high": "120", "low": "90", "close": "110", "volume": "20"},
    ]
    summary = summarize_ohlcv(rows)
    assert "2026-01-01" in summary
    assert "2026-01-02" in summary
    assert "+10.00%" in summary
    assert "120.00" in summary  # 最高價
    assert "90.00" in summary  # 最低價


def _make_rows(closes: list[float], volumes: list[float]) -> list[dict]:
    return [
        {"date": f"2026-01-{i+1:02d}", "open": str(c), "high": str(c), "low": str(c), "close": str(c), "volume": str(v)}
        for i, (c, v) in enumerate(zip(closes, volumes))
    ]


def test_compute_technical_indicators_returns_empty_when_insufficient_data():
    rows = _make_rows([100.0] * 10, [10.0] * 10)
    assert compute_technical_indicators(rows) == {}


def test_compute_technical_indicators_all_gains_gives_rsi_100():
    closes = [100.0 + i for i in range(15)]  # 15 天單調上漲，全是漲，RSI 應為 100
    volumes = [10.0] * 8 + [20.0] * 7
    indicators = compute_technical_indicators(_make_rows(closes, volumes))
    assert indicators["rsi14"] == 100.0
    assert indicators["sma7"] == sum(closes[-7:]) / 7
    assert indicators["sma14"] == sum(closes[-14:]) / 14
    assert indicators["volume_trend_pct"] > 0  # 近 7 日量能高於前 7 日


def test_summarize_technical_indicators_labels_rsi_zone():
    indicators = {"sma7": 100.0, "sma14": 95.0, "rsi14": 100.0, "volatility_pct": 1.5, "volume_trend_pct": 10.0, "last_close": 105.0}
    summary = summarize_technical_indicators(indicators)
    assert "超買" in summary
    assert "RSI14=100.0" in summary


def test_summarize_technical_indicators_handles_empty():
    assert "不足" in summarize_technical_indicators({})

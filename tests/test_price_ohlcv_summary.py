from agent.collectors.price import load_ohlcv_tail, summarize_ohlcv


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

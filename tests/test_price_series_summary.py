"""R1-6／R1-7 序列摘要：技術指標改輸出近 30 天走勢摘要，而非只有最新一天的單點值。

方向判定是決定性計算（不經 LLM），所以可以逐案驗算。
"""

from __future__ import annotations

from agent.collectors.price import (
    SERIES_WINDOW,
    build_indicator_series,
    classify_direction,
    summarize_series,
    summarize_structural_indicators,
)


def _rows(closes: list[float], volumes: list[float] | None = None) -> list[dict]:
    vols = volumes if volumes is not None else [10.0] * len(closes)
    return [
        {
            "date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            "open": str(c), "high": str(c), "low": str(c), "close": str(c), "volume": str(v),
        }
        for i, (c, v) in enumerate(zip(closes, vols))
    ]


# --- 方向判定四態 + 橫盤 ---------------------------------------------------


def test_direction_monotonic_up():
    assert classify_direction([float(i) for i in range(30)]) == "單調上升"


def test_direction_monotonic_down():
    assert classify_direction([float(30 - i) for i in range(30)]) == "單調下降"


def test_direction_choppy_up():
    """整體走高但過程有回檔 → 震盪走高，不是單調上升。"""
    values = [float(i) for i in range(30)]
    values[10] = values[9] - 1  # 插一次反向
    assert classify_direction(values) == "震盪走高"


def test_direction_choppy_down():
    values = [float(30 - i) for i in range(30)]
    values[10] = values[9] + 1
    assert classify_direction(values) == "震盪走低"


def test_direction_flat_when_delta_within_own_stdev():
    """首尾差沒超過序列自身標準差就算橫盤——用序列自己的波動當基準，
    才不會對量能這種高波動指標與 RSI 這種低波動指標套同一個絕對門檻。"""
    values = [50.0, 60.0, 40.0, 55.0, 45.0, 51.0]
    assert classify_direction(values) == "橫盤"


def test_direction_insufficient_data():
    assert classify_direction([1.0]) == "資料不足"


# --- 序列建構與摘要 -------------------------------------------------------


def test_build_indicator_series_caps_at_window():
    rows = _rows([100.0 + (i % 9) for i in range(120)])
    series = build_indicator_series(rows)
    assert set(series) == {"RSI14", "MA20", "14日報酬波動率(%)", "7日均量"}
    for points in series.values():
        assert len(points) == SERIES_WINDOW


def test_build_indicator_series_degrades_when_history_short():
    """資料不足 30 天時給幾天算幾天；湊不出任何一天的指標則該項整項不出現。"""
    rows = _rows([100.0 + i for i in range(18)])
    series = build_indicator_series(rows)
    assert "MA20" not in series          # 20 日均線湊不滿一天
    assert len(series["RSI14"]) == 4     # 18 筆 → 第 15 筆起才有 RSI，共 4 天
    assert len(series["7日均量"]) == 12


def test_build_indicator_series_empty_when_no_rows():
    assert build_indicator_series([]) == {}


def test_summarize_series_reports_endpoints_extremes_and_percentile():
    rows = _rows([100.0 + i for i in range(60)])
    summary = summarize_series(build_indicator_series(rows))

    assert "RSI14：" in summary
    assert "MA20：" in summary
    assert "天前" in summary and "→ 現在" in summary
    assert "期間高" in summary and "／低" in summary
    assert "百分位" in summary
    # 單調上升的序列，現值就是期間最高 → 百分位 100
    ma_line = next(line for line in summary.splitlines() if line.startswith("MA20："))
    assert "單調上升" in ma_line
    assert "第 100 百分位" in ma_line


def test_summarize_series_does_not_dump_raw_values(caplog):
    """R1-7：只寫摘要，不把 30 天原始數列倒進 content_reference。"""
    rows = _rows([100.0 + i for i in range(60)])
    summary = summarize_series(build_indicator_series(rows))
    # 每個指標剛好一行；原始數列若被倒進來，行長會遠超過摘要格式
    lines = summary.splitlines()
    assert len(lines) == 4
    assert all(len(line) < 200 for line in lines)


def test_summarize_series_handles_empty():
    assert "不足" in summarize_series({})


# --- 結構指標的位置判定 ---------------------------------------------------


def test_structural_position_uses_current_close_not_csv_end():
    """R1-8 要求均線值以官方 CSV 計算，但位置判定必須用補齊後的現價。

    CSV 落後執行日近兩個月時，拿 CSV 末日收盤去比會判出與現實相反的「站上」。
    """
    indicators = {
        "ma60": 76044.92, "ma60_position": "站上",
        "ma120": 72613.46, "ma120_position": "站上",  # 依 CSV 末日收盤算出的舊判定
        "volatility_percentile_alltime": 5.1, "volatility_percentile_sample_size": 1813,
    }
    summary = summarize_structural_indicators(
        indicators, current_close=65399.99, current_date="2026-07-26"
    )
    assert "MA120=72613.46（現價跌破）" in summary
    assert "MA60=76044.92（現價跌破）" in summary
    assert "2026-07-26 收盤 65399.99 判定" in summary


def test_structural_position_falls_back_to_stored_position():
    """不傳現價時維持舊行為（報告／既有呼叫端不受影響）。"""
    indicators = {"ma60": 100.0, "ma60_position": "站上", "ma120": 90.0, "ma120_position": "站上"}
    summary = summarize_structural_indicators(indicators)
    assert "MA120=90.00（站上）" in summary
    assert "判定" not in summary

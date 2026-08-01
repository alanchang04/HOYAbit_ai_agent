"""R1-2／R1-3／R1-5 缺口補齊：Coinbase 優先，缺日以 Binance 公開日線補足。

全部用 mock，不打真實網路。驗的是併接規則與降級行為，不是 Binance 回傳的數字。
"""

from __future__ import annotations

import csv as csv_module
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.collectors.horizon import utc_today
from agent.collectors.price import (
    PriceCollector,
    build_gap_note,
    coinbase_candles_to_rows,
    gap_days_since,
    klines_to_rows,
    splice_ohlcv,
)
from agent.logging_utils import ExecutionLogger
from agent.schemas import LogStatus


@pytest.fixture
def logger(tmp_path):
    return ExecutionLogger(tmp_path / "test.jsonl")


class _Settings:
    """PriceCollector 只讀 settings.data_dir，測試不需要完整 Settings。"""

    def __init__(self, data_dir):
        self.data_dir = str(data_dir)


def _open_time_ms(day) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


def _kline(day, close="100", volume="10"):
    ts = _open_time_ms(day)
    return [ts, "100", "110", "90", close, volume, ts + 86_399_999]


def _coinbase_candle(day, close="100", volume="10"):
    ts = _open_time_ms(day) // 1000
    return [ts, "90", "110", "100", close, volume]


def _write_csv(path, start_day, days: int):
    """產一份收在 `start_day + days - 1` 的官方格式 CSV。"""
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv_module.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "volume"])
        w.writeheader()
        for i in range(days):
            d = start_day + timedelta(days=i)
            w.writerow({
                "date": d.isoformat(), "open": "100", "high": "110",
                "low": "90", "close": str(100 + i % 7), "volume": "10",
            })


def _resp(payload):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.json.return_value = payload
    return m


def _client(get):
    c = AsyncMock()
    c.get = get
    c.__aenter__ = AsyncMock(return_value=c)
    c.__aexit__ = AsyncMock(return_value=False)
    return c


# --- 純函式層 -------------------------------------------------------------


def test_klines_to_rows_drops_unclosed_candle():
    """當日 K 棒尚未收盤，半日的高低點與量能會污染指標，必須剔除。"""
    today = utc_today()
    payload = [_kline(today - timedelta(days=2)), _kline(today - timedelta(days=1)), _kline(today)]
    rows = klines_to_rows(payload, today=today)
    assert len(rows) == 2
    assert rows[-1]["date"] == (today - timedelta(days=1)).isoformat()


def test_klines_to_rows_skips_malformed_row_without_losing_the_rest():
    """畸形列只該跳過那一列——整段補齊作廢會讓分析退回 55 天前的舊資料。"""
    today = utc_today()
    good = _kline(today - timedelta(days=1))
    rows = klines_to_rows([[123], good, "not a list"], today=today)
    assert len(rows) == 1
    assert rows[0]["date"] == (today - timedelta(days=1)).isoformat()


def test_klines_to_rows_maps_fields_by_position():
    today = utc_today()
    day = today - timedelta(days=1)
    rows = klines_to_rows([[_open_time_ms(day), "1", "2", "0.5", "1.5", "999"]], today=today)
    assert rows == [{
        "date": day.isoformat(), "open": "1", "high": "2",
        "low": "0.5", "close": "1.5", "volume": "999",
    }]


def test_coinbase_candles_to_rows_maps_sorts_and_drops_open_day():
    today = utc_today()
    payload = [
        _coinbase_candle(today),
        _coinbase_candle(today - timedelta(days=1), close="105"),
        _coinbase_candle(today - timedelta(days=2), close="101"),
    ]
    rows = coinbase_candles_to_rows(payload, today=today)
    assert [row["date"] for row in rows] == [
        (today - timedelta(days=2)).isoformat(),
        (today - timedelta(days=1)).isoformat(),
    ]
    assert rows[-1]["close"] == "105"


@pytest.mark.asyncio
async def test_gap_fill_prefers_coinbase_when_complete(logger, tmp_path):
    csv_end = utc_today() - timedelta(days=4)
    _write_csv(tmp_path / "BTC_daily_ohlcv.csv", csv_end - timedelta(days=200), 201)
    gap = [_coinbase_candle(csv_end + timedelta(days=i)) for i in range(1, 4)]
    calls = []

    async def mock_get(url, **kwargs):
        calls.append(url)
        if "api.exchange.coinbase.com/products/BTC-USD/candles" in url:
            return _resp(gap)
        raise RuntimeError("其他來源本測試不驗")

    collector = PriceCollector(logger, settings=_Settings(tmp_path))
    with patch("agent.collectors.price.httpx.AsyncClient") as cls:
        cls.return_value = _client(mock_get)
        evidences = await collector.fetch("BTC")

    ohlcv = next(e for e in evidences if "共同基準資料集" in e.source)
    assert ohlcv.window_end == (utc_today() - timedelta(days=1)).isoformat()
    assert "Coinbase Exchange USD 公開日線補齊" in ohlcv.content_reference
    assert not any("api/v3/klines" in url for url in calls)


@pytest.mark.asyncio
async def test_formal_collector_uses_verified_cache_before_network(logger, tmp_path):
    """7/31-style refreshed cache is the first formal gap source, not merely an artifact."""
    csv_end = utc_today() - timedelta(days=4)
    official_dir = tmp_path / "official"
    raw_root = tmp_path / "raw_price"
    coin_dir = raw_root / "BTC"
    official_dir.mkdir()
    coin_dir.mkdir(parents=True)
    official_path = official_dir / "BTC_daily_ohlcv.csv"
    _write_csv(official_path, csv_end - timedelta(days=200), 201)
    official_rows = list(csv_module.DictReader(official_path.open(encoding="utf-8")))
    extension = [
        {
            "date": (csv_end + timedelta(days=i)).isoformat(), "open": "100",
            "high": "110", "low": "90", "close": str(100 + i), "volume": "10",
        }
        for i in range(1, 4)
    ]
    with (coin_dir / "BTC_daily_ohlcv.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv_module.DictWriter(handle, fieldnames=list(official_rows[0]))
        writer.writeheader()
        writer.writerows(official_rows + extension)
    (raw_root / "update_manifest.json").write_text(
        json.dumps({"coins": {"BTC": {"extended_end": extension[-1]["date"]}}}),
        encoding="utf-8",
    )

    calls = []
    async def mock_get(url, **kwargs):
        calls.append(url)
        raise RuntimeError("non-gap live sources are irrelevant to this test")

    collector = PriceCollector(logger, settings=_Settings(official_dir))
    with (
        patch("agent.collectors.price.RAW_PRICE_DIR", raw_root),
        patch("agent.collectors.price.httpx.AsyncClient") as cls,
    ):
        cls.return_value = _client(mock_get)
        evidences = await collector.fetch("BTC")

    ohlcv = next(e for e in evidences if "共同基準資料集" in e.source)
    assert ohlcv.window_end == (utc_today() - timedelta(days=1)).isoformat()
    assert "已驗證的 raw_data 價格快取" in ohlcv.content_reference
    assert not any("/candles" in url or "api/v3/klines" in url for url in calls)


def test_splice_prefers_csv_on_duplicate_date():
    """同日重複時保留 CSV：官方資料集是共同基準，補齊只補它沒涵蓋的日子。"""
    csv_rows = [{"date": "2026-05-31", "open": "1", "high": "1", "low": "1", "close": "CSV", "volume": "1"}]
    gap_rows = [
        {"date": "2026-05-31", "open": "9", "high": "9", "low": "9", "close": "BINANCE", "volume": "9"},
        {"date": "2026-06-01", "open": "9", "high": "9", "low": "9", "close": "NEW", "volume": "9"},
    ]
    spliced = splice_ohlcv(csv_rows, gap_rows)
    assert [r["date"] for r in spliced] == ["2026-05-31", "2026-06-01"]
    assert spliced[0]["close"] == "CSV"
    assert spliced[1]["close"] == "NEW"


def test_gap_days_since_handles_bad_date():
    """日期不可解時回 0＝視為無缺口，寧可不補也不要因為格式問題誤觸發。"""
    assert gap_days_since("not-a-date") == 0


def test_build_gap_note_success_and_failure_wording():
    ok = build_gap_note("2026-05-31", [{"date": "2026-06-01"}, {"date": "2026-06-02"}], 57)
    assert "2026-06-01 起 2 日採 Binance 公開日線補齊" in ok
    assert "官方基準資料集止於 2026-05-31" in ok

    failed = build_gap_note("2026-05-31", [], 57)
    assert failed.startswith("｜⚠ 未能補齊")
    assert "距執行日 57 天" in failed

    assert build_gap_note("2026-05-31", [], 1) == ""  # 無缺口不加註記


# --- collector 層 ---------------------------------------------------------


@pytest.mark.asyncio
async def test_gap_fill_success_advances_as_of_date(logger, tmp_path):
    csv_end = utc_today() - timedelta(days=10)
    _write_csv(tmp_path / "BTC_daily_ohlcv.csv", csv_end - timedelta(days=200), 201)
    gap = [_kline(csv_end + timedelta(days=i)) for i in range(1, 11)]  # 含當日未收盤那根

    calls = []

    async def mock_get(url, **kwargs):
        calls.append(url)
        if "api/v3/klines" in url:
            return _resp(gap)
        raise RuntimeError("其他來源本測試不驗")

    collector = PriceCollector(logger, settings=_Settings(tmp_path))
    with patch("agent.collectors.price.httpx.AsyncClient") as cls:
        cls.return_value = _client(mock_get)
        evidences = await collector.fetch("BTC")

    assert any("api/v3/klines" in u for u in calls)
    ohlcv = next(e for e in evidences if "共同基準資料集" in e.source)
    # 當日未收盤那根被剔除，序列推進到昨天
    assert ohlcv.window_end == (utc_today() - timedelta(days=1)).isoformat()
    assert "Binance Spot USDT 公開日線補齊" in ohlcv.content_reference
    assert f"官方基準資料集止於 {csv_end.isoformat()}" in ohlcv.content_reference


@pytest.mark.asyncio
async def test_gap_fill_failure_degrades_to_csv_only(logger, tmp_path):
    """R1-3：補齊失敗照樣產出證據，只是標註「未能補齊」並記一筆 SKIPPED。"""
    csv_end = utc_today() - timedelta(days=10)
    _write_csv(tmp_path / "BTC_daily_ohlcv.csv", csv_end - timedelta(days=200), 201)

    async def mock_get(url, **kwargs):
        raise RuntimeError("simulated network failure")

    collector = PriceCollector(logger, settings=_Settings(tmp_path))
    with patch("agent.collectors.price.httpx.AsyncClient") as cls:
        cls.return_value = _client(mock_get)
        evidences = await collector.fetch("BTC")

    ohlcv = next(e for e in evidences if "共同基準資料集" in e.source)
    assert ohlcv.window_end == csv_end.isoformat()  # 沒補到，基準日停在 CSV 末日
    assert "⚠ 未能補齊" in ohlcv.content_reference
    assert "距執行日 10 天" in ohlcv.content_reference

    entries = [json.loads(line) for line in logger.log_path.read_text(encoding="utf-8").splitlines()]
    gap_logs = [e for e in entries if e["action"].endswith("binance_gap_fill")]
    assert gap_logs and gap_logs[0]["status"] == LogStatus.SKIPPED.value


@pytest.mark.asyncio
async def test_gap_fill_empty_response_degrades(logger, tmp_path):
    csv_end = utc_today() - timedelta(days=10)
    _write_csv(tmp_path / "BTC_daily_ohlcv.csv", csv_end - timedelta(days=200), 201)

    async def mock_get(url, **kwargs):
        if "api/v3/klines" in url:
            return _resp([])
        raise RuntimeError("其他來源本測試不驗")

    collector = PriceCollector(logger, settings=_Settings(tmp_path))
    with patch("agent.collectors.price.httpx.AsyncClient") as cls:
        cls.return_value = _client(mock_get)
        evidences = await collector.fetch("BTC")

    ohlcv = next(e for e in evidences if "共同基準資料集" in e.source)
    assert "⚠ 未能補齊" in ohlcv.content_reference


@pytest.mark.asyncio
async def test_no_gap_makes_zero_api_calls(logger, tmp_path):
    """R1-5：主辦方當日提供更新資料集時自動不觸發補齊，且不需要改任何設定。"""
    csv_end = utc_today() - timedelta(days=1)
    _write_csv(tmp_path / "BTC_daily_ohlcv.csv", csv_end - timedelta(days=200), 201)

    calls = []

    async def mock_get(url, **kwargs):
        calls.append(url)
        raise RuntimeError("其他來源本測試不驗")

    collector = PriceCollector(logger, settings=_Settings(tmp_path))
    with patch("agent.collectors.price.httpx.AsyncClient") as cls:
        cls.return_value = _client(mock_get)
        evidences = await collector.fetch("BTC")

    assert not [u for u in calls if "api/v3/klines" in u or "products/BTC-USD/candles" in u]
    ohlcv = next(e for e in evidences if "共同基準資料集" in e.source)
    assert "補齊" not in ohlcv.content_reference

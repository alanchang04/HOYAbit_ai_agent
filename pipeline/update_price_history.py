"""Extend the immutable HOYA BIT price baseline with complete public daily bars.

The competition CSV files in ``data/`` remain untouched.  Extended OHLCV files
are rebuilt under ``raw_data/price/{COIN}/`` from the official baseline on every
run, then all derived price series are regenerated.

Coinbase Exchange USD candles are preferred.  Any missing complete UTC day is
filled from Binance Spot USDT candles.  ``--as-of`` is an exclusive UTC cutoff:
``--as-of 2026-08-01`` writes through 2026-07-31 and never includes an open
daily candle.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from itertools import permutations
from pathlib import Path
from typing import Any, Iterable

try:
    import httpx
except ModuleNotFoundError:  # pragma: no cover - 只在未安裝依賴的環境走到
    # 這支腳本會被 .kiro/hooks/price-data-refresh.json 以裸 `python` 啟動。
    # 若該 python 不是本專案的 venv（評審 clone 後最常見的情況），httpx 會缺，
    # 直接 import 會噴 traceback，看起來像專案壞了。改成延後回報：模組仍可 import
    # （tests/test_update_price_history.py 需要），真的要跑才在 main() 友善退出。
    httpx = None  # type: ignore[assignment]

COINS = ("BTC", "ETH", "SOL", "BNB", "XRP")
CSV_FIELDS = ("date", "open", "high", "low", "close", "volume")
COINBASE_API = "https://api.exchange.coinbase.com"
BINANCE_KLINES_API = "https://api.binance.com/api/v3/klines"
DAY_SECONDS = 86_400
DAY_MS = DAY_SECONDS * 1000
COINBASE_MAX_DAYS = 290
BINANCE_LIMIT = 1000
HTTP_TIMEOUT = 30.0
USER_AGENT = "HOYAbit-price-history-updater/1.0"

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL_DATA_DIR = ROOT / "data"
RAW_PRICE_DIR = ROOT / "raw_data" / "price"
MANIFEST_PATH = RAW_PRICE_DIR / "update_manifest.json"


def _utc_midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _iso_utc(day: date) -> str:
    return _utc_midnight(day).isoformat().replace("+00:00", "Z")


def _date_range(start: date, end: date) -> Iterable[date]:
    """Yield dates in the half-open interval [start, end)."""
    cursor = start
    while cursor < end:
        yield cursor
        cursor += timedelta(days=1)


def load_official_rows(coin: str, data_dir: Path = OFFICIAL_DATA_DIR) -> list[dict[str, str]]:
    path = data_dir / f"{coin}_daily_ohlcv.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not set(CSV_FIELDS).issubset(reader.fieldnames):
            raise ValueError(f"Unexpected OHLCV schema: {path}")
        rows = [{field: row[field] for field in CSV_FIELDS} for row in reader]
    if not rows:
        raise ValueError(f"Empty official OHLCV file: {path}")
    dates = [row["date"] for row in rows]
    if dates != sorted(set(dates)):
        raise ValueError(f"Official OHLCV dates are not unique and sorted: {path}")
    return rows


def coinbase_candles_to_rows(
    payload: Any, start: date, as_of: date
) -> list[dict[str, str]]:
    """Map Coinbase [time, low, high, open, close, volume] candles."""
    if not isinstance(payload, list):
        return []
    rows: dict[str, dict[str, str]] = {}
    for candle in payload:
        try:
            day = datetime.fromtimestamp(int(candle[0]), tz=timezone.utc).date()
            if not start <= day < as_of:
                continue
            rows[day.isoformat()] = {
                "date": day.isoformat(),
                "open": str(candle[3]),
                "high": str(candle[2]),
                "low": str(candle[1]),
                "close": str(candle[4]),
                "volume": str(candle[5]),
            }
        except (IndexError, TypeError, ValueError, OSError):
            continue
    return [rows[key] for key in sorted(rows)]


def binance_klines_to_rows(
    payload: Any, start: date, as_of: date
) -> list[dict[str, str]]:
    """Map Binance [openTime, open, high, low, close, volume, ...] klines."""
    if not isinstance(payload, list):
        return []
    rows: dict[str, dict[str, str]] = {}
    for kline in payload:
        try:
            day = datetime.fromtimestamp(int(kline[0]) / 1000, tz=timezone.utc).date()
            if not start <= day < as_of:
                continue
            rows[day.isoformat()] = {
                "date": day.isoformat(),
                "open": str(kline[1]),
                "high": str(kline[2]),
                "low": str(kline[3]),
                "close": str(kline[4]),
                "volume": str(kline[5]),
            }
        except (IndexError, TypeError, ValueError, OSError):
            continue
    return [rows[key] for key in sorted(rows)]


def _get_json(
    client: httpx.Client, url: str, *, params: dict[str, Any], attempts: int = 3
) -> Any:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


def fetch_coinbase_rows(
    client: httpx.Client, coin: str, start: date, as_of: date
) -> list[dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    cursor = start
    while cursor < as_of:
        chunk_end = min(cursor + timedelta(days=COINBASE_MAX_DAYS), as_of)
        payload = _get_json(
            client,
            f"{COINBASE_API}/products/{coin}-USD/candles",
            params={
                "granularity": DAY_SECONDS,
                "start": _iso_utc(cursor),
                "end": _iso_utc(chunk_end),
            },
        )
        for row in coinbase_candles_to_rows(payload, cursor, chunk_end):
            rows[row["date"]] = row
        cursor = chunk_end
    return [rows[key] for key in sorted(rows)]


def fetch_binance_rows(
    client: httpx.Client, coin: str, start: date, as_of: date
) -> list[dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    cursor_ms = int(_utc_midnight(start).timestamp() * 1000)
    end_ms = int(_utc_midnight(as_of).timestamp() * 1000) - 1
    while cursor_ms <= end_ms:
        payload = _get_json(
            client,
            BINANCE_KLINES_API,
            params={
                "symbol": f"{coin}USDT",
                "interval": "1d",
                "startTime": cursor_ms,
                "endTime": end_ms,
                "limit": BINANCE_LIMIT,
            },
        )
        batch = binance_klines_to_rows(payload, start, as_of)
        if not batch:
            break
        for row in batch:
            rows[row["date"]] = row
        next_ms = int(_utc_midnight(date.fromisoformat(batch[-1]["date"])).timestamp() * 1000) + DAY_MS
        if next_ms <= cursor_ms:
            break
        cursor_ms = next_ms
        if len(payload) < BINANCE_LIMIT:
            break
    return [rows[key] for key in sorted(rows)]


def merge_extension_rows(
    coinbase_rows: list[dict[str, str]],
    binance_rows: list[dict[str, str]],
    start: date,
    as_of: date,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Prefer Coinbase by date; use Binance only for missing complete days."""
    coinbase_by_date = {row["date"]: row for row in coinbase_rows}
    binance_by_date = {row["date"]: row for row in binance_rows}
    merged: list[dict[str, str]] = []
    counts = {"coinbase_exchange_usd": 0, "binance_spot_usdt": 0}
    missing: list[str] = []
    for day in _date_range(start, as_of):
        key = day.isoformat()
        if key in coinbase_by_date:
            merged.append(coinbase_by_date[key])
            counts["coinbase_exchange_usd"] += 1
        elif key in binance_by_date:
            merged.append(binance_by_date[key])
            counts["binance_spot_usdt"] += 1
        else:
            missing.append(key)
    if missing:
        preview = ", ".join(missing[:5])
        raise RuntimeError(f"Missing {len(missing)} complete daily candles: {preview}")
    return merged, counts


def _atomic_write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", delete=False, dir=path.parent, suffix=".tmp"
        ) as handle:
            temporary = handle.name
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", delete=False, dir=path.parent, suffix=".tmp"
        ) as handle:
            temporary = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def rebuild_derived_series() -> dict[str, int]:
    """Rebuild the 35 CSVs derived from extended OHLCV data."""
    try:
        from pipeline import compute_historical_volatility_percentile as historical_vol
        from pipeline import compute_ma
        from pipeline import compute_relative_strength as relative_strength
        from pipeline import compute_volatility_compression as vol_compression
    except ModuleNotFoundError:  # Direct execution: python pipeline/update_price_history.py
        import compute_historical_volatility_percentile as historical_vol
        import compute_ma
        import compute_relative_strength as relative_strength
        import compute_volatility_compression as vol_compression

    for coin in COINS:
        _, rows = compute_ma.load_closes(coin)
        compute_ma.write_series_output(coin, compute_ma.compute_ma_series(rows))

        vol_rows = vol_compression.load_closes(coin)
        vol_compression.write_series_output(coin, vol_compression.compute_volatility_series(vol_rows))

        historical_rows = historical_vol.load_closes(coin)
        historical_vol.write_series_output(coin, historical_vol.compute_series(historical_rows))

    closes = {coin: relative_strength.load_closes(coin) for coin in COINS}
    for coin_a, coin_b in permutations(COINS, 2):
        series = relative_strength.compute_relative_strength_series(closes[coin_a], closes[coin_b])
        relative_strength.write_series_output(coin_a, coin_b, series)

    return {
        "ma_series": len(COINS),
        "volatility_compression_series": len(COINS),
        "volatility_percentile_series": len(COINS),
        "relative_strength_series": len(COINS) * (len(COINS) - 1),
    }


def update_price_history(
    as_of: date,
    *,
    official_data_dir: Path = OFFICIAL_DATA_DIR,
    raw_price_dir: Path = RAW_PRICE_DIR,
    rebuild_derived: bool = True,
) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    if as_of > today:
        raise ValueError(f"--as-of cannot be after current UTC date {today}")

    manifest: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_exclusive_utc": as_of.isoformat(),
        "last_complete_date": (as_of - timedelta(days=1)).isoformat(),
        "baseline_policy": "data/*.csv is the immutable HOYA BIT official baseline",
        "source_priority": ["Coinbase Exchange USD", "Binance Spot USDT (missing-day fallback)"],
        "coins": {},
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    with httpx.Client(timeout=HTTP_TIMEOUT, headers=headers, follow_redirects=True) as client:
        for coin in COINS:
            official_rows = load_official_rows(coin, official_data_dir)
            official_end = date.fromisoformat(official_rows[-1]["date"])
            extension_start = official_end + timedelta(days=1)
            if as_of < extension_start:
                raise ValueError(
                    f"{coin}: --as-of {as_of} predates extension start {extension_start}"
                )

            coinbase_error: str | None = None
            try:
                coinbase_rows = fetch_coinbase_rows(client, coin, extension_start, as_of)
            except (httpx.HTTPError, ValueError) as exc:
                coinbase_rows = []
                coinbase_error = f"{type(exc).__name__}: {exc}"

            expected = {day.isoformat() for day in _date_range(extension_start, as_of)}
            coinbase_dates = {row["date"] for row in coinbase_rows}
            missing_dates = expected - coinbase_dates
            binance_rows: list[dict[str, str]] = []
            if missing_dates:
                binance_rows = fetch_binance_rows(client, coin, min(map(date.fromisoformat, missing_dates)), as_of)

            extension_rows, source_counts = merge_extension_rows(
                coinbase_rows, binance_rows, extension_start, as_of
            )
            output_path = raw_price_dir / coin / f"{coin}_daily_ohlcv.csv"
            _atomic_write_csv(output_path, official_rows + extension_rows)
            manifest["coins"][coin] = {
                "product_preferred": f"{coin}-USD",
                "fallback_symbol": f"{coin}USDT",
                "official_start": official_rows[0]["date"],
                "official_end": official_rows[-1]["date"],
                "extended_end": (official_rows + extension_rows)[-1]["date"],
                "official_rows": len(official_rows),
                "extension_rows": len(extension_rows),
                "source_rows": source_counts,
                "coinbase_error": coinbase_error,
                "output": str(output_path.relative_to(ROOT)).replace("\\", "/"),
            }
            print(
                f"{coin}: {official_rows[-1]['date']} -> {manifest['coins'][coin]['extended_end']} "
                f"(Coinbase {source_counts['coinbase_exchange_usd']}, "
                f"Binance {source_counts['binance_spot_usdt']})"
            )

    if rebuild_derived:
        manifest["derived_files"] = rebuild_derived_series()
    else:
        manifest["derived_files"] = {"skipped": True}

    manifest_path = raw_price_dir / MANIFEST_PATH.name
    _atomic_write_json(manifest_path, manifest)
    print(f"Manifest: {manifest_path}")
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=datetime.now(timezone.utc).date(),
        help="Exclusive UTC cutoff (default: current UTC date)",
    )
    parser.add_argument(
        "--skip-derived",
        action="store_true",
        help="Only update extended OHLCV caches; do not rebuild derived CSVs",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if httpx is None:
        # 缺依賴不是錯誤情境，只是這台 python 沒裝：安靜跳過並說明怎麼補。
        # 回傳 0 讓 SessionStart hook 不被判為失敗——價格缺口 agent 執行時
        # 會由 price.py 自行補齊，這支腳本只是預先暖快取。
        print(
            "[skip] 未安裝 httpx，跳過價格歷史更新。\n"
            "       需要時請用專案 venv 執行："
            "python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 0
    try:
        update_price_history(args.as_of, rebuild_derived=not args.skip_derived)
    except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
        print(f"Price history update failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

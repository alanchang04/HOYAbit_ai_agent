"""價格資料 collector：主辦方 CSV（穩定基準）＋ CoinGecko 即時報價（備援 CryptoCompare）。

另外用純 Python（不靠外部 API、不靠 LLM）從官方 OHLCV CSV 計算技術指標
（SMA／RSI／波動率／量能趨勢），這類證據是決定性運算，不會因網路或
API 額度而失敗，是最穩定的一類 price evidence。
"""

from __future__ import annotations

import csv
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from agent.collectors.base import BaseCollector
from agent.collectors.coin_map import get_coin_info
from agent.collectors.horizon import utc_today
from agent.schemas import EvidenceDraft, HorizonClass, LogStatus, now_iso

HTTP_TIMEOUT = 20.0
# MA120 需要至少 120 天收盤價才算得出來，抓 121 列留一天緩衝（見
# pipeline/流程紀錄.md 的落差記錄）。2026-07-21 由 Ken 直接指示先改，
# 尚未跟 alanchang 對過這個窗口常數，之後要補講一聲。
INDICATOR_WINDOW = 121
MA_WINDOWS = (20, 60, 120)
# 併自 pipeline/compute_historical_volatility_percentile.py：波動率百分位
# 窗口跟 volatility_pct 同一個 14 天，累積不到 90 筆前不給百分位（樣本太少
# 會失真，跟其他 prototype 的門檻一致）。
VOL_PERCENTILE_WINDOW = 14
VOL_PERCENTILE_MIN_SAMPLE = 90
# 併自 pipeline/compute_volatility_compression.py：跟上面的全歷史百分位
# 是不同題目——這裡回答「近期是否相對『近 90 天』悶」，用固定滾動視窗，
# 不是擴張視窗；20 天日報酬標準差窗口跟 90 天排百分位窗口都沿用 prototype
# 原始常數，不跟 VOL_PERCENTILE_WINDOW（14天/全歷史）共用。
VOL_COMPRESSION_WINDOW = 20
VOL_COMPRESSION_PCTL_WINDOW = 90

# 序列摘要的呈現窗口：逐日重算指標後只描述最後 30 天的走勢（R1-6）。
SERIES_WINDOW = 30

# --- 缺口補齊（R1-2，ADR-1 雙軌資料）---
# 官方 CSV 是長歷史基準，Binance 只補「CSV 末日 → 執行日」這一段供當前訊號帶指標使用。
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_KLINES_LIMIT = 1000
# CSV 末日距執行日 <= 1 天視為無缺口，直接跳過補齊（R1-5：主辦方若當日提供新資料集，
# 這裡自動不觸發，不需要改任何程式或設定）。
GAP_FILL_TRIGGER_DAYS = 1


def load_ohlcv_all(coin: str, data_dir: str) -> list[dict]:
    path = Path(data_dir) / f"{coin}_daily_ohlcv.csv"
    if not path.exists():
        raise FileNotFoundError(f"找不到 OHLCV 資料檔: {path}")
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_ohlcv_tail(coin: str, data_dir: str, n: int = 14) -> list[dict]:
    return load_ohlcv_all(coin, data_dir)[-n:]


def klines_to_rows(payload: list, today: date | None = None) -> list[dict]:
    """Binance klines 回應 → 與官方 CSV 同 schema 的列。

    欄位映射 `[0]=openTime, [1]=open, [2]=high, [3]=low, [4]=close, [5]=volume`。
    **當日（UTC）那根 K 棒尚未收盤必須剔除**——半日的高低點與成交量會直接污染
    波動率與量能指標（design.md §3.3）。
    """
    cutoff = today or utc_today()
    rows: list[dict] = []
    for k in payload:
        # 整筆映射都放進 try：欄位數不足的畸形列只該跳過那一列，不該讓整段補齊作廢
        try:
            day = datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc).date()
            if day >= cutoff:
                continue
            row = {
                "date": day.isoformat(),
                "open": str(k[1]),
                "high": str(k[2]),
                "low": str(k[3]),
                "close": str(k[4]),
                "volume": str(k[5]),
            }
        except (TypeError, ValueError, IndexError, KeyError, OSError):
            continue
        rows.append(row)
    return rows


def splice_ohlcv(csv_rows: list[dict], gap_rows: list[dict]) -> list[dict]:
    """併接官方 CSV 與補齊區段，依日期升序輸出。

    同一天兩邊都有時**保留 CSV 那筆**——官方資料集是「共同基準」，補齊只負責它
    沒涵蓋到的日子，不覆寫它已經給的數字。
    """
    merged = {r["date"]: r for r in gap_rows}
    merged.update({r["date"]: r for r in csv_rows})
    return [merged[d] for d in sorted(merged)]


def gap_days_since(csv_end: str, today: date | None = None) -> int:
    """官方 CSV 末日距執行日幾天；日期不可解時回 0（視為無缺口，不觸發補齊）。"""
    try:
        return ((today or utc_today()) - date.fromisoformat(csv_end[:10])).days
    except ValueError:
        return 0


def build_gap_note(csv_end: str, gap_rows: list[dict], gap_days: int) -> str:
    """接縫揭露文字（R1-3／R1-4）。無缺口時回空字串。"""
    if gap_rows:
        return (
            f"｜其中 {gap_rows[0]['date']} 起 {len(gap_rows)} 日採 Binance 公開日線補齊，"
            f"官方基準資料集止於 {csv_end}"
        )
    if gap_days > GAP_FILL_TRIGGER_DAYS:
        return f"｜⚠ 未能補齊，資料止於 {csv_end}，距執行日 {gap_days} 天"
    return ""


def summarize_ohlcv(rows: list[dict]) -> str:
    if not rows:
        return "無可用歷史資料"
    start, end = rows[0], rows[-1]
    start_close = float(start["close"])
    end_close = float(end["close"])
    pct_change = (end_close - start_close) / start_close * 100 if start_close else 0.0
    high = max(float(r["high"]) for r in rows)
    low = min(float(r["low"]) for r in rows)
    total_volume = sum(float(r["volume"]) for r in rows)
    return (
        f"期間 {start['date']} ~ {end['date']}（共 {len(rows)} 日）："
        f"收盤價 {start_close:.2f} → {end_close:.2f} USDT（{pct_change:+.2f}%），"
        f"期間最高 {high:.2f}／最低 {low:.2f}，總成交量約 {total_volume:.2f}"
    )


def compute_historical_volatility_percentile(
    full_closes: list[float],
    window: int = VOL_PERCENTILE_WINDOW,
    min_sample: int = VOL_PERCENTILE_MIN_SAMPLE,
) -> dict | None:
    """依全歷史收盤價序列，算最新一天 window 天波動率相對「過去至今全部歷史」
    的百分位（擴張視窗，不是固定滾動視窗）——對照
    pipeline/compute_historical_volatility_percentile.py 的 compute_series()，
    這裡只需要序列最後一天的結果餵進證據文字，不落地整份序列。

    累積樣本數不到 min_sample 時回傳 None，呼叫端應顯示「資料不足」而不是
    硬湊一個不可靠的百分位。
    """
    if len(full_closes) < window + 1:
        return None

    returns = [0.0]
    for i in range(1, len(full_closes)):
        prev = full_closes[i - 1]
        returns.append((full_closes[i] - prev) / prev * 100 if prev else 0.0)

    vol_history: list[float] = []
    for i in range(len(full_closes)):
        if i + 1 >= window:
            vol_history.append(statistics.pstdev(returns[i - window + 1 : i + 1]))

    if len(vol_history) < min_sample:
        return None

    latest_vol = vol_history[-1]
    percentile = sum(1 for v in vol_history if v <= latest_vol) / len(vol_history) * 100
    return {"vol_pct": latest_vol, "percentile_alltime": percentile, "sample_size": len(vol_history)}


def compute_volatility_compression(
    full_closes: list[float],
    window: int = VOL_COMPRESSION_WINDOW,
    pctl_window: int = VOL_COMPRESSION_PCTL_WINDOW,
) -> dict | None:
    """依全歷史收盤價序列，算近 window 天日報酬標準差，相對「近 pctl_window
    天」這段固定滾動視窗的百分位——回答「近期是否相對近期悶」，跟
    `compute_historical_volatility_percentile()` 的擴張視窗（回答「相對全歷史
    的位置」）是不同題目，兩者不能互相取代。對照
    pipeline/compute_volatility_compression.py 的 compute_volatility_series()。

    累積樣本數不到 pctl_window 時回傳 None，呼叫端應顯示「資料不足」。
    """
    if len(full_closes) < window + 1:
        return None

    returns = [0.0]
    for i in range(1, len(full_closes)):
        prev = full_closes[i - 1]
        returns.append((full_closes[i] - prev) / prev * 100 if prev else 0.0)

    vol_history: list[float] = []
    for i in range(len(full_closes)):
        if i + 1 >= window:
            vol_history.append(statistics.pstdev(returns[i - window + 1 : i + 1]))

    if len(vol_history) < pctl_window:
        return None

    latest_vol = vol_history[-1]
    recent_window = vol_history[-pctl_window:]
    percentile = sum(1 for v in recent_window if v <= latest_vol) / len(recent_window) * 100
    return {"vol_20d_pct": latest_vol, "percentile_90d": percentile}


def _rsi14(window15: list[float]) -> float:
    """RSI14；輸入為 15 筆收盤價（14 個差分）。全漲無跌時定義為 100。"""
    diffs = [window15[i + 1] - window15[i] for i in range(len(window15) - 1)]
    if not diffs:
        return 100.0
    n = len(diffs)
    avg_gain = sum(d for d in diffs if d > 0) / n
    avg_loss = sum(-d for d in diffs if d < 0) / n
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def _volatility_pct(window15: list[float]) -> float:
    """日報酬率的母體標準差（%）；輸入為 15 筆收盤價。"""
    returns = [
        (window15[i + 1] - window15[i]) / window15[i]
        for i in range(len(window15) - 1)
        if window15[i]
    ]
    return statistics.pstdev(returns) * 100 if len(returns) >= 2 else 0.0


def compute_technical_indicators(rows: list[dict], full_closes: list[float] | None = None) -> dict:
    """依最近 N 日 OHLCV 計算 SMA7/SMA14、RSI14、日報酬波動率、近 7 日量能趨勢。

    需要至少 15 筆資料才能算出一個 RSI14 數值；資料不足時回傳空 dict，
    呼叫端應視為「本次無法計算技術指標」而略過，不應拋例外。

    `full_closes`（選填）是完整歷史收盤價序列（不是 `rows` 這個受
    INDICATOR_WINDOW 截斷的尾段），用來算 volatility_pct 相對全歷史的百分位；
    不傳時（例如既有測試手動組 rows）就略過百分位欄位，不影響原有指標。
    """
    closes = [float(r["close"]) for r in rows]
    volumes = [float(r["volume"]) for r in rows]
    if len(closes) < 15:
        return {}

    sma7 = sum(closes[-7:]) / 7
    sma14 = sum(closes[-14:]) / 14

    window = closes[-15:]
    rsi14 = _rsi14(window)
    volatility_pct = _volatility_pct(window)

    if len(volumes) >= 14:
        recent_avg_vol = sum(volumes[-7:]) / 7
        prior_avg_vol = sum(volumes[-14:-7]) / 7
        volume_trend_pct = (
            (recent_avg_vol - prior_avg_vol) / prior_avg_vol * 100 if prior_avg_vol else 0.0
        )
    else:
        volume_trend_pct = 0.0

    result = {
        "sma7": sma7,
        "sma14": sma14,
        "rsi14": rsi14,
        "volatility_pct": volatility_pct,
        "volume_trend_pct": volume_trend_pct,
        "last_close": closes[-1],
    }

    # MA20/60/120 位置判讀：資料不足對應天數的窗口留 None（不是 0，避免誤讀）。
    for window_size in MA_WINDOWS:
        if len(closes) >= window_size:
            ma = sum(closes[-window_size:]) / window_size
            result[f"ma{window_size}"] = ma
            result[f"ma{window_size}_position"] = "站上" if closes[-1] >= ma else "跌破"
        else:
            result[f"ma{window_size}"] = None
            result[f"ma{window_size}_position"] = "資料不足"

    if full_closes is not None:
        hist = compute_historical_volatility_percentile(full_closes)
        result["volatility_percentile_alltime"] = hist["percentile_alltime"] if hist else None
        result["volatility_percentile_sample_size"] = hist["sample_size"] if hist else None

        compression = compute_volatility_compression(full_closes)
        result["vol_compression_20d_pct"] = compression["vol_20d_pct"] if compression else None
        result["vol_compression_percentile_90d"] = compression["percentile_90d"] if compression else None

    return result


def build_indicator_series(rows: list[dict], window: int = SERIES_WINDOW) -> dict[str, list[tuple[str, float]]]:
    """逐日重算指標，回傳最後 `window` 天的 `{指標名: [(日期, 值), ...]}`（R1-6）。

    資料不足以湊滿 window 天時就給幾天算幾天，湊不出任何一天的指標則該指標整項
    不出現在結果裡——不硬湊、也不拋錯（R6-1）。
    """
    dates = [r["date"] for r in rows]
    closes = [float(r["close"]) for r in rows]
    volumes = [float(r["volume"]) for r in rows]
    series: dict[str, list[tuple[str, float]]] = {}

    def collect(name: str, lookback: int, value_at) -> None:
        points = [
            (dates[i], value_at(i)) for i in range(len(rows)) if i + 1 >= lookback
        ]
        if points:
            series[name] = points[-window:]

    collect("RSI14", 15, lambda i: _rsi14(closes[i - 14 : i + 1]))
    collect("MA20", 20, lambda i: sum(closes[i - 19 : i + 1]) / 20)
    collect("14日報酬波動率(%)", 15, lambda i: _volatility_pct(closes[i - 14 : i + 1]))
    collect("7日均量", 7, lambda i: sum(volumes[i - 6 : i + 1]) / 7)
    return series


def classify_direction(values: list[float]) -> str:
    """序列方向的決定性判定（design.md §3.4），不經 LLM。

    首尾差沒超過序列自身的標準差就算橫盤——用序列自己的波動當基準，避免對高波動
    指標（量能）與低波動指標（RSI）套同一個絕對門檻。
    """
    if len(values) < 2:
        return "資料不足"
    delta = values[-1] - values[0]
    if abs(delta) <= statistics.pstdev(values):
        return "橫盤"
    rising = delta > 0
    diffs = [b - a for a, b in zip(values, values[1:])]
    has_reversal = any((d < 0) if rising else (d > 0) for d in diffs)
    if rising:
        return "震盪走高" if has_reversal else "單調上升"
    return "震盪走低" if has_reversal else "單調下降"


def _summarize_one_series(name: str, points: list[tuple[str, float]]) -> str:
    values = [v for _, v in points]
    first, last = values[0], values[-1]
    high = max(points, key=lambda p: p[1])
    low = min(points, key=lambda p: p[1])
    percentile = sum(1 for v in values if v <= last) / len(values) * 100
    n = len(values)
    return (
        f"{name}：{n}天前 {first:,.2f} → 現在 {last:,.2f}（{last - first:+,.2f}），"
        f"{classify_direction(values)}；期間高 {high[1]:,.2f}（{high[0]}）／"
        f"低 {low[1]:,.2f}（{low[0]}）；現值位於近 {n} 天分佈第 {percentile:.0f} 百分位"
    )


def summarize_series(series: dict[str, list[tuple[str, float]]]) -> str:
    """把逐日序列壓成每個指標一行的摘要。

    刻意**不輸出原始數列**（R1-7）：30 天 × 4 指標的原始數字約 800 字，摘要約 240 字，
    而且原始數列還得讓 LLM 自己看出方向，等於把決定性計算外包給不決定性的東西。
    """
    if not series:
        return "資料筆數不足，無法產生指標序列摘要"
    return "\n".join(_summarize_one_series(name, points) for name, points in series.items())


def _ma_part(indicators: dict, window_size: int) -> str:
    val = indicators.get(f"ma{window_size}")
    pos = indicators.get(f"ma{window_size}_position", "資料不足")
    return f"MA{window_size}={val:.2f}（{pos}）" if val is not None else f"MA{window_size}=資料不足"


def summarize_current_indicators(indicators: dict) -> str:
    """當前訊號帶（horizon=medium）的技術指標：回看不超過 20 天的動能與量能。

    刻意**不含** MA60/MA120 與全歷史波動率百分位——那些是月／年尺度的結構位置，
    混在同一筆證據裡就只能標一個 horizon，正是假矛盾（design.md D2）的成因。
    """
    if not indicators:
        return "資料筆數不足，無法計算技術指標"
    trend = "站上" if indicators["last_close"] >= indicators["sma7"] else "跌破"
    rsi_zone = (
        "超買" if indicators["rsi14"] >= 70 else "超賣" if indicators["rsi14"] <= 30 else "中性"
    )
    return (
        f"SMA7={indicators['sma7']:.2f}, SMA14={indicators['sma14']:.2f}"
        f"（現價{trend} SMA7）, RSI14={indicators['rsi14']:.1f}（{rsi_zone}區間）, "
        f"近14日日報酬波動率={indicators['volatility_pct']:.2f}%, "
        f"近7日量能較前7日變化={indicators['volume_trend_pct']:+.2f}%, "
        + _ma_part(indicators, 20)
    )


def summarize_structural_indicators(
    indicators: dict, current_close: float | None = None, current_date: str | None = None
) -> str:
    """結構脈絡帶（horizon=structural）：長均線位置與波動率的全歷史相對位置。

    這段描述的是「現在處在大週期何處」，不是短窗方向訊號，不應與當前訊號當成矛盾。

    均線**值**依 R1-8 一律由官方 CSV 全歷史計算，但站上／跌破的**位置判定**必須用
    `current_close`（補齊後的最新收盤）——拿 CSV 末日的收盤去比，在 CSV 落後執行日
    快兩個月時會判出與現實相反的結論。不傳 current_close 時維持舊行為。
    """
    if not indicators:
        return "資料筆數不足，無法計算長期結構指標"
    percentile = indicators.get("volatility_percentile_alltime")
    if percentile is not None:
        lean = "偏悶（相對全歷史低波動）" if percentile < 50 else "偏熱（相對全歷史高波動）"
        vol_percentile_part = (
            f"（全歷史{indicators['volatility_percentile_sample_size']}筆樣本百分位="
            f"{percentile:.1f}，{lean}）"
        )
    else:
        vol_percentile_part = "（全歷史百分位：資料不足）"

    # MA60 嚴格說是 long 而非 structural，但與 MA120／全歷史百分位同屬「大週期位置」的
    # 判讀語意，併在同一筆結構證據裡；兩者都不參與矛盾判定，分開只是多一筆噪音。
    long_windows = [w for w in MA_WINDOWS if w != 20]
    if current_close is None:
        ma_parts = [_ma_part(indicators, w) for w in long_windows]
        position_note = ""
    else:
        ma_parts = []
        for w in long_windows:
            val = indicators.get(f"ma{w}")
            if val is None:
                ma_parts.append(f"MA{w}=資料不足")
                continue
            ma_parts.append(f"MA{w}={val:.2f}（現價{'站上' if current_close >= val else '跌破'}）")
        position_note = f"（位置以 {current_date} 收盤 {current_close:.2f} 判定）"

    # 併自 Ken 的波動壓縮（`compute_volatility_compression`，20 天標準差 vs 近 90 天
    # 滾動分佈）。90 天滾動窗屬結構脈絡帶（design.md §3.2.1 決策②），所以放這支而不是
    # current——它跟上面的全歷史百分位是不同題目：前者問「相對近 90 天是否悶」，
    # 後者問「相對全歷史的位置」，兩者並列不重複計算。
    compression_pctl = indicators.get("vol_compression_percentile_90d")
    if compression_pctl is not None:
        c_lean = "偏悶（盤整彈藥）" if compression_pctl < 50 else "偏熱（相對近90天高波動期）"
        compression_part = (
            f"，近20日日報酬波動率={indicators['vol_compression_20d_pct']:.2f}%"
            f"，90天滾動百分位={compression_pctl:.1f}（{c_lean}）"
        )
    else:
        compression_part = "，近90天波動壓縮度百分位：資料不足"

    return (
        "，".join(ma_parts)
        + position_note
        + f"，近14日日報酬波動率相對全歷史位置{vol_percentile_part}"
        + compression_part
    )


def has_structural_indicators(indicators: dict) -> bool:
    """是否算得出任何長期結構指標；全部資料不足時就不必產生那筆結構證據。"""
    if not indicators:
        return False
    return any(indicators.get(f"ma{w}") is not None for w in MA_WINDOWS if w != 20) or (
        indicators.get("volatility_percentile_alltime") is not None
    )


def summarize_technical_indicators(indicators: dict) -> str:
    """完整版摘要＝當前訊號段＋結構段。

    collector 已改為分兩筆證據輸出（各自帶正確 horizon），這個合併版保留給
    報告／測試等需要「一句話看完全部技術面」的呼叫端。
    """
    if not indicators:
        return "資料筆數不足，無法計算技術指標"
    return summarize_current_indicators(indicators) + "，" + summarize_structural_indicators(indicators)


def compute_perp_basis(mark_price: float, index_price: float, funding_rate: float) -> dict:
    """依 Binance premiumIndex 回傳值算永續合約基差（mark 相對 index 的溢價比例）。"""
    basis_pct = (mark_price - index_price) / index_price * 100 if index_price else 0.0
    return {
        "mark_price": mark_price,
        "index_price": index_price,
        "basis_pct": basis_pct,
        "funding_rate_pct": funding_rate * 100,
    }


def summarize_perp_basis(basis: dict) -> str:
    direction = (
        "正基差 contango（多頭情緒佐證）"
        if basis["basis_pct"] >= 0
        else "負基差 backwardation（空頭情緒佐證）"
    )
    return (
        f"markPrice {basis['mark_price']:.4f} vs indexPrice {basis['index_price']:.4f}，"
        f"基差 {basis['basis_pct']:+.4f}%（{direction}），"
        f"最新資金費率 {basis['funding_rate_pct']:+.5f}%"
    )


class PriceCollector(BaseCollector):
    name = "price_collector"
    source_type = "price"

    async def _fetch_gap_klines(self, client: httpx.AsyncClient, coin: str, since: date) -> list[dict]:
        """補齊 `since` 起至昨日的日線（R1-2）。任何失敗都回空 list 並記 SKIPPED，
        不拋錯——補齊失敗只該讓分析退回純 CSV，不該讓整條 pipeline 倒（R6-1）。"""
        info = get_coin_info(coin)
        symbol = f"{info.ticker}USDT"
        start_ms = int(datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp() * 1000)
        try:
            resp = await client.get(
                BINANCE_KLINES_URL,
                params={
                    "symbol": symbol,
                    "interval": "1d",
                    "startTime": start_ms,
                    "limit": BINANCE_KLINES_LIMIT,
                },
            )
            resp.raise_for_status()
            rows = klines_to_rows(resp.json())
        except Exception as exc:  # noqa: BLE001
            self.log_subsource("binance_gap_fill", coin, LogStatus.SKIPPED, f"symbol={symbol}, error={exc}")
            return []
        if not rows:
            self.log_subsource(
                "binance_gap_fill", coin, LogStatus.SKIPPED,
                f"symbol={symbol}, klines 回傳空序列或僅含當日未收盤 K 棒",
            )
            return []
        self.log_subsource(
            "binance_gap_fill", coin, LogStatus.OK,
            f"symbol={symbol}, 補齊 {len(rows)} 日（{rows[0]['date']}~{rows[-1]['date']}）",
        )
        return rows

    async def _build_ohlcv_evidences(
        self, client: httpx.AsyncClient, coin: str, data_dir: str, evidences: list[EvidenceDraft]
    ) -> None:
        """官方 CSV（＋缺口補齊）衍生的三筆價格證據：走勢摘要、當前動能、長期結構。

        直接寫進呼叫端的 `evidences`（而非回傳新 list）：中途拋錯時已經組好的前幾筆
        必須保留下來，不能整批作廢（R6-1 降級優先）。
        """
        csv_rows = load_ohlcv_all(coin, data_dir)
        csv_end = csv_rows[-1]["date"]
        gap_days = gap_days_since(csv_end)

        gap_rows: list[dict] = []
        if gap_days > GAP_FILL_TRIGGER_DAYS:
            gap_rows = await self._fetch_gap_klines(
                client, coin, date.fromisoformat(csv_end) + timedelta(days=1)
            )
        # 併接後的序列供當前訊號帶指標使用；長歷史指標仍只吃官方 CSV（R1-8／ADR-1）。
        spliced_rows = splice_ohlcv(csv_rows, gap_rows) if gap_rows else csv_rows
        as_of_date = spliced_rows[-1]["date"]
        gap_note = build_gap_note(csv_end, gap_rows, gap_days)

        indicator_rows = spliced_rows[-INDICATOR_WINDOW:]
        summary_rows = indicator_rows[-14:]
        # window 直接取自資料本身的日期欄，不用 today 回推——補齊失敗時序列末日仍是
        # CSV 末日，用 today 回推會宣稱涵蓋了其實沒有的天數（R1 資料時效斷層本身）。
        evidences.append(
            EvidenceDraft(
                coin=coin,
                source=f"HOYA BIT 共同基準資料集 (data/{coin}_daily_ohlcv.csv)",
                source_url=None,
                fetched_at=now_iso(),
                content_reference=summarize_ohlcv(summary_rows) + gap_note,
                related_claim=f"{coin} 近兩週價格走勢與成交量變化（基準日 {as_of_date}）",
                source_type="price",
                window_start=summary_rows[0]["date"] if summary_rows else None,
                window_end=as_of_date,
                horizon_class=HorizonClass.MEDIUM,
            )
        )

        # --- 技術指標：純 Python 決定性運算，不依賴 LLM，不會因額度失敗 ---
        indicators = compute_technical_indicators(indicator_rows)
        if indicators:
            # 拆成兩筆：當前動能（medium）與長期結構位置（structural）。合成一筆的話
            # 「RSI 超買」與「現價位於 5 年分佈高位」會共用一個 horizon，Step B 就會
            # 把兩者的方向差異讀成矛盾。
            series = build_indicator_series(indicator_rows)
            series_rows = indicator_rows[-SERIES_WINDOW:]
            evidences.append(
                EvidenceDraft(
                    coin=coin,
                    source=f"本地技術指標計算（依 {coin} 日線最近 {len(series_rows)} 日逐日重算，非外部資料）",
                    source_url=None,
                    fetched_at=now_iso(),
                    content_reference=(
                        summarize_current_indicators(indicators)
                        + gap_note
                        + "\n"
                        + summarize_series(series)
                    ),
                    related_claim=f"{coin} 近期技術面動能走勢（短均線、RSI、波動率、量能的 30 日序列）",
                    source_type="price",
                    window_start=series_rows[0]["date"] if series_rows else None,
                    window_end=as_of_date,
                    horizon_class=HorizonClass.MEDIUM,
                )
            )

            # 長歷史指標一律以官方 CSV 全歷史計算，不吃補齊區段（R1-8）：這樣才能主張
            # 長週期基準 100% 來自主辦方資料集。代價是它的基準日停在 csv_end，
            # 已由 window_end 誠實揭露。
            csv_indicator_rows = csv_rows[-INDICATOR_WINDOW:]
            structural = compute_technical_indicators(
                csv_indicator_rows, full_closes=[float(r["close"]) for r in csv_rows]
            )
            if has_structural_indicators(structural):
                evidences.append(
                    EvidenceDraft(
                        coin=coin,
                        source=f"本地長期結構指標計算（依 data/{coin}_daily_ohlcv.csv 全歷史 {len(csv_rows)} 日計算，非外部資料）",
                        source_url=None,
                        fetched_at=now_iso(),
                        content_reference=(
                            summarize_structural_indicators(
                                structural,
                                current_close=float(spliced_rows[-1]["close"]),
                                current_date=as_of_date,
                            )
                            + f"｜均線值與全歷史百分位一律以官方基準資料集（止於 {csv_end}）計算"
                        ),
                        related_claim=f"{coin} 長期結構位置（長均線位置、波動率全歷史百分位）——定位大週期位置，非短窗方向訊號",
                        source_type="price",
                        window_start=csv_rows[0]["date"],
                        window_end=csv_end,
                        horizon_class=HorizonClass.STRUCTURAL,
                    )
                )

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        evidences: list[EvidenceDraft] = []
        info = get_coin_info(coin)
        data_dir = self.settings.data_dir if self.settings else "data"

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            # --- 主要來源：主辦方提供之共同基準 OHLCV CSV（＋缺口補齊）---
            try:
                await self._build_ohlcv_evidences(client, coin, data_dir, evidences)
            except Exception as exc:  # noqa: BLE001
                self.log_subsource("ohlcv_csv", coin, LogStatus.ERROR, f"error={exc}")

            # --- 即時報價：CoinGecko（免 key），失敗則退 CryptoCompare（免 key）---
            try:
                resp = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={
                        "ids": info.coingecko_id,
                        "vs_currencies": "usd",
                        "include_24hr_change": "true",
                        "include_24hr_vol": "true",
                    },
                )
                resp.raise_for_status()
                data = resp.json()[info.coingecko_id]
                evidences.append(
                    EvidenceDraft(
                        coin=coin,
                        source="CoinGecko /simple/price",
                        source_url="https://api.coingecko.com/api/v3/simple/price",
                        fetched_at=now_iso(),
                        content_reference=(
                            f"query: ids={info.coingecko_id}&vs_currencies=usd | "
                            f"現價 {data.get('usd')} USD，24h 漲跌 {data.get('usd_24h_change', 0):.2f}%，"
                            f"24h 成交量 {data.get('usd_24h_vol', 0):.0f} USD"
                        ),
                        related_claim=f"{coin} 當前即時報價與 24 小時變化",
                        source_type="price",
                        horizon_class=HorizonClass.SPOT,  # 即時報價＝當下快照，無觀察窗
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.log_subsource("coingecko", coin, LogStatus.SKIPPED, f"error={exc}, fallback=cryptocompare")
                try:
                    resp = await client.get(
                        "https://min-api.cryptocompare.com/data/pricemultifull",
                        params={"fsyms": info.cryptocompare_symbol, "tsyms": "USD"},
                    )
                    resp.raise_for_status()
                    raw = resp.json()["RAW"][info.cryptocompare_symbol]["USD"]
                    evidences.append(
                        EvidenceDraft(
                            coin=coin,
                            source="CryptoCompare /data/pricemultifull（CoinGecko 備援）",
                            source_url="https://min-api.cryptocompare.com/data/pricemultifull",
                            fetched_at=now_iso(),
                            content_reference=(
                                f"query: fsyms={info.cryptocompare_symbol}&tsyms=USD | "
                                f"現價 {raw.get('PRICE')} USD，24h 漲跌 {raw.get('CHANGEPCT24HOUR', 0):.2f}%"
                            ),
                            related_claim=f"{coin} 當前即時報價與 24 小時變化",
                            source_type="price",
                            horizon_class=HorizonClass.SPOT,
                        )
                    )
                except Exception as exc2:  # noqa: BLE001
                    self.log_subsource("cryptocompare", coin, LogStatus.ERROR, f"error={exc2}")

            # --- 永續基差：Binance Futures premiumIndex（免 key），mark/index 價差是多空情緒佐證 ---
            try:
                resp = await client.get(
                    "https://fapi.binance.com/fapi/v1/premiumIndex",
                    params={"symbol": f"{info.ticker}USDT"},
                )
                resp.raise_for_status()
                data = resp.json()
                basis = compute_perp_basis(
                    mark_price=float(data["markPrice"]),
                    index_price=float(data["indexPrice"]),
                    funding_rate=float(data["lastFundingRate"]),
                )
                evidences.append(
                    EvidenceDraft(
                        coin=coin,
                        source="Binance Futures /fapi/v1/premiumIndex",
                        source_url="https://fapi.binance.com/fapi/v1/premiumIndex",
                        fetched_at=now_iso(),
                        content_reference=(
                            f"query: symbol={info.ticker}USDT | " + summarize_perp_basis(basis)
                        ),
                        related_claim=f"{coin} 永續合約基差與資金費率（多空情緒佐證）",
                        source_type="price",
                        horizon_class=HorizonClass.SPOT,  # premiumIndex 是當下報價，非序列
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.log_subsource("perp_basis", coin, LogStatus.ERROR, f"error={exc}")

        return evidences

"""事件日曆：FOMC／CPI（對照 02改_資料網格.html 的 `event-calendar` spec）。

五幣皆掛這格（層3背景資訊），BTC/ETH/BNB 只有 FOMC/CPI；SOL 額外掛 SOL 解鎖日
（chip 文字「FOMC／CPI＋SOL 解鎖日」）、XRP 額外掛 escrow 釋出日（chip 文字
「FOMC／CPI＋escrow 釋出日」）——這兩個額外事件不是這支腳本重新查一次，是直接
引用 `fetch_supply_calendar.py`（`coin-unlock-calendar` spec）已經人工研究好的
`SUPPLY_CALENDAR["SOL"]`／`SUPPLY_CALENDAR["XRP"]`，避免同一份資料兩處維護、
兩處可能兜不起來。

跟正式 `agent/collectors/` 還沒有對應模組，這裡先是 Ken 自己驗證用的 prototype。

資料來源：全部是賽前人工查證的靜態資料（2026-07-21 research 一次），不是即時
API——落實「賽前預快取事件日曆」原則，執行時零連線風險：

- FOMC 2026 全年 8 場會議日期：federalreserve.gov 官方行事曆
- CPI 2026 全年公布日期：BLS 官方公布時程（經 usinflationcalculator.com 彙整
  對照）

執行時只做本地日期運算（找出「今天之前最近一次」跟「今天之後最近一次」，算
距今天數），不重新查證日期本身——賽前如果時間允許應該對照官方行事曆重新核對
一次，尤其 FOMC 官方行事曆偶有微幅調整（例如因假日順延）。

用法：
    python pipeline/fetch_event_calendar.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from fetch_supply_calendar import SUPPLY_CALENDAR

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "macro"
RESEARCHED_AT = "2026-07-21"

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]

# 來源：https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_MEETINGS_2026 = [
    {"start_date": "2026-01-27", "end_date": "2026-01-28", "decision_date": "2026-01-28"},
    {"start_date": "2026-03-17", "end_date": "2026-03-18", "decision_date": "2026-03-18"},
    {"start_date": "2026-04-28", "end_date": "2026-04-29", "decision_date": "2026-04-29"},
    {"start_date": "2026-06-16", "end_date": "2026-06-17", "decision_date": "2026-06-17"},
    {"start_date": "2026-07-28", "end_date": "2026-07-29", "decision_date": "2026-07-29"},
    {"start_date": "2026-09-15", "end_date": "2026-09-16", "decision_date": "2026-09-16"},
    {"start_date": "2026-10-27", "end_date": "2026-10-28", "decision_date": "2026-10-28"},
    {"start_date": "2026-12-08", "end_date": "2026-12-09", "decision_date": "2026-12-09"},
]

# 來源：BLS CPI 公布時程，經 https://www.usinflationcalculator.com/inflation/consumer-price-index-release-schedule/ 彙整對照
CPI_RELEASES_2026 = [
    {"reference_month": "2025-12", "release_date": "2026-01-13"},
    {"reference_month": "2026-01", "release_date": "2026-02-13"},
    {"reference_month": "2026-02", "release_date": "2026-03-11"},
    {"reference_month": "2026-03", "release_date": "2026-04-10"},
    {"reference_month": "2026-04", "release_date": "2026-05-12"},
    {"reference_month": "2026-05", "release_date": "2026-06-10"},
    {"reference_month": "2026-06", "release_date": "2026-07-14"},
    {"reference_month": "2026-07", "release_date": "2026-08-12"},
    {"reference_month": "2026-08", "release_date": "2026-09-11"},
    {"reference_month": "2026-09", "release_date": "2026-10-14"},
    {"reference_month": "2026-10", "release_date": "2026-11-10"},
    {"reference_month": "2026-11", "release_date": "2026-12-10"},
]

SOURCES = [
    "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "https://www.usinflationcalculator.com/inflation/consumer-price-index-release-schedule/",
]

READ_COMMON = (
    "「距下次 FOMC／CPI 剩 X 天」是層3 背景資訊，用來提醒報告讀者「這個判斷是在"
    "什麼總經時間點做出的」，尤其 FOMC 利率決議／CPI 公布前後市場常提前定價或"
    "劇烈反應——如果查證當下剛好落在事件前後幾天窗口內，報告應該提醒讀者「近期"
    "波動可能部分反映總經事件不確定性，不能全部歸因給幣圈自身敘事」。"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nearest_past_and_future(events: list[dict], date_field: str, today: date) -> tuple[dict | None, dict | None]:
    past = [e for e in events if date.fromisoformat(e[date_field]) < today]
    future = [e for e in events if date.fromisoformat(e[date_field]) >= today]
    last_event = max(past, key=lambda e: e[date_field]) if past else None
    next_event = min(future, key=lambda e: e[date_field]) if future else None
    return last_event, next_event


def build_fomc_block(today: date) -> dict:
    last_meeting, next_meeting = nearest_past_and_future(FOMC_MEETINGS_2026, "decision_date", today)
    block: dict = {}
    if last_meeting:
        block["last_meeting"] = {
            **last_meeting,
            "days_since": (today - date.fromisoformat(last_meeting["decision_date"])).days,
        }
    if next_meeting:
        block["next_meeting"] = {
            **next_meeting,
            "days_until": (date.fromisoformat(next_meeting["decision_date"]) - today).days,
        }
    block["schedule_2026"] = FOMC_MEETINGS_2026
    return block


def build_cpi_block(today: date) -> dict:
    last_release, next_release = nearest_past_and_future(CPI_RELEASES_2026, "release_date", today)
    block: dict = {}
    if last_release:
        block["last_release"] = {
            **last_release,
            "days_since": (today - date.fromisoformat(last_release["release_date"])).days,
        }
    if next_release:
        block["next_release"] = {
            **next_release,
            "days_until": (date.fromisoformat(next_release["release_date"]) - today).days,
        }
    block["schedule_2026"] = CPI_RELEASES_2026
    return block


def build_coin_specific_event(coin: str) -> dict | None:
    if coin not in ("SOL", "XRP"):
        return None
    entry = SUPPLY_CALENDAR[coin]
    block = {
        "source_spec": "coin-unlock-calendar（fetch_supply_calendar.py，非本腳本重新查證）",
        "schedule_type": entry["schedule_type"],
    }
    # SOL 是 irregular_estate_liquidation，沒有 next_event，只有 last_event／
    # remaining_estate_position；XRP 是 monthly_escrow_release，只有 next_event。
    # 兩幣欄位不對稱是資料本質不同，不是漏寫，這裡照實把兩幣各自有的欄位帶出來。
    for key in ("next_event", "last_event", "remaining_estate_position"):
        if key in entry:
            block[key] = entry[key]
    return block


def write_output(coin: str, today: date) -> Path:
    payload = {
        "coin": coin,
        "researched_at": RESEARCHED_AT,
        "written_at": now_iso(),
        "fomc": build_fomc_block(today),
        "cpi": build_cpi_block(today),
        "read": READ_COMMON,
        "sources": SOURCES,
    }
    coin_event = build_coin_specific_event(coin)
    if coin_event:
        payload["coin_specific_event"] = coin_event

    out_path = RAW_DATA_DIR / coin / "event_calendar_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    today = date.today()
    for coin in COINS:
        out_path = write_output(coin, today)
        print(f"[{coin}] 已寫入 {out_path}")
    print()
    print(f"今天 {today.isoformat()}：")
    fomc = build_fomc_block(today)
    cpi = build_cpi_block(today)
    if "next_meeting" in fomc:
        print(f"  距下次 FOMC 決議（{fomc['next_meeting']['decision_date']}）還有 {fomc['next_meeting']['days_until']} 天")
    if "next_release" in cpi:
        print(f"  距下次 CPI 公布（{cpi['next_release']['release_date']}，{cpi['next_release']['reference_month']} 資料）還有 {cpi['next_release']['days_until']} 天")


if __name__ == "__main__":
    main()

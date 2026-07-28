"""總體經濟 collector：Fear & Greed Index（免 key）＋ 美元指數 DXY（stooq 免 key CSV）。

若使用者提供 FRED 免費 key，可額外疊加美債殖利率等指標（補充來源）。
"""

from __future__ import annotations

from datetime import date

import httpx

from agent.collectors.base import BaseCollector
from agent.collectors.horizon import window_back
from agent.schemas import EvidenceDraft, HorizonClass, LogStatus, now_iso

HTTP_TIMEOUT = 20.0
FNG_WINDOW = 30

# 併自 pipeline/fetch_supply_calendar.py：BTC/BNB/XRP/SOL 四幣供給節奏日曆，
# 賽前人工研究、寫死的靜態資料（2026-07-21 research 一次），執行時零連線風險。
# ETH 查證過沒有等價的「固定日期＋供給數字」事件（發行量持續性，Glamsterdam
# 硬分叉是效能升級不是供給事件），維持不掛這格。⚠️ 有時效性，尤其 SOL 的
# FTX estate 清算是持續進行式，賽前如果時間允許應該重新查一次確認沒有變動。
SUPPLY_CALENDAR_RESEARCHED_AT = "2026-07-21"
NEXT_HALVING_ESTIMATED_DATE = date(2028, 4, 17)

SUPPLY_CALENDAR: dict[str, dict] = {
    "BTC": {
        "schedule_type": "halving",
        "cycle": "每 210,000 區塊（約 4 年）一次，區塊獎勵腰斬",
        "last_event": {
            "date": "2024-04-20",
            "label": "第 4 次減半，區塊高度 840,000",
            "reward_before_btc": 6.25,
            "reward_after_btc": 3.125,
        },
        "next_event": {
            "date_estimated": NEXT_HALVING_ESTIMATED_DATE.isoformat(),
            "label": "第 5 次減半（預估日期隨平均出塊時間微調，會逐漸收斂）",
            "reward_before_btc": 3.125,
            "reward_after_btc": 1.5625,
        },
    },
    "BNB": {
        "schedule_type": "quarterly_burn",
        "cycle": "每年 1／4／7／10 月，官方 Auto-Burn 公告",
        "last_event": {
            "date": "2026-07-15",
            "label": "第 36 次季度銷毀",
            "amount_bnb": 1_600_000,
            "amount_usd": 931_700_000,
        },
        "next_event": {
            "date": "2026-10",
            "label": "第 37 次季度銷毀（確切日期通常燒毀前幾天才公告）",
        },
    },
    "XRP": {
        "schedule_type": "monthly_escrow_release",
        "cycle": "每月 1 日固定釋出",
        "next_event": {
            "date": "2026-08-01",
            "gross_amount_xrp": 1_000_000_000,
            "label": "多數會被重新鎖回下一期 escrow，實際淨流入市場常僅 2-4 億枚",
        },
    },
    "SOL": {
        "schedule_type": "irregular_estate_liquidation",
        "cycle": "無固定週期——依 FTX/Alameda 破產遺產清算進度，法院/受託人決定",
        "last_event": {
            "date": "2026-07",
            "label": "FTX/Alameda estate 解鎖批次",
            "amount_sol": 198_000,
            "amount_usd": 16_210_000,
        },
        "remaining_estate_position": {
            "amount_sol": 4_180_000,
            "amount_usd": 977_000_000,
            "status": "質押中，陸續解鎖",
        },
    },
}

# 併自 pipeline/fetch_event_calendar.py：FOMC／CPI 2026 全年時程，賽前人工查證
# 的靜態資料，執行時只做本地日期運算，不重新查證日期本身——賽前如果時間允許
# 應該對照官方行事曆重新核對一次（FOMC 偶有因假日順延的微幅調整）。
EVENT_CALENDAR_RESEARCHED_AT = "2026-07-21"

# 來源：https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_MEETINGS_2026 = [
    {"decision_date": "2026-01-28"},
    {"decision_date": "2026-03-18"},
    {"decision_date": "2026-04-29"},
    {"decision_date": "2026-06-17"},
    {"decision_date": "2026-07-29"},
    {"decision_date": "2026-09-16"},
    {"decision_date": "2026-10-28"},
    {"decision_date": "2026-12-09"},
]

# 來源：BLS CPI 公布時程，經 usinflationcalculator.com 彙整對照
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


def compute_fng_percentile(values: list[int], current: int) -> float:
    """回傳 current 在近 N 天序列（含當天）中的百分位：當天值贏過幾成樣本。"""
    if not values:
        return 0.0
    count_le = sum(1 for v in values if v <= current)
    return count_le / len(values) * 100


def supply_calendar_summary(coin: str, today: date) -> str | None:
    """依 SUPPLY_CALENDAR 組一行摘要；ETH（或任何未掛這格的幣）回傳 None，
    呼叫端應視為「這幣沒有對應供給事件」而略過，不是錯誤。"""
    entry = SUPPLY_CALENDAR.get(coin.upper())
    if entry is None:
        return None

    parts = [f"類型={entry['schedule_type']}（{entry['cycle']}）"]

    last = entry.get("last_event")
    if last:
        detail = "，".join(f"{k}={v}" for k, v in last.items() if k not in ("date", "label"))
        parts.append(f"上次{last['date']}：{last['label']}" + (f"（{detail}）" if detail else ""))

    next_event = entry.get("next_event")
    if next_event:
        if coin.upper() == "BTC":
            days_until = (NEXT_HALVING_ESTIMATED_DATE - today).days
            parts.append(f"下次預估{next_event['date_estimated']}（距今約{days_until}天）：{next_event['label']}")
        else:
            parts.append(f"下次{next_event['date']}：{next_event['label']}")

    remaining = entry.get("remaining_estate_position")
    if remaining:
        parts.append(
            f"剩餘部位約{remaining['amount_sol']:,}枚（約${remaining['amount_usd']:,}，{remaining['status']}）"
        )

    return "｜".join(parts)


def _nearest_past_and_future(events: list[dict], date_field: str, today: date) -> tuple[dict | None, dict | None]:
    past = [e for e in events if date.fromisoformat(e[date_field]) < today]
    future = [e for e in events if date.fromisoformat(e[date_field]) >= today]
    last_event = max(past, key=lambda e: e[date_field]) if past else None
    next_event = min(future, key=lambda e: e[date_field]) if future else None
    return last_event, next_event


def event_calendar_summary(coin: str, today: date) -> str:
    """FOMC／CPI 距今天數＋（SOL/XRP）額外掛供給事件，一行摘要。"""
    parts: list[str] = []

    last_meeting, next_meeting = _nearest_past_and_future(FOMC_MEETINGS_2026, "decision_date", today)
    if next_meeting:
        days_until = (date.fromisoformat(next_meeting["decision_date"]) - today).days
        parts.append(f"下次FOMC決議{next_meeting['decision_date']}（{days_until}天後）")
    if last_meeting:
        days_since = (today - date.fromisoformat(last_meeting["decision_date"])).days
        parts.append(f"上次FOMC決議{last_meeting['decision_date']}（{days_since}天前）")

    last_release, next_release = _nearest_past_and_future(CPI_RELEASES_2026, "release_date", today)
    if next_release:
        days_until = (date.fromisoformat(next_release["release_date"]) - today).days
        parts.append(f"下次CPI公布{next_release['release_date']}（{days_until}天後，{next_release['reference_month']}資料）")
    if last_release:
        days_since = (today - date.fromisoformat(last_release["release_date"])).days
        parts.append(f"上次CPI公布{last_release['release_date']}（{days_since}天前）")

    coin = coin.upper()
    if coin == "SOL":
        entry = SUPPLY_CALENDAR.get("SOL", {})
        last = entry.get("last_event")
        if last:
            parts.append(f"SOL特有：近期解鎖{last['date']}（FTX estate 清算，無固定下次日期）")
    elif coin == "XRP":
        entry = SUPPLY_CALENDAR.get("XRP", {})
        next_event = entry.get("next_event")
        if next_event:
            parts.append(f"XRP特有：下次escrow釋出{next_event['date']}")

    return "｜".join(parts)


class MacroCollector(BaseCollector):
    name = "macro_collector"
    source_type = "macro"

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        evidences: list[EvidenceDraft] = []

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            try:
                resp = await client.get(
                    "https://api.alternative.me/fng/", params={"limit": FNG_WINDOW}
                )
                resp.raise_for_status()
                data = resp.json()["data"]
                item = data[0]
                values = [int(d["value"]) for d in data]
                percentile = compute_fng_percentile(values, int(item["value"]))
                # 窗長用實得筆數而非 FNG_WINDOW：API 少回幾天時不該宣稱涵蓋 30 天
                fng_start, fng_end = window_back(len(values))
                evidences.append(
                    EvidenceDraft(
                        coin=coin,
                        source="Fear & Greed Index (alternative.me)",
                        source_url="https://api.alternative.me/fng/",
                        fetched_at=now_iso(),
                        content_reference=(
                            f"value={item.get('value')}, classification={item.get('value_classification')}, "
                            f"timestamp={item.get('timestamp')}, 近{len(values)}天百分位={percentile:.1f}%, "
                            f"近{len(values)}天範圍={min(values)}-{max(values)}"
                        ),
                        related_claim="整體加密市場情緒指標（近 30 天百分位）",
                        source_type="macro",
                        window_start=fng_start,
                        window_end=fng_end,
                        horizon_class=HorizonClass.MEDIUM,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.log_subsource("fear_greed", coin, LogStatus.ERROR, f"error={exc}")

            try:
                # stooq 已加上瀏覽器 JS 驗證機制，無法穩定免 key 存取；改用 Frankfurter（歐洲央行公開匯率
                # API，免 key、穩定）以 USD/EUR 匯率變化作為美元強弱的簡易總經代理指標。
                resp = await client.get(
                    "https://api.frankfurter.app/latest", params={"from": "USD", "to": "EUR,JPY,GBP"}
                )
                resp.raise_for_status()
                data = resp.json()
                rates = data.get("rates", {})
                evidences.append(
                    EvidenceDraft(
                        coin=coin,
                        source="Frankfurter 美元匯率（歐洲央行公開資料，美元強弱代理指標）",
                        source_url="https://api.frankfurter.app/latest?from=USD",
                        fetched_at=now_iso(),
                        content_reference=f"date={data.get('date')}, USD/EUR={rates.get('EUR')}, USD/JPY={rates.get('JPY')}, USD/GBP={rates.get('GBP')}",
                        related_claim="美元相對強弱走勢（總經背景，加密市場常呈負相關）",
                        source_type="macro",
                        horizon_class=HorizonClass.SPOT,  # /latest 只給最新一日匯率，非序列
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.log_subsource("frankfurter_fx", coin, LogStatus.ERROR, f"error={exc}")

            if self.settings and getattr(self.settings, "fred_api_key", None):
                try:
                    resp = await client.get(
                        "https://api.stlouisfed.org/fred/series/observations",
                        params={
                            "series_id": "DGS10",
                            "api_key": self.settings.fred_api_key,
                            "file_type": "json",
                            "sort_order": "desc",
                            "limit": 1,
                        },
                    )
                    resp.raise_for_status()
                    obs = resp.json()["observations"][0]
                    evidences.append(
                        EvidenceDraft(
                            coin=coin,
                            source="FRED DGS10（10年期美債殖利率，補充來源）",
                            source_url="https://fred.stlouisfed.org/series/DGS10",
                            fetched_at=now_iso(),
                            content_reference=f"date={obs.get('date')}, value={obs.get('value')}",
                            related_claim="美債殖利率走勢（總經背景）",
                            source_type="macro",
                            horizon_class=HorizonClass.SPOT,  # limit=1，只取最新一筆觀測
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    self.log_subsource("fred", coin, LogStatus.SKIPPED, f"error={exc}")

        # 併自 pipeline/fetch_supply_calendar.py + fetch_event_calendar.py：純本地
        # 靜態資料＋日期運算，零連線風險，不需要 httpx client。
        today = date.today()
        try:
            summary = supply_calendar_summary(coin, today)
            if summary:
                evidences.append(
                    EvidenceDraft(
                        coin=coin,
                        source=f"幣種供給節奏日曆（賽前人工研究 {SUPPLY_CALENDAR_RESEARCHED_AT}，非即時 API）",
                        source_url=None,
                        fetched_at=now_iso(),
                        content_reference=summary,
                        related_claim=f"{coin} 供給面事件日曆（減半／銷毀／解鎖等）",
                        source_type="macro",
                    )
                )
            else:
                self.log_subsource(
                    "supply_calendar", coin, LogStatus.SKIPPED, "無對應供給事件（發行持續性，無固定日期事件）"
                )
        except Exception as exc:  # noqa: BLE001
            self.log_subsource("supply_calendar", coin, LogStatus.ERROR, f"error={exc}")

        try:
            evidences.append(
                EvidenceDraft(
                    coin=coin,
                    source=f"FOMC／CPI 事件日曆（賽前人工查證 {EVENT_CALENDAR_RESEARCHED_AT} 2026全年時程，非即時 API）",
                    source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                    fetched_at=now_iso(),
                    content_reference=event_calendar_summary(coin, today),
                    related_claim=f"{coin} 總經事件時間點（FOMC／CPI，判斷近期波動是否有總經背景）",
                    source_type="macro",
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.log_subsource("event_calendar", coin, LogStatus.ERROR, f"error={exc}")

        return evidences

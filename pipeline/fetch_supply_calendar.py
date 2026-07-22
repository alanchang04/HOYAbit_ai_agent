"""幣種供給節奏日曆（對照 02改_資料網格.html 的 `coin-unlock-calendar` spec）。

BTC/SOL/BNB/XRP 四幣掛這格，ETH 排除。第一版判斷是「BTC/ETH 發行完全由協議
寫死，沒有外部強加的解鎖排程，沒有日曆可做」——這個理由對 ETH 成立，但對 BTC
不成立：減半（halving）本身就是有明確區塊高度、可推算日期的供給事件，是這格
的教科書案例，只是週期比 SOL/BNB/XRP 長很多（約 4 年 vs 季度/月度）。ETH 查證
過 2026 年沒有等價的「固定日期＋供給數字」事件（發行量是持續性的，Glamsterdam
硬分叉是效能升級不是供給事件），維持排除。

跟正式 `agent/collectors/` 還沒有對應模組，這裡先是 Ken 自己驗證用的 prototype。

資料來源：全部是賽前人工研究整理（2026-07-21 research 一次），不是即時 API——
落實「賽前預快取事件日曆」原則，執行時零連線風險。四幣規律性不同，寫法也不同：

- BTC：協議寫死的區塊高度事件（每 210,000 區塊），規律性最高、週期最長
- BNB：協議公告的固定季度銷毀（1/4/7/10 月），規律性最高
- XRP：Ripple escrow 固定每月 1 日釋出 10 億枚，規律性最高，但多數會被重新鎖回
- SOL：目前最大的近期供給壓力來源其實是 FTX/Alameda 破產遺產清算，不是生態基金
  /團隊 vesting；沒有固定日期規則，依法院/受託人清算進度決定，跟 BTC/BNB/XRP 的
  「協議層固定排程」性質不同，`schedule_type` 特別標成 irregular，報告措辭不能
  套用其他三幣那種「下次日期」的確定性語氣

⚠️ 這份資料有時效性，數字是 2026-07-21 當下人工查證的結果，賽前如果時間允許
應該重新查一次確認日期/金額沒有變動（尤其 SOL 的 FTX estate 清算是持續進行式）。
BTC 的減半預估日期本身也是賽前查好的靜態值，只有「距下次減半還有幾天」是每次
執行時即時算出來的，不是寫死的數字。

用法：
    python pipeline/fetch_supply_calendar.py
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "macro"
RESEARCHED_AT = "2026-07-21"
NEXT_HALVING_ESTIMATED_DATE = date(2028, 4, 17)

SUPPLY_CALENDAR = {
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
            "block_height": 1_050_000,
            "label": "第 5 次減半（預估日期隨平均出塊時間微調，會逐漸收斂）",
            "reward_before_btc": 3.125,
            "reward_after_btc": 1.5625,
        },
        "read": "減半＝區塊獎勵腰斬，是供給面最確定的長期通縮敘事，但下次減半"
        "通常還有數年，執行當下多半只能講「距下次減半還有 X 天，發行速度尚未"
        "變動」這種背景鋪陳，不是近期催化劑，跟 SOL/BNB/XRP 的「近期」事件時間"
        "尺度不同，報告裡不要跟其他三幣的迫切性並列。",
        "sources": [
            "https://bitbo.io/halving/",
        ],
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
        "read": "銷毀＝供給收縮敘事，是通縮訊號；金額隨 BNB 價格與當季 BSC 出塊量連動，"
        "屬該幣特有（層2）供給結構訊號，不同幣種之間不能直接比大小。",
        "sources": [
            "https://cryptopotato.com/bnb-chain-completes-36th-quarterly-token-burn-marks-third-burn-of-2026/",
            "https://www.bnbburn.info/",
        ],
    },
    "XRP": {
        "schedule_type": "monthly_escrow_release",
        "cycle": "每月 1 日固定釋出",
        "next_event": {
            "date": "2026-08-01",
            "gross_amount_xrp": 1_000_000_000,
            "typical_relock_pct_range": [60, 80],
            "label": "多數會被重新鎖回下一期 escrow，實際淨流入市場常僅 2-4 億枚",
        },
        "read": "大額解鎖前市場常有拋壓預期，但 Ripple escrow 機制設計成可預測、"
        "多數會重新鎖回，讀的時候要強調「總量大但淨流入通常小很多」，不是單純的"
        "拋壓利空。",
        "sources": [
            "https://crypto.news/how-ripples-xrp-escrow-works-monthly-unlock-explained/",
        ],
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
        "read": "⚠️ 跟 BTC/BNB/XRP 不同，這不是協議層固定排程，是破產清算進度，沒有"
        "「下次確切日期」——報告措辭不能講「下次解鎖是 X 天後」這種確定性語氣，"
        "只能講「近期供給壓力來源是 FTX estate 持續清算，規模約 X」。",
        "sources": [
            "https://cryptorank.io/news/feed/773ad-ftx-alameda-unstakes-sol-liquidation",
        ],
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_output(coin: str, entry: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "supply_calendar_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "coin": coin,
        "researched_at": RESEARCHED_AT,
        "written_at": now_iso(),
        **entry,
    }
    if coin == "BTC":
        payload["next_event"]["days_until_estimated"] = (
            NEXT_HALVING_ESTIMATED_DATE - date.today()
        ).days
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    for coin, entry in SUPPLY_CALENDAR.items():
        out_path = write_output(coin, entry)
        print(f"[{coin}] {entry['schedule_type']} → 已寫入 {out_path}")
        if "next_event" in entry:
            print(f"  下一次：{entry['next_event']}")
        if "last_event" in entry:
            print(f"  最近一次：{entry['last_event']}")
        print()
    print("[ETH] 發行量持續性、無固定日期供給事件，設計上不掛這格，跳過")


if __name__ == "__main__":
    main()

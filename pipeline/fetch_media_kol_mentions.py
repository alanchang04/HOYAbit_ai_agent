"""Social 方向：媒體轉寫大老觀點（原「X 大老提及次數＋觀點立場」降級後的替代做法，
對照 `02改_資料網格.html` 的 `x-mention-count` spec，spec id 沿用未改，內容已更新）。

背景：直接查 X（Twitter）大老帳號需要付費 API（Basic 約 $200/mo 起，見
`pipeline/待辦筆記/x大老_社群訊號.md`），Ken 拍板改用「已經在幫忙把大老在 X 上的
發言轉寫成報導的中文加密媒體」取代，免 key、免費，邏輯比直接爬 X 簡單很多：
媒體記者已經做完「這則推文值不值得報導」的篩選跟摘要，我們只要抓現成報導。

不做規則式看多看空分類（跟 YT 逐字稿那條不同）：PANews 快訊本身常常直接引用
大老原話（例如「莱比特矿池创始人江卓尔表示：'这一轮走完，我不空ETH了，改空
BTC。'」），這種完整句子丟給 LLM 判斷立場比關鍵字計數準，規則式分類在這裡反而
是多餘的中間層——層1 提及次數用命中筆數，層2 觀點就是原始 title+summary 文字，
直接當 evidence 餵給 LLM。

跟即時報價／onchain／news 一樣，這是「當下一個時間點」快照，沒有歷史序列，
每次跑都會覆蓋掉上一次的結果。

用法：
    python pipeline/fetch_media_kol_mentions.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "social"
HTTP_TIMEOUT = 20.0
MAX_ITEMS_PER_COIN = 10
USER_AGENT = "hoyabit-crypto-agent/1.0"

# PANews 首頁「RSS訂閱」按鈕(`/zh/rss`)產生的正式訂閱網址，非猜測。type=NEWS 是
# 快訊（近乎即時，實測 100 篇涵蓋約 17 小時），type=NORMAL 是深度文章（實測 100
# 篇涵蓋約 5 天）；兩條都抓，快訊補新鮮度、深度文章補命中率。
FEEDS: dict[str, str] = {
    "NEWS": "https://www.panewslab.com/rss.xml?lang=zh&type=NEWS",
    "NORMAL": "https://www.panewslab.com/rss.xml?lang=zh&type=NORMAL",
}

# ⚠️ BNB／XRP 刻意不比對「币安」「Binance」「Ripple」——這幾個是交易所/公司名稱，
# 命中的多半是上下架公告、機房維護這類跟代幣本身無關的操作新聞（實測 2026-07-28
# 踩過這個坑：「币安」在快訊裡命中 9 篇，幾乎都是交易對上下架公告）。只留代幣
# 自己的代稱，寧可少抓也不要混進噪音。BNB 額外加「赵长鹏／CZ」——他是 BNB 創辦人，
# 具名發言直接算大老觀點，不會像「币安」那樣把交易所日常公告也撈進來（實測加
# 這兩個詞在 200 篇樣本裡多抓到 1 篇真實觀點，XRP 那邊試過 Garlinghouse／
# David Schwartz／孫宇晨這幾個具名大老，同樣 200 篇樣本裡 0 命中，這個時間窗口
# 就是沒有 XRP 大老觀點被報導，不是關鍵字沒抓對，暫不加）。
COIN_KEYWORDS: dict[str, list[str]] = {
    "BTC": ["比特币", "BTC"],
    "ETH": ["以太坊", "ETH", "以太币"],
    "SOL": ["Solana", "SOL"],
    "BNB": ["BNB", "赵长鹏", "Changpeng Zhao"],
    "XRP": ["XRP", "瑞波币", "瑞波幣"],
}

# 實測 2026-07-28 抓到的具體假陽性：「ZuriQ完成2550万美元种子轮融资」命中 ETH
# 關鍵字，是因為內文提到「苏黎世联邦理工学院（ETH Zurich）」——瑞士這間大學的
# 英文縮寫剛好也是 ETH，跟以太坊無關。命中任一排除詞就整篇跳過，不計入該幣。
COIN_EXCLUDE_KEYWORDS: dict[str, list[str]] = {
    "ETH": ["ETH Zurich", "苏黎世联邦理工"],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_feed_entries(client: httpx.Client, feed_name: str, url: str) -> list[dict]:
    resp = client.get(url)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.text)
    entries = []
    for entry in parsed.entries:
        entries.append({
            "feed": feed_name,
            "title": entry.get("title", ""),
            "summary": entry.get("summary", ""),
            "url": entry.get("link", ""),
            "published": entry.get("published", "未知"),
        })
    return entries


def match_coin(coin: str, entry: dict) -> bool:
    haystack = f"{entry['title']} {entry['summary']}"
    if any(kw in haystack for kw in COIN_EXCLUDE_KEYWORDS.get(coin, [])):
        return False
    return any(kw in haystack for kw in COIN_KEYWORDS[coin])


def fetch_all() -> dict:
    now = now_iso()
    all_entries: list[dict] = []
    errors: list[str] = []

    with httpx.Client(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for feed_name, url in FEEDS.items():
            try:
                all_entries.extend(fetch_feed_entries(client, feed_name, url))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{feed_name}: error={exc}")

    result: dict[str, dict] = {}
    for coin in COIN_KEYWORDS:
        matched = [e for e in all_entries if match_coin(coin, e)][:MAX_ITEMS_PER_COIN]
        result[coin] = {
            "coin": coin,
            "mention_count": len(matched),
            "items": matched,
            "errors": errors,
            "fetched_at": now,
        }
    return result


def write_output(coin: str, payload: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "media_kol_mentions_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    # Windows 主控台預設 cp950，印不出全形符號，強制 stdout 走 UTF-8（跟
    # fetch_news.py／compute_historical_volatility_percentile.py 踩過的同一個坑）。
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    results = fetch_all()
    for coin, payload in results.items():
        out_path = write_output(coin, payload)
        print(f"[{coin}] 已寫入 {out_path}（{payload['mention_count']} 筆）")
        for item in payload["items"]:
            print(f"  [{item['feed']}] {item['title'][:60]}")
            if item["summary"]:
                print(f"    摘要：{item['summary'][:150]}")
        for err in payload["errors"]:
            print(f"  ⚠️ {err}")
        print()


if __name__ == "__main__":
    main()

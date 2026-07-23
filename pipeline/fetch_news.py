"""News 方向：五幣官方發布源快照（對照 02改_資料網格.html 的「3 News 新聞」色塊）。

跟 `agent/collectors/news.py` 的正式實作邏輯完全一致（2026-07-20 那次改版是
直接改在正式 collector，沒有先經過這層 pipeline prototype，這支是事後補的，
純粹讓這個方向也留一份跟其他方向一樣的獨立驗證腳本，邏輯本身沒有新內容）：
每幣官方發布源優先，有 RSS 用 RSS，沒有則退階解析官方頁面 HTML。不再用
CoinDesk／Cointelegraph／CryptoPanic 等第三方媒體聚合（第三方聚合角色移去
social 方向），理由見 `pipeline/流程紀錄.md` 的「新聞（News）」章節。

跟即時報價／onchain 一樣，這是「當下一個時間點」的快照，沒有歷史序列版本，
每次跑都會覆蓋掉上一次的結果。

用法：
    python pipeline/fetch_news.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx
from bs4 import BeautifulSoup

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "news"
HTTP_TIMEOUT = 20.0
MAX_ITEMS_PER_SOURCE = 5
USER_AGENT = "hoyabit-crypto-agent/1.0"

# 跟 agent/collectors/news.py 的 OFFICIAL_SOURCES 同一份設定，維護時兩邊要一起改。
OFFICIAL_SOURCES: dict[str, list[dict]] = {
    "BTC": [
        {"name": "Bitcoin Optech Newsletter", "kind": "rss", "url": "https://bitcoinops.org/feed.xml"},
    ],
    "ETH": [
        {"name": "Ethereum Foundation Blog", "kind": "rss", "url": "https://blog.ethereum.org/feed.xml"},
    ],
    "SOL": [
        {"name": "Solana Foundation News", "kind": "rss", "url": "https://solana.com/news/rss.xml"},
    ],
    "BNB": [
        {"name": "BNB Chain Blog", "kind": "html", "url": "https://www.bnbchain.org/en/blog"},
    ],
    "XRP": [
        {"name": "Ripple Insights", "kind": "html", "url": "https://ripple.com/insights/"},
    ],
}

# 對照 02改_資料網格.html 的 news-coin-keywords spec：每幣 3-6 個特有主題，
# 各主題掛幾個英文關鍵字（官方源文章標題多是英文）。只比對標題大小寫不敏感的
# substring，不是語意分類——命中就標記主題名，沒命中不代表本週沒這個敘事，
# 只代表這批標題沒直接提到，報告措辭要照這個誠實。
NARRATIVE_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "BTC": {
        "ETF 資金流": ["etf", "inflow", "outflow"],
        "企業／國家儲備": ["reserve", "treasury", "strategic bitcoin"],
        "減半供給敘事": ["halving", "halve", "block reward"],
        "挖礦算力": ["hashrate", "hash rate", "miner", "mining"],
    },
    "ETH": {
        "網路升級": ["pectra", "fusaka", "glamsterdam", "hard fork", "upgrade"],
        "質押／再質押": ["staking", "restaking", "validator"],
        "L2 生態": ["layer 2", "l2", "rollup", "optimism", "arbitrum", "base"],
        "ETH ETF": ["etf"],
    },
    "SOL": {
        "網路穩定性／宕機": ["outage", "downtime", "degraded"],
        "memecoin 生態": ["memecoin", "meme coin", "pump.fun"],
        "支付／DePIN": ["payments", "depin", "point of sale", "pay"],
        "SOL ETF": ["etf"],
    },
    "BNB": {
        "季度銷毀": ["burn"],
        "BNB Chain 生態升級": ["upgrade", "hard fork", "opbnb", "greenfield"],
    },
    "XRP": {
        "SEC 案終局／監管明確化": ["sec", "lawsuit", "regulation", "regulatory"],
        "RLUSD 穩定幣": ["rlusd", "stablecoin"],
        "跨境支付 ODL": ["odl", "cross-border", "cross border", "on-demand liquidity"],
        "XRP ETF": ["etf"],
    },
}


def tag_narrative_topics(coin: str, *texts: str) -> list[str]:
    combined = " ".join(texts).lower()
    return [
        topic
        for topic, keywords in NARRATIVE_KEYWORDS.get(coin.upper(), {}).items()
        if any(kw in combined for kw in keywords)
    ]


def strip_html(text: str) -> str:
    return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)


# 有些站的單篇文章頁沒設專屬 og:description，會退回網站全站通用標語（og:title
# 仍是文章專屬的，只有 description 這欄位是罐頭文字）。實測發現 Ripple Insights
# 5 篇裡有 3 篇是這句——不是文章摘要，混進比對／報告會誤導 LLM 以為文章在講這個，
# 直接濾掉當作沒有摘要。之後如果其他站也踩到同款罐頭文字，往這個集合加就好。
GENERIC_DESCRIPTION_FALLBACKS = {
    "ripple is the leading blockchain payments company.",
}


def fetch_meta_description(client: httpx.Client, url: str) -> str:
    """點進單篇文章頁抓 og:description／meta description 當內文摘要——BNB／XRP
    這兩站的本文卡在破碎的 emotion-css div 裡抓不穩，但社群分享用的 meta
    description 兩邊都有乾淨的一段文字，比硬解析內文可靠。"""
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for attrs in ({"property": "og:description"}, {"name": "description"}):
        tag = soup.find("meta", attrs=attrs)
        content = tag["content"].strip() if tag and tag.get("content") else ""
        if content and content.lower() not in GENERIC_DESCRIPTION_FALLBACKS:
            return content
    return ""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scrape_bnbchain_blog(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    items: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.match(r"^/en/blog/[^/]+$", href):
            continue
        if href in seen:
            continue
        seen.add(href)
        slug = href.rsplit("/", 1)[-1]
        title = slug.replace("-", " ").strip().capitalize()
        items.append({
            "title": f"{title}（標題由網址還原，非原文標題）",
            "url": f"https://www.bnbchain.org{href}",
            "published": "未知",
        })
        if len(items) >= MAX_ITEMS_PER_SOURCE:
            break
    return items


def _scrape_ripple_insights(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    order: list[str] = []
    by_href: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.match(r"^/insights/[^/]+/$", href):
            continue
        title_tag = a.find("p")
        title = title_tag.get_text(strip=True) if title_tag else None
        if href not in by_href:
            order.append(href)
            by_href[href] = {"title": title, "text": a.get_text(" ", strip=True)}
        elif title and not by_href[href]["title"]:
            by_href[href]["title"] = title
            by_href[href]["text"] = a.get_text(" ", strip=True)

    items: list[dict] = []
    for href in order:
        entry = by_href[href]
        date_match = re.search(r"[A-Za-z]+ \d{1,2}, \d{4}", entry["text"])
        items.append({
            "title": entry["title"] or href,
            "url": f"https://ripple.com{href}",
            "published": date_match.group(0) if date_match else "未知",
        })
        if len(items) >= MAX_ITEMS_PER_SOURCE:
            break
    return items


HTML_SCRAPERS = {
    "BNB Chain Blog": _scrape_bnbchain_blog,
    "Ripple Insights": _scrape_ripple_insights,
}


def fetch_coin(client: httpx.Client, coin: str) -> dict:
    sources = OFFICIAL_SOURCES.get(coin.upper(), [])
    items: list[dict] = []
    errors: list[str] = []

    for source in sources:
        try:
            resp = client.get(source["url"])
            resp.raise_for_status()

            if source["kind"] == "rss":
                parsed = feedparser.parse(resp.text)
                for entry in parsed.entries[:MAX_ITEMS_PER_SOURCE]:
                    title = entry.get("title", "")
                    summary = strip_html(entry.get("summary", "")) if entry.get("summary") else ""
                    items.append({
                        "source": f"{source['name']}（官方源）",
                        "url": entry.get("link", source["url"]),
                        "title": title,
                        "published": entry.get("published", "未知"),
                        "summary": summary,
                        "narrative_topics": tag_narrative_topics(coin, title, summary),
                    })
            else:
                for item in HTML_SCRAPERS[source["name"]](resp.text):
                    summary = ""
                    try:
                        summary = fetch_meta_description(client, item["url"])
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"{item['url']}: summary fetch error={exc}")
                    items.append({
                        "source": f"{source['name']}（官方源・HTML 解析）",
                        "url": item["url"],
                        "title": item["title"],
                        "published": item["published"],
                        "summary": summary,
                        "narrative_topics": tag_narrative_topics(coin, item["title"], summary),
                    })
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{source['name']}: error={exc}")

    return {
        "items": items,
        "errors": errors,
        "fetched_at": now_iso(),
    }


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "news_snapshot.json"
    out_path.write_text(json.dumps({"coin": coin, **result}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    # Windows 主控台預設用 cp950，印不出「・」這類全形符號，強制 stdout 走 UTF-8。
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    with httpx.Client(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for coin in OFFICIAL_SOURCES:
            result = fetch_coin(client, coin)
            out_path = write_output(coin, result)
            print(f"[{coin}] 已寫入 {out_path}（{len(result['items'])} 筆）")
            for item in result["items"]:
                topics = "・".join(item["narrative_topics"]) or "（無命中主題）"
                print(f"  {item['source']}：{item['title']}  [{topics}]")
                if item["summary"]:
                    print(f"    摘要：{item['summary'][:120]}")
            for err in result["errors"]:
                print(f"  ⚠️ {err}")
            print()


if __name__ == "__main__":
    main()

"""新聞 collector：每幣官方發布源優先，有 RSS 用 RSS，沒有則退階抓官方頁面 HTML。
2026-07-20 起不再使用 CoinDesk／Cointelegraph／CryptoPanic 等第三方媒體聚合
（改版理由：報告要以「該幣官方怎麼說」為主，第三方聚合的角色移去 social 方向）。
"""

from __future__ import annotations

import re

import feedparser
import httpx
from bs4 import BeautifulSoup

from agent.collectors.base import BaseCollector
from agent.schemas import EvidenceDraft, LogStatus, now_iso

HTTP_TIMEOUT = 20.0
MAX_ITEMS_PER_SOURCE = 5
USER_AGENT = "hoyabit-crypto-agent/1.0"

# 每幣的官方發布源。RSS 端點已於 2026-07-20 逐一 curl 實測確認可用；
# html 端點沒有 RSS，退階解析官方頁面，CSS 結構若改版會直接失效（見對應 _scrape_*）。
OFFICIAL_SOURCES: dict[str, list[dict]] = {
    "BTC": [
        {"name": "Bitcoin Optech Newsletter", "kind": "rss", "url": "https://bitcoinops.org/feed.xml"},
        # 原本想把 Bitcoin Core 開發郵件列表當第二管道，但該列表已搬到 gnusha.org
        # public-inbox 鏡像，站方對爬蟲有 anti-bot 擋牆（"go-away" 挑戰頁），實測抓不到
        # 內容，故沒接。BTC 本身沒有單一官方實體發新聞稿，只剩這一條技術公告管道是
        # 現況的真實反映，不是漏做。
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


def _scrape_bnbchain_blog(html: str) -> list[dict]:
    """BNB Chain 官方 blog 是 Chakra UI 網站，標題文字被拆進多層 emotion-css
    包裝的 <div> 裡沒法穩定抓，改用網址 slug 還原成人類可讀標題，並在
    content_reference 裡揭露這件事，不假裝是原文標題。
    """
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
    """同一篇文章在列表頁常有兩個 <a href> 變體：一個包圖片沒有 <p> 標題，
    一個包 <p class="line-clamp-2"> 才是真標題。用 href 去重時要挑有標題的
    那個變體，不能拿到哪個就用哪個（拿到圖片版會整篇退化成印網址）。
    """
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


class NewsCollector(BaseCollector):
    name = "news_collector"
    source_type = "news"

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        sources = OFFICIAL_SOURCES.get(coin.upper(), [])
        evidences: list[EvidenceDraft] = []

        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            for source in sources:
                sub_name = source["name"].lower().replace(" ", "_")
                try:
                    resp = await client.get(source["url"])
                    resp.raise_for_status()

                    if source["kind"] == "rss":
                        parsed = feedparser.parse(resp.text)
                        for entry in parsed.entries[:MAX_ITEMS_PER_SOURCE]:
                            evidences.append(
                                EvidenceDraft(
                                    coin=coin,
                                    source=f"{source['name']}（官方源）",
                                    source_url=entry.get("link", source["url"]),
                                    fetched_at=now_iso(),
                                    content_reference=(
                                        f"標題：{entry.get('title', '')}"
                                        f"｜發布時間：{entry.get('published', '未知')}"
                                    ),
                                    related_claim=f"{coin} 官方發布新聞事件",
                                    source_type="news",
                                )
                            )
                    else:
                        for item in HTML_SCRAPERS[source["name"]](resp.text):
                            evidences.append(
                                EvidenceDraft(
                                    coin=coin,
                                    source=f"{source['name']}（官方源・HTML 解析）",
                                    source_url=item["url"],
                                    fetched_at=now_iso(),
                                    content_reference=f"標題：{item['title']}｜發布時間：{item['published']}",
                                    related_claim=f"{coin} 官方發布新聞事件",
                                    source_type="news",
                                )
                            )
                except Exception as exc:  # noqa: BLE001
                    self.log_subsource(sub_name, coin, LogStatus.ERROR, f"error={exc}")

            if not evidences:
                self.log_subsource("official_sources", coin, LogStatus.SKIPPED, "所有官方源皆未取得任何項目")

        return evidences

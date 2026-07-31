"""新聞 collector：每幣官方發布源優先，有 RSS 用 RSS，沒有則退階抓官方頁面 HTML。
2026-07-20 起不再使用 CoinDesk／Cointelegraph／CryptoPanic 等第三方媒體聚合
（改版理由：報告要以「該幣官方怎麼說」為主，第三方聚合的角色移去 social 方向）。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import feedparser
import httpx
from bs4 import BeautifulSoup

from agent.collectors.base import BaseCollector
from agent.collectors.horizon import window_back
from agent.schemas import (
    DecayPattern,
    EvidenceDraft,
    HorizonClass,
    LogStatus,
    Persistence,
    horizon_for_days,
    now_iso,
)

HTTP_TIMEOUT = 20.0
MAX_ITEMS_PER_SOURCE = 5
USER_AGENT = "hoyabit-crypto-agent/1.0"

# 對照 raw_data/_meta/window_policy.md 的 News「近 7-14 天為主」建議窗口，取
# 上緣 14 天當「非近期」判斷線。2026-07-23 實測發現 window_policy.md 原本寫的
# 「RSS feed 天然回傳近期項目、效果上落在 7-14 天內」對 HTML 解析來源不成立
# （XRP 5 篇實測跨度近 3 個月），改成不濾除、只標記，理由見
# pipeline/待辦筆記/news_日期窗口.md：低頻官方源（BTC Optech 等）若硬濾掉超窗
# 項目可能整批變空，標記比濾除更安全。
NEWS_RECENCY_WINDOW_DAYS = 14

# R8-5：主視野落在 long／structural 時放寬「非近期」判斷線與涵蓋窗聲明。
# 這幾個官方源本身沒有可調的查詢窗參數（RSS/HTML 就是回傳當下能抓到的最新
# 幾篇），實際抓取行為不變；放寬的是「多久算過期」的判斷線，避免問「過去
# 一年」時，月更頻率的官方源（如 BTC Optech）被錯誤標成全部非近期。
NEWS_LONG_RANGE_WINDOW_DAYS = 180
_LONG_RANGE_HORIZONS = frozenset({HorizonClass.LONG, HorizonClass.STRUCTURAL})

# 併自 pipeline/fetch_news.py（Step 25）：對照 02改_資料網格.html 的
# news-coin-keywords spec，每幣 3-6 個特有主題，各掛幾個英文關鍵字（官方源
# 文章多是英文）。只比對標題＋摘要的大小寫不敏感 substring，不是語意分類——
# 沒命中不代表本週沒這個敘事，只代表這批標題／摘要沒直接提到，報告措辭要
# 照這個誠實。
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

# 有些站的單篇文章頁沒設專屬 og:description，會退回網站全站通用標語（og:title
# 仍是文章專屬的，只有 description 這欄位是罐頭文字）。實測發現 Ripple Insights
# 5 篇裡有 3 篇是這句——不是文章摘要，混進比對會誤導成「這篇在講這個」，直接
# 濾掉當作沒有摘要。之後如果其他站也踩到同款罐頭文字，往這個集合加就好。
GENERIC_DESCRIPTION_FALLBACKS = {
    "ripple is the leading blockchain payments company.",
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


async def _fetch_meta_description(client: httpx.AsyncClient, url: str) -> str:
    """點進單篇文章頁抓 og:description／meta description 當內文摘要——BNB／XRP
    這兩站的本文卡在破碎的 emotion-css div 裡抓不穩，但社群分享用的 meta
    description 兩邊都有乾淨的一段文字，比硬解析內文可靠。"""
    resp = await client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for attrs in ({"property": "og:description"}, {"name": "description"}):
        tag = soup.find("meta", attrs=attrs)
        content = tag["content"].strip() if tag and tag.get("content") else ""
        if content and content.lower() not in GENERIC_DESCRIPTION_FALLBACKS:
            return content
    return ""


def _parse_rss_published(entry: dict) -> datetime | None:
    parsed = entry.get("published_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def _parse_html_published(published: str) -> datetime | None:
    """目前只有 Ripple Insights 會給出可解析的日期字串（如 "April 24, 2026"）；
    BNB Chain Blog 目前固定回傳「未知」，解析不出來直接回 None。"""
    try:
        return datetime.strptime(published, "%B %d, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _recency_note(published_dt: datetime | None, now: datetime, window_days: int = NEWS_RECENCY_WINDOW_DAYS) -> str:
    if published_dt is None:
        return "｜⚠️日期未知，無法判斷是否近期"
    age_days = (now - published_dt).days
    if age_days > window_days:
        return f"｜⚠️非近期（發布已 {age_days} 天，超過 {window_days} 天窗口）"
    return ""

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
        now = datetime.now(timezone.utc)

        # R8-5：盡力依主視野放寬「非近期」判斷線；沒傳／傳 None 時維持既有 14 天（R6-1）。
        primary_horizon = kwargs.get("primary_horizon")
        recency_window_days = (
            NEWS_LONG_RANGE_WINDOW_DAYS if primary_horizon in _LONG_RANGE_HORIZONS else NEWS_RECENCY_WINDOW_DAYS
        )
        news_horizon_class = horizon_for_days(recency_window_days)
        # 標的是「本 collector 的涵蓋窗口」，不是個別文章的發布日：超出窗口的
        # 項目不濾除、只在 content_reference 由 _recency_note() 標「非近期」（見上方註解）。
        window_start, window_end = window_back(recency_window_days, end=now.date())

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
                            recency = _recency_note(_parse_rss_published(entry), now, recency_window_days)
                            summary = strip_html(entry.get("summary", "")) if entry.get("summary") else ""
                            topics = tag_narrative_topics(coin, entry.get("title", ""), summary)
                            topics_note = f"｜特有題材：{'・'.join(topics)}" if topics else ""
                            evidences.append(
                                EvidenceDraft(
                                    coin=coin,
                                    source=f"{source['name']}（官方源）",
                                    source_url=entry.get("link", source["url"]),
                                    fetched_at=now_iso(),
                                    content_reference=(
                                        f"標題：{entry.get('title', '')}"
                                        f"｜發布時間：{entry.get('published', '未知')}"
                                        f"{recency}{topics_note}"
                                    ),
                                    related_claim=f"{coin} 官方發布新聞事件",
                                    source_type="news",
                                    window_start=window_start,
                                    window_end=window_end,
                                    horizon_class=news_horizon_class,
                                    # design.md §3.9.1 明列案例：news 官方公告 persistence=medium/slow。
                                    persistence=Persistence.MEDIUM,
                                    decay=DecayPattern.SLOW,
                                )
                            )
                    else:
                        for item in HTML_SCRAPERS[source["name"]](resp.text):
                            recency = _recency_note(_parse_html_published(item["published"]), now, recency_window_days)
                            summary = ""
                            try:
                                summary = await _fetch_meta_description(client, item["url"])
                            except Exception as exc:  # noqa: BLE001
                                self.log_subsource(f"{sub_name}_summary", coin, LogStatus.SKIPPED, f"error={exc}")
                            topics = tag_narrative_topics(coin, item["title"], summary)
                            topics_note = f"｜特有題材：{'・'.join(topics)}" if topics else ""
                            evidences.append(
                                EvidenceDraft(
                                    coin=coin,
                                    source=f"{source['name']}（官方源・HTML 解析）",
                                    source_url=item["url"],
                                    fetched_at=now_iso(),
                                    content_reference=(
                                        f"標題：{item['title']}｜發布時間：{item['published']}{recency}{topics_note}"
                                    ),
                                    related_claim=f"{coin} 官方發布新聞事件",
                                    source_type="news",
                                    window_start=window_start,
                                    window_end=window_end,
                                    horizon_class=news_horizon_class,
                                    # design.md §3.9.1 明列案例：news 官方公告 persistence=medium/slow。
                                    persistence=Persistence.MEDIUM,
                                    decay=DecayPattern.SLOW,
                                )
                            )
                except Exception as exc:  # noqa: BLE001
                    self.log_subsource(sub_name, coin, LogStatus.ERROR, f"error={exc}")

            if not evidences:
                self.log_subsource("official_sources", coin, LogStatus.SKIPPED, "所有官方源皆未取得任何項目")

        return evidences

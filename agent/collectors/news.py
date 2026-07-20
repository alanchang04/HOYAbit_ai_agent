"""新聞 collector：主要用 RSS（CoinDesk、Cointelegraph，免 key），
若使用者提供 CryptoPanic 免費 key 則額外疊加補充來源。
"""

from __future__ import annotations

import feedparser
import httpx

from agent.collectors.base import BaseCollector
from agent.collectors.coin_map import FULL_NAME_ALIASES, get_coin_info
from agent.schemas import EvidenceDraft, LogStatus, now_iso

HTTP_TIMEOUT = 20.0
MAX_ITEMS_PER_FEED = 5

RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
]


def _matches_coin(text: str, ticker: str) -> bool:
    """雙軌比對：ticker 大小寫敏感 ＋ 全名別名小寫比對。

    與 coin_map.detect_coins_in_text() 邏輯一致，避免 "eth" 誤中 "method" 等問題。
    """
    # Track 1: ticker 大小寫敏感
    if ticker in text:
        return True
    # Track 2: 全名別名大小寫不敏感
    text_lower = text.lower()
    for alias in FULL_NAME_ALIASES.get(ticker, ()):
        if alias in text_lower:
            return True
    return False


class NewsCollector(BaseCollector):
    name = "news_collector"
    source_type = "news"

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        info = get_coin_info(coin)
        evidences: list[EvidenceDraft] = []
        hit_counts: dict[str, int] = {}

        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT, headers={"User-Agent": "hoyabit-crypto-agent/1.0"}, follow_redirects=True
        ) as client:
            for feed_name, feed_url in RSS_FEEDS:
                try:
                    resp = await client.get(feed_url)
                    resp.raise_for_status()
                    parsed = feedparser.parse(resp.text)
                    matched = 0
                    for entry in parsed.entries:
                        title = entry.get("title", "")
                        summary = entry.get("summary", "")
                        if not _matches_coin(f"{title} {summary}", coin):
                            continue
                        evidences.append(
                            EvidenceDraft(
                                coin=coin,
                                source=f"{feed_name} RSS",
                                source_url=entry.get("link", feed_url),
                                fetched_at=now_iso(),
                                content_reference=f"標題：{title}｜發布時間：{entry.get('published', '未知')}",
                                related_claim=f"{coin} 相關新聞事件",
                                source_type="news",
                            )
                        )
                        hit_counts[feed_name] = hit_counts.get(feed_name, 0) + 1
                        matched += 1
                        if matched >= MAX_ITEMS_PER_FEED:
                            break
                except Exception as exc:  # noqa: BLE001
                    self.log_subsource(feed_name.lower(), coin, LogStatus.ERROR, f"error={exc}")

            if self.settings and getattr(self.settings, "cryptopanic_api_key", None):
                try:
                    resp = await client.get(
                        "https://cryptopanic.com/api/v1/posts/",
                        params={
                            "auth_token": self.settings.cryptopanic_api_key,
                            "currencies": coin,
                            "public": "true",
                        },
                    )
                    resp.raise_for_status()
                    results = resp.json().get("results", [])[:MAX_ITEMS_PER_FEED]
                    for post in results:
                        evidences.append(
                            EvidenceDraft(
                                coin=coin,
                                source="CryptoPanic（付費/補充來源，已揭露）",
                                source_url=post.get("url"),
                                fetched_at=now_iso(),
                                content_reference=f"標題：{post.get('title')}｜發布時間：{post.get('published_at')}",
                                related_claim=f"{coin} 相關新聞事件（CryptoPanic 補充）",
                                source_type="news",
                            )
                        )
                except Exception as exc:  # noqa: BLE001
                    self.log_subsource("cryptopanic", coin, LogStatus.SKIPPED, f"error={exc}")

        # 量化證據：各來源命中則數（市場關注度代理指標）
        if hit_counts:
            total_hits = sum(hit_counts.values())
            hits_detail = ", ".join(f"{name}={count}" for name, count in hit_counts.items())
            evidences.append(
                EvidenceDraft(
                    coin=coin,
                    source="新聞命中則數量化統計",
                    source_url=None,
                    fetched_at=now_iso(),
                    content_reference=f"總命中 {total_hits} 則（{hits_detail}）— 市場關注度代理指標",
                    related_claim=f"{coin} 新聞市場關注度",
                    source_type="news",
                )
            )

        return evidences

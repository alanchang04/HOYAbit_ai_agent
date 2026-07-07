"""社群情緒 collector：Reddit 公開 .json 搜尋端點（免 key，需自訂 User-Agent 避免 403）。"""

from __future__ import annotations

import httpx

from agent.collectors.base import BaseCollector
from agent.collectors.coin_map import get_coin_info
from agent.schemas import EvidenceDraft, LogStatus, now_iso

HTTP_TIMEOUT = 20.0
MAX_POSTS_PER_SUBREDDIT = 5
REDDIT_USER_AGENT = "hoyabit-crypto-agent/1.0 (hackathon research bot)"


class SocialCollector(BaseCollector):
    name = "social_collector"
    source_type = "social"

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        info = get_coin_info(coin)
        evidences: list[EvidenceDraft] = []

        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT, headers={"User-Agent": REDDIT_USER_AGENT}, follow_redirects=True
        ) as client:
            for subreddit in info.subreddits:
                url = f"https://www.reddit.com/r/{subreddit}/search.json"
                params = {"q": info.name, "restrict_sr": "1", "sort": "new", "limit": MAX_POSTS_PER_SUBREDDIT, "t": "week"}
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    posts = resp.json()["data"]["children"]
                    for post in posts:
                        p = post["data"]
                        evidences.append(
                            EvidenceDraft(
                                source=f"Reddit r/{subreddit}",
                                source_url=f"https://www.reddit.com{p.get('permalink', '')}",
                                fetched_at=now_iso(),
                                content_reference=(
                                    f"標題：{p.get('title')}｜score={p.get('score')}｜"
                                    f"留言數={p.get('num_comments')}｜發文時間戳(UTC epoch)={p.get('created_utc')}"
                                ),
                                related_claim=f"{coin} 社群討論熱度與情緒",
                                source_type="social",
                            )
                        )
                except Exception as exc:  # noqa: BLE001
                    self.log_subsource(f"reddit_{subreddit}", coin, LogStatus.ERROR, f"error={exc}")

        return evidences

"""社群情緒 collector：Reddit 搜尋。

**2026-07-28 改版**：Reddit 已全面封鎖未認證的 `.json` 端點（實測 `www`／`old`
子網域、自訂 UA 與瀏覽器 UA 一律 403），改走仍然開放的 `.rss`（Atom）端點。

代價是 RSS 不含 `score`／`num_comments`，熱度訊號降級為「近 7 天貼文則數與標題」。
若 `.env` 提供 `REDDIT_CLIENT_ID`／`REDDIT_CLIENT_SECRET`，會優先走 OAuth 取回
完整欄位（含 score／留言數）並享有較寬的額度；沒設定就自動退 RSS，不中斷。

RSS 的限流很緊：實測 header 回 `x-ratelimit-used=1, remaining=0, reset=10~20`，
即每個窗口只准一次請求。因此請求之間會依 `x-ratelimit-reset` 主動等待，
而不是硬打到被擋（那樣兩個 subreddit 會一個都拿不到）。
"""

from __future__ import annotations

import asyncio
import os
import re
from xml.etree import ElementTree

import httpx

from agent.collectors.base import BaseCollector
from agent.collectors.coin_map import get_coin_info
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
MAX_POSTS_PER_SUBREDDIT = 5
REDDIT_USER_AGENT = "hoyabit-crypto-agent/1.0 (hackathon research bot)"
# 搜尋帶 t=week，Reddit 只回近 7 天貼文 → horizon 由這個查詢參數決定性推導（ADR-2）
REDDIT_WINDOW_DAYS = 7

# R8-5：主視野落在 long／structural 時改抓 t=year，避免「過去一年」這類題目
# 只拿得到近 7 天情緒、被迫全部塞進結構脈絡帶。中間的 spot/short/medium
# 沿用既有 t=week——這三帶本來就是命題最常見的尺度，不需要新增中間層級。
REDDIT_LONG_RANGE_WINDOW_DAYS = 365
_LONG_RANGE_HORIZONS = frozenset({HorizonClass.LONG, HorizonClass.STRUCTURAL})

# 429 時最多等這麼久再重試一次。collector 預設 timeout 75 秒，兩個 subreddit
# 各等一次仍在預算內；等太久會排擠其他 collector，寧可少一則也不要拖垮整體。
RATE_LIMIT_MAX_WAIT = 20.0
# RSS 模式下兩個 subreddit 之間的主動間隔。實測不等就必吃 429（每窗口只准 1 次），
# 等了才拿得到第二個版塊。抽成常數是為了讓測試 patch 成 0，不用真的空等。
RSS_INTER_REQUEST_DELAY = 10.0
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH_SEARCH_URL = "https://oauth.reddit.com/r/{subreddit}/search"


def _search_params(query: str, t: str = "week") -> dict:
    return {
        "q": query,
        "restrict_sr": "1",
        "sort": "new",
        "limit": MAX_POSTS_PER_SUBREDDIT,
        "t": t,
    }


def parse_rss_entries(xml_text: str, limit: int = MAX_POSTS_PER_SUBREDDIT) -> list[dict]:
    """解析 Reddit Atom feed → `[{title, link, published, author}, ...]`。

    解析失敗回空 list 而非拋錯——社群是六類來源中最不關鍵的一類，
    不值得為了它中斷整個 collector（R6-1 降級優先）。
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []

    entries = []
    for entry in root.findall("a:entry", ATOM_NS)[:limit]:
        link_el = entry.find("a:link", ATOM_NS)
        author_el = entry.find("a:author/a:name", ATOM_NS)
        title_el = entry.find("a:title", ATOM_NS)
        published_el = entry.find("a:published", ATOM_NS)
        if published_el is None:
            published_el = entry.find("a:updated", ATOM_NS)
        entries.append(
            {
                "title": (title_el.text or "").strip() if title_el is not None else "",
                "link": link_el.get("href", "") if link_el is not None else "",
                "published": (published_el.text or "").strip() if published_el is not None else "",
                "author": (author_el.text or "").strip() if author_el is not None else "",
            }
        )
    return entries


def _retry_after_seconds(resp: httpx.Response) -> float:
    """從限流 header 推算該等多久，夾在 1 ~ RATE_LIMIT_MAX_WAIT 秒。"""
    raw = resp.headers.get("x-ratelimit-reset") or resp.headers.get("retry-after") or ""
    match = re.search(r"\d+(\.\d+)?", str(raw))
    seconds = float(match.group(0)) if match else RATE_LIMIT_MAX_WAIT
    return max(1.0, min(RATE_LIMIT_MAX_WAIT, seconds))


class SocialCollector(BaseCollector):
    name = "social_collector"
    source_type = "social"

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        info = get_coin_info(coin)
        evidences: list[EvidenceDraft] = []

        # R8-5：盡力依主視野調整查詢窗；沒傳／傳 None 時維持既有 t=week（R6-1）。
        primary_horizon = kwargs.get("primary_horizon")
        if primary_horizon in _LONG_RANGE_HORIZONS:
            window_days, reddit_t = REDDIT_LONG_RANGE_WINDOW_DAYS, "year"
        else:
            window_days, reddit_t = REDDIT_WINDOW_DAYS, "week"
        window_start, window_end = window_back(window_days)
        # horizon_class 必須跟著實際查詢窗重新決定性推導（ADR-2），不能沿用寫死的 SHORT。
        horizon_class = horizon_for_days(window_days)

        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT, headers={"User-Agent": REDDIT_USER_AGENT}, follow_redirects=True
        ) as client:
            token = await self._get_oauth_token(client, coin)

            for index, subreddit in enumerate(info.subreddits):
                try:
                    if token:
                        items = await self._fetch_via_oauth(client, token, subreddit, info.name, reddit_t)
                    else:
                        # RSS 每個窗口只准一次請求，第二個 subreddit 起先讓一手，
                        # 否則必定吃 429（實測連打會全滅）。
                        if index and RSS_INTER_REQUEST_DELAY > 0:
                            await asyncio.sleep(RSS_INTER_REQUEST_DELAY)
                        items = await self._fetch_via_rss(client, coin, subreddit, info.name, reddit_t)
                except Exception as exc:  # noqa: BLE001
                    self.log_subsource(f"reddit_{subreddit}", coin, LogStatus.ERROR, f"error={exc}")
                    continue

                if not items:
                    self.log_subsource(
                        f"reddit_{subreddit}", coin, LogStatus.SKIPPED, "本次無符合條件的貼文"
                    )
                    continue

                for item in items:
                    evidences.append(
                        EvidenceDraft(
                            coin=coin,
                            source=f"Reddit r/{subreddit}"
                            + ("" if token else "（RSS，未含 score／留言數）"),
                            source_url=item.get("link") or None,
                            fetched_at=now_iso(),
                            content_reference=item["summary"],
                            related_claim=f"{coin} 社群討論熱度與情緒",
                            source_type="social",
                            window_start=window_start,
                            window_end=window_end,
                            horizon_class=horizon_class,
                            # design.md §3.9.1 明列案例：social 情緒 persistence=short/fast，
                            # 社群情緒最短命，即使本次拉長查詢窗（t=year）以覆蓋主視野，
                            # 抓回來的仍是「這一年內陸續發生的當下情緒快照集合」而非單一
                            # 持久訊號，過期情緒依然不能當現況——固定不隨 horizon 改變。
                            persistence=Persistence.SHORT,
                            decay=DecayPattern.FAST,
                        )
                    )

        return evidences

    async def _get_oauth_token(self, client: httpx.AsyncClient, coin: str) -> str | None:
        """有設定 app 憑證才走 OAuth；沒有就回 None 讓呼叫端退 RSS。"""
        client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
        client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return None
        try:
            resp = await client.post(
                OAUTH_TOKEN_URL,
                auth=(client_id, client_secret),
                data={"grant_type": "client_credentials"},
            )
            resp.raise_for_status()
            token = resp.json().get("access_token")
            if token:
                self.log_subsource("reddit_oauth", coin, LogStatus.OK, "已取得 app-only token")
                return token
            return None
        except Exception as exc:  # noqa: BLE001
            self.log_subsource(
                "reddit_oauth", coin, LogStatus.SKIPPED, f"取 token 失敗，改用 RSS: {exc}"
            )
            return None

    async def _fetch_via_oauth(
        self, client: httpx.AsyncClient, token: str, subreddit: str, query: str, t: str = "week"
    ) -> list[dict]:
        resp = await client.get(
            OAUTH_SEARCH_URL.format(subreddit=subreddit),
            params=_search_params(query, t),
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        out = []
        for post in resp.json()["data"]["children"]:
            p = post["data"]
            out.append(
                {
                    "link": f"https://www.reddit.com{p.get('permalink', '')}",
                    "summary": (
                        f"標題：{p.get('title')}｜score={p.get('score')}｜"
                        f"留言數={p.get('num_comments')}｜發文時間戳(UTC epoch)={p.get('created_utc')}"
                    ),
                }
            )
        return out

    async def _fetch_via_rss(
        self, client: httpx.AsyncClient, coin: str, subreddit: str, query: str, t: str = "week"
    ) -> list[dict]:
        """免 key 路徑。429 時依 `x-ratelimit-reset` 等待後重試一次。"""
        url = f"https://www.reddit.com/r/{subreddit}/search.rss"
        resp = await client.get(url, params=_search_params(query, t))

        if resp.status_code == 429:
            wait = _retry_after_seconds(resp)
            self.log_subsource(
                f"reddit_{subreddit}", coin, LogStatus.SKIPPED, f"429 限流，等待 {wait:.0f}s 後重試"
            )
            await asyncio.sleep(wait)
            resp = await client.get(url, params=_search_params(query, t))

        resp.raise_for_status()
        return [
            {
                "link": item["link"],
                "summary": (
                    f"標題：{item['title']}｜作者={item['author'] or '未知'}｜"
                    f"發文時間={item['published'] or '未知'}"
                    "（RSS 端點不提供 score／留言數，熱度僅以貼文則數與時間分布判讀）"
                ),
            }
            for item in parse_rss_entries(resp.text)
        ]

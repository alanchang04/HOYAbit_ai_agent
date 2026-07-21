"""YT 逐字稿提及次數（層1）＋看法摘要（層2）prototype（對照 02改_資料網格.html
的 `yt-transcript` spec）。

範圍：只做 cakebaba 頻道／BTC，其他幣種還沒有對應頻道名單，先不擴（Ken
2026-07-21 拍板）。跟 `agent/collectors/` 還沒有對應模組，這裡先是
prototype，比照費率擁擠度／多空帳戶比的做法，跑出結果後再跟 alanchang
討論要不要併進 collector。

資料來源（都免 key）：
- 頻道近期影片列表：YouTube RSS feed
  （https://www.youtube.com/feeds/videos.xml?channel_id=...），用專案既有的
  feedparser 讀，不用 YouTube Data API key
- 逐字稿：youtube-transcript-api（新依賴，見 requirements.txt）

已知限制（老實記，避免後面的人以為判斷很準）：
- cakebaba 的自動字幕是簡體中文，用 opencc（s2t）先轉繁體再比對關鍵字，
  否則「比特幣」對不上字幕裡的「比特币」
- 層2 看法摘要是純關鍵字計數（看漲/看跌詞庫各 20 出頭個詞，Ken 2026-07-21
  確認方向：規則式、不占 LLM call），對「突破無力」「漲不動」這種否定/
  轉折句型會誤判——只看到「突破」會被算成看漲，但整句其實偏空。不做否定詞
  偵測，這是刻意的取捨，不是疏漏
- 頻道 RSS 只回傳「最新發布」的影片，不保證每支都提到 BTC；沒字幕/字幕
  抓取失敗的影片會標記 transcript_available=False，不計入方向判斷

用法：
    python pipeline/fetch_yt_transcript.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import feedparser
from opencc import OpenCC
from youtube_transcript_api import YouTubeTranscriptApi

CHANNELS = {
    "BTC": {"name": "cakebaba", "channel_id": "UCcMyv5UQ9dCVN2UbLhXiLWw"},
}
MAX_VIDEOS = 5

COIN_KEYWORDS = {
    "BTC": ["比特幣", "BTC", "Bitcoin"],
}

BULLISH_KEYWORDS = [
    "看漲", "看多", "做多", "偏多", "轉強", "走強", "上漲", "暴漲", "噴出",
    "突破", "站上", "止跌", "反彈", "抄底", "牛市", "牛回", "追漲", "利多",
    "看好", "樂觀", "上攻", "拉升",
]
BEARISH_KEYWORDS = [
    "看跌", "看空", "做空", "偏空", "轉弱", "走弱", "下跌", "暴跌", "崩盤",
    "跌破", "失守", "破位", "回落", "追空", "熊市", "逃頂", "利空", "看衰",
    "悲觀", "下殺", "砸盤", "M頭",
]

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "social"
_cc = OpenCC("s2t")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_recent_videos(channel_id: str, limit: int) -> list[dict]:
    feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    if not feed.entries:
        raise RuntimeError(f"RSS 沒有任何影片，可能是 channel_id 錯誤或頻道被停用：{feed.get('bozo_exception')}")
    return [
        {
            "video_id": entry.yt_videoid,
            "title": entry.title,
            "published": entry.published,
            "url": entry.link,
        }
        for entry in feed.entries[:limit]
    ]


def fetch_transcript_text(video_id: str) -> tuple[str, str] | None:
    api = YouTubeTranscriptApi()
    try:
        transcript = api.fetch(video_id, languages=["zh-Hant", "zh-TW", "zh", "zh-Hans", "en"])
    except Exception:
        return None
    text = " ".join(snippet.text for snippet in transcript)
    return _cc.convert(text), transcript.language_code


def count_keywords(text: str, keywords: list[str]) -> dict[str, int]:
    return {kw: text.count(kw) for kw in keywords if text.count(kw) > 0}


def analyze_video(video: dict, coin: str) -> dict:
    fetched = fetch_transcript_text(video["video_id"])
    if fetched is None:
        return {**video, "transcript_available": False}
    text, lang = fetched

    mention_hits = count_keywords(text, COIN_KEYWORDS[coin])
    bullish_hits = count_keywords(text, BULLISH_KEYWORDS)
    bearish_hits = count_keywords(text, BEARISH_KEYWORDS)
    bullish_count = sum(bullish_hits.values())
    bearish_count = sum(bearish_hits.values())

    if bullish_count > bearish_count:
        direction = 1
    elif bearish_count > bullish_count:
        direction = -1
    else:
        direction = 0

    return {
        **video,
        "transcript_available": True,
        "transcript_language": lang,
        "transcript_char_count": len(text),
        "coin_mention_count": sum(mention_hits.values()),
        "coin_mention_hits": mention_hits,
        "bullish_hits": bullish_hits,
        "bearish_hits": bearish_hits,
        "direction": direction,
    }


def summarize_channel(coin: str, channel: dict) -> dict:
    videos = fetch_recent_videos(channel["channel_id"], MAX_VIDEOS)
    analyzed = [analyze_video(v, coin) for v in videos]
    scored = [v for v in analyzed if v["transcript_available"]]
    total_direction = sum(v["direction"] for v in scored)

    if not scored:
        overall = "無資料"
    elif total_direction > 0:
        overall = "偏多"
    elif total_direction < 0:
        overall = "偏空"
    else:
        overall = "多空拉鋸"

    return {
        "coin": coin,
        "source": f"YouTube {channel['name']}（channel_id={channel['channel_id']}）",
        "videos_checked": len(analyzed),
        "videos_with_transcript": len(scored),
        "total_mention_count": sum(v["coin_mention_count"] for v in scored),
        "overall_direction": overall,
        "videos": analyzed,
        "fetched_at": now_iso(),
    }


def write_output(coin: str, result: dict) -> Path:
    out_path = RAW_DATA_DIR / coin / "yt_transcript_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    for coin, channel in CHANNELS.items():
        try:
            result = summarize_channel(coin, channel)
        except Exception as exc:  # noqa: BLE001
            print(f"[{coin}] 抓取失敗：{exc}")
            continue
        out_path = write_output(coin, result)
        print(f"[{coin}] 已寫入 {out_path}")
        print(f"  檢查 {result['videos_checked']} 支影片，{result['videos_with_transcript']} 支有字幕")
        print(f"  提及次數合計 {result['total_mention_count']}，整體看法 {result['overall_direction']}")
        print()


if __name__ == "__main__":
    main()

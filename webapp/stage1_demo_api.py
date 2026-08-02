"""Stage 1-5 Demo API —— 對應 13_流程圖迭代定案v2.md。

獨立於 webapp/app.py（正式 Web Demo，跑完整 Phase 1-6 pipeline）之外的示範用小型
API：
- /api/stage1：Stage 1「單一 LLM 判斷 Asset/Horizon/Research Goal」。horizon 是
  自由文字，讓 LLM 自己判斷、自己決定怎麼表達，不綁死在固定選項裡。
- /api/stage2/funding_rate、/api/stage2/active_address、/api/stage2/cpi、
  /api/stage2/liquidation、/api/stage2/panews_sentiment：Stage 2 Feature
  Extraction，五個 factor 各自真的去抓真實資料，不是同一套邏輯換個名字——五份
  `Stage 2 — Feature Extraction/*.yaml` 骨架彼此差異很大（Statistical／Event／
  Sentiment 三型都有），抓取邏輯照著各自的結構走：
    - funding_rate：Binance 永續合約 funding rate（免 key），重用
      agent/collectors/derivatives.py 已驗證過的邏輯（percentile_rank／
      crowd_label）。窗口＝天，由 LLM 依 Horizon 判斷
    - active_address：blockchain.info Charts API `n-unique-addresses`（免
      key，只支援 BTC，其他幣種直接回錯誤說明資料源限制）。窗口＝天，跟
      funding_rate 共用同一支 `_resolve_window_days_via_llm`
    - cpi：FRED 公開 CSV（`fredgraph.csv?id=CPIAUCSL`，免 key，月頻、全幣種
      通用）。窗口單位是「月」不是「天」——重用日頻窗口判斷結果再換算成月，
      不是另外設計一套月頻 LLM prompt
    - liquidation：Binance USDⓈ-M `!forceOrder@arr` WebSocket，**真的**開
      連線監聽固定秒數（不是查歷史——舊版查歷史清算單的 REST API 已停用，
      這是 Stage 2 liquidation.yaml 本身記錄的結構性限制）。percentile／
      trend／slope 等需要歷史序列的欄位這個 factor 结構性沒有，一律不產生
    - panews_sentiment：PANews 分頁端點（`universal-api.panewslab.com/articles`，
      免 key），一批一批往回翻到蓋滿 window 為止（受 PANEWS_MAX_PAGES 上限約束，
      被上限擋住時 `window_covered=false` 並在 coverage_note 講明只翻到哪天）。
      情緒分數是**簡化版關鍵字計分**，不是 NLP 模型——Stage 2 yaml 本來就記錄
      這是臨時代理；幣種比對直接 import `pipeline/fetch_media_kol_mentions.py`
      的 COIN_KEYWORDS，不另外維護第二份。⚠ window 在這個 factor 只決定「往回
      抓多深」，不是過濾邊界：超出窗口的文章標記為非近期但照樣計入
- /api/stage3/{factor_id}：Stage 3 Knowledge Layer，通用一支路由服務全部
  factor（funding_rate／active_address／cpi／liquidation／panews_sentiment）。內容讀自
  `Stage 3 — Knowledge Layer/{factor_id}.md`——Ken 手動研究、附真實學術／
  產業出處的正式版本，單一事實來源是那份 .md，這支 API 只是讀檔解析，不重複
  維護第二份副本。**刻意不打 LLM**：07/13 原文都明講 Stage 3 本身是固定
  library、不是推理層，只回答「這個 factor 是什麼」，直接讀檔回傳就好，不需要
  （也不應該）讓 LLM 介入詮釋。
- /api/stage4/funding_rate：Stage 4 Dynamic Evidence Weight Engine 的
  funding_rate 版本，對應 13 文件的兩層設計：
    - Prior Weight：真的算 `rolling_spearman_ic`（本地 CSV 價格 × Binance
      funding 歷史，spearman rank correlation 純 Python 實作，環境沒裝
      scipy/numpy），不是寫死示範值。窗口長度就是 horizon_days 本身（13 文件
      明講「不另外設 lookback_window 參數」）；公式裡的 `now` 錨定在「本地
      CSV 實際涵蓋到的最後一天」而不是今天的日曆日期——CSV 是賽事提供的靜態
      資料集（5 幣都停在同一天），funding rate 是即時抓的，兩邊時間基準一定
      要對齊，不然 forward_return 永遠配不出已實現的樣本。窗口窄時樣本數可能
      還是很小，13 拍板不設 min_sample_size 防呆，失真的 IC 交給後面排序階段
      自然淘汰
    - Dynamic Modifier：真的打一次 LLM，讀 market_regime／time_horizon_match／
      cross_source_consensus／freshness 四條線索，給一個 `[0.5, 2.0]` 的
      `context_modifier`＋理由——13 拍板的設計是「LLM 解釋給出，不套公式」。
      market_regime（FOMC 利率方向）跟 cross_source_consensus（open_interest／
      long_short_ratio 今天是否同向）這兩條線索這輪 demo 還沒接上真實資料源，
      老實標成 stub 讓 LLM 當「未知」處理，不假裝有答案
- /api/stage5：Stage 5 Evidence Card ＋ Prioritization（13 文件說這層是
  「組裝／輸出格式層」，不重新運算）。一次組裝五個 factor：直接呼叫 Stage 2/3/4
  的處理函式（不是另外發 HTTP request，同一個 process 裡直接呼叫），把 Fact／
  Knowledge／Weight 三層輸出組裝成統一格式的 Evidence Card，`evidence_weight` 取
  Stage 4 的 `final_evidence_weight`，`related_evidence` 取 Stage 3 Knowledge
  的 confirms／conflicts／independent。排序（原 Stage 6 併入）純照
  **`|evidence_weight|`（取絕對值）**由大到小——2026-08-02 Ken 拍板兩件事：
  ①**一律照權重排序**，不因 Prior Weight 來源不同（ic 回測值／impact_level 人工
  分級／Domain Knowledge 理由）而分組或另設規則，單一排序鍵就是這層的設計；
  ②比大小時**取絕對值**，因為 ic 是相關係數、負值是反向訊號不是弱訊號（實測
  BTC funding_rate ic=-0.55 是五個 factor 裡強度最高的，照帶號值排會排到最後一名）。
  代價是名次不表達方向——方向留在卡片的 `evidence_weight` 正負號與
  `weight_direction` 欄位，下游要判方向讀那兩格、不是讀名次。`evidence_coverage` 定義 13
  還沒拍板，先不產生這個欄位（不是留 null 假裝有這個概念）。算不出權重的卡片
  排最後但不刪除（13 明講「不刪除，只排序」）。
  各 factor 的卡片設計說明見 `Stage 5 — Evidence Card ＋ Prioritization/{factor}.md`。

啟動方式（在 HOYAbit_ai_agent/ 目錄下，需先啟用 .venv）：
    uvicorn webapp.stage1_demo_api:app --reload --port 8001
啟動後打開 http://127.0.0.1:8001/ 就會看到報告頁面（這支 API 直接把
14_流程圖視覺報告.html 讀出來當首頁，同源呼叫 /api/stage1，不會遇到瀏覽器 CORS 問題）。
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import csv
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import websockets
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent.collectors.derivatives import (
    FAPI_BASE,
    FUNDING_INTERVAL_HOURS,
    PERP_SYMBOL,
    crowd_label,
    percentile_rank,
)
from agent.config import get_settings
from agent.reasoning.llm_client import build_llm_client
from webapp.stage_specs import (
    build_evidence_card,
    compute_series_features,
    load_feature_spec,
    load_value_source,
    pct_change_vs_month,
    render_params,
)

# 幣種關鍵字比對規則直接沿用既有腳本那份（Stage 2 panews_sentiment.yaml 明講
# 「同一份規則」）——排除詞是實測踩過的假陽性（ETH Zurich 命中 ETH），複製第二份
# 遲早會走鐘。這支模組沒有 import 期副作用，抓取邏輯都在 main() 裡。
from pipeline.fetch_media_kol_mentions import (
    COIN_EXCLUDE_KEYWORDS as PANEWS_COIN_EXCLUDE,
    COIN_KEYWORDS as PANEWS_COIN_KEYWORDS,
)

# funding rate 每 8 小時結算一次，一天固定 3 筆
FUNDING_SAMPLES_PER_DAY = 24 // FUNDING_INTERVAL_HOURS

# LLM 判斷窗口失敗時的保守退回值（不是「換算規則」，只是讓功能不要整個掛掉）。
FALLBACK_WINDOW_DAYS = 14
# Binance /fundingRate 單次查詢上限
MAX_FUNDING_LIMIT = 1000

REPORT_HTML_NAME = "14_流程圖視覺報告.html"
# 開發位置：webapp -> HOYAbit_ai_agent -> 2026-07-雲湧智生黑客松/（vault 裡的正本，
# Ken 平常就是改這一份）
REPORT_HTML_VAULT = Path(__file__).resolve().parent.parent.parent / REPORT_HTML_NAME
# repo 內的副本：給 clone 這個 repo 的隊友／部署機用——vault 那份不在這個 repo 裡，
# 只 clone HOYAbit_ai_agent 的人拿不到它，首頁會 404
REPORT_HTML_REPO = Path(__file__).resolve().parent.parent / REPORT_HTML_NAME


def _resolve_report_html() -> Path | None:
    """決定首頁要送哪一份報告 HTML。

    順序是**先 vault 正本、後 repo 副本**：開發機上兩份都在，要送正在編輯的那份，
    不然改了畫面不會變（副本會變成看起來像 bug 的假象）；clone/部署環境只有副本。

    ⚠️ 這是刻意接受的「兩份檔案」——vault 那份是正本，repo 這份是為了讓 repo
    自己跑得起來的快照，兩邊會漂移。所以下面會在兩份都存在且內容不同時吠一聲，
    提醒副本該更新了（deploy 前沒同步，demo 機器上就會是舊畫面）。"""
    if REPORT_HTML_VAULT.exists():
        if REPORT_HTML_REPO.exists():
            try:
                if REPORT_HTML_VAULT.read_bytes() != REPORT_HTML_REPO.read_bytes():
                    print(
                        f"⚠ {REPORT_HTML_NAME}：vault 正本與 repo 副本內容不同，"
                        f"這次送的是 vault 正本。部署前記得把副本同步過去："
                        f"cp '{REPORT_HTML_VAULT}' '{REPORT_HTML_REPO}'"
                    )
            except OSError:
                pass
        return REPORT_HTML_VAULT
    if REPORT_HTML_REPO.exists():
        return REPORT_HTML_REPO
    return None

# webapp/stage1_demo_api.py -> webapp -> HOYAbit_ai_agent -> "Stage 3 — Knowledge Layer"/
KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "Stage 3 — Knowledge Layer"

# webapp/stage1_demo_api.py -> webapp -> HOYAbit_ai_agent -> "Stage 4 — Dynamic Evidence Weight Engine"/
WEIGHT_DIR = Path(__file__).resolve().parent.parent / "Stage 4 — Dynamic Evidence Weight Engine"

# webapp/stage1_demo_api.py -> webapp -> HOYAbit_ai_agent -> "Stage 2 — Feature Extraction"/
FEATURE_DIR = Path(__file__).resolve().parent.parent / "Stage 2 — Feature Extraction"

# webapp/stage1_demo_api.py -> webapp -> HOYAbit_ai_agent -> "Stage 5 — Evidence Card ＋ Prioritization"/
CARD_DIR = Path(__file__).resolve().parent.parent / "Stage 5 — Evidence Card ＋ Prioritization"

# webapp/stage1_demo_api.py -> webapp -> HOYAbit_ai_agent -> data/
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

KNOWN_FACTORS = ["funding_rate", "active_address", "cpi", "liquidation", "panews_sentiment", "etf"]


# 學術出處的識別碼 → 可點擊的網址
_ACADEMIC_URL = {
    "doi": lambda v: f"https://doi.org/{v}",
    "arxiv": lambda v: f"https://arxiv.org/abs/{v}",
    "ssrn": lambda v: f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={v}",
}
_ACADEMIC_LINE = re.compile(r'^\s*-\s*(doi|arxiv|ssrn)\s*:\s*"?([^"#]+?)"?\s*(?:#\s*(.*))?$')
# 產業出處寫成「發布者 - 標題: 網址」一整串，用最後一個「: http」切開標題與網址
_INDUSTRY_LINE = re.compile(r"^(.*):\s*(https?://\S+)$")


def _academic_notes(yaml_text: str) -> dict[str, str]:
    """把 references.academic 每一筆的**行末註解**抓出來當說明。

    那些註解就是分析師寫的「這篇是什麼、為什麼收錄」（例如作者、期刊、關鍵
    發現），但 `yaml.safe_load` 會把註解整個丟掉，所以另外掃一次原始文字取回，
    前端才有東西可以標示「這個連結是做什麼的」。格式若跑掉就退回沒有說明，
    不會讓整份知識庫載入失敗。"""
    notes: dict[str, str] = {}
    in_academic = False
    for line in yaml_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("academic:"):
            in_academic = True
            continue
        if in_academic:
            # 離開 academic 區塊：碰到同層級的其他 key（例如 industry:／note:）
            if stripped and not stripped.startswith("-"):
                break
            m = _ACADEMIC_LINE.match(line)
            if m and m.group(3):
                notes[m.group(2).strip()] = m.group(3).strip()
    return notes


def _enrich_references(knowledge: dict, yaml_text: str) -> None:
    """就地把 references 補上 `url`／`label`，讓前端不用再顯示一長串生網址。
    內容本身完全來自 .md，這裡只是重新整理成好呈現的形狀，沒有新增資訊。"""
    refs = knowledge.get("references")
    if not isinstance(refs, dict):
        return

    notes = _academic_notes(yaml_text)
    enriched_academic = []
    for entry in refs.get("academic") or []:
        if not isinstance(entry, dict):
            continue
        kind = next((k for k in _ACADEMIC_URL if k in entry), None)
        if kind is None:
            continue
        ident = str(entry[kind]).strip()
        enriched_academic.append({
            "kind": kind,
            "id": ident,
            "url": _ACADEMIC_URL[kind](ident),
            # 找不到註解時 label 退回識別碼本身，不硬編一個描述
            "label": notes.get(ident) or f"{kind.upper()} {ident}",
        })
    refs["academic"] = enriched_academic

    enriched_industry = []
    for entry in refs.get("industry") or []:
        if not isinstance(entry, str):
            continue
        m = _INDUSTRY_LINE.match(entry.strip())
        if m:
            enriched_industry.append({"label": m.group(1).strip(), "url": m.group(2)})
        else:
            enriched_industry.append({"label": entry.strip(), "url": None})
    refs["industry"] = enriched_industry


def _load_knowledge_md(factor_id: str) -> dict:
    """讀 `Stage 3 — Knowledge Layer/{factor_id}.md` 裡的 yaml 區塊。這幾份
    手動研究、附真實學術／產業出處的版本是 Ken 拍板要用的正式內容，單一事實
    來源是這些 .md 檔案，這裡只是讀出來解析，不重複維護第二份副本。"""
    path = KNOWLEDGE_DIR / f"{factor_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"找不到知識庫檔案：{path}")
    text = path.read_text(encoding="utf-8")
    match = re.search(r"```yaml\n(.*?)\n```", text, re.DOTALL)
    if not match:
        raise RuntimeError(f"{path} 找不到 yaml 區塊")
    yaml_text = match.group(1)
    knowledge = yaml.safe_load(yaml_text)["knowledge"]
    _enrich_references(knowledge, yaml_text)
    return knowledge


def _load_funding_rate_knowledge() -> dict:
    """Stage 4/5 目前只示範 funding_rate，保留這個具名包裝方便閱讀呼叫端。"""
    return _load_knowledge_md("funding_rate")


def _load_weight_md(factor_id: str) -> dict | None:
    """讀 `Stage 4 — Dynamic Evidence Weight Engine/{factor_id}.md` 的 yaml
    區塊。跟 Stage 3 一樣，這些 .md 是 Ken 拍板的單一事實來源，程式只負責讀，
    不在程式碼裡另外發明一套權重規則。

    沒有對應檔案時回 None——代表這個 factor 走預設的 Statistical 路徑
    （現場算 rolling_spearman_ic），例如 funding_rate。"""
    path = WEIGHT_DIR / f"{factor_id}.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    match = re.search(r"```yaml\n(.*?)\n```", text, re.DOTALL)
    if not match:
        return None
    parsed = yaml.safe_load(match.group(1))
    return (parsed or {}).get("weight")


def _load_price_series(coin: str) -> dict[str, float]:
    """讀本地 5 年 Daily OHLCV CSV（data/{coin}_daily_ohlcv.csv），回傳
    date(YYYY-MM-DD) -> close 的字典，供 rolling_spearman_ic 算 forward return
    用——零網路成本，不用另外打 API（07 文件 Round 4 講的「Price 技術面吃本地
    免費長窗口」）。"""
    path = DATA_DIR / f"{coin}_daily_ohlcv.csv"
    if not path.exists():
        raise FileNotFoundError(f"找不到本地價格資料：{path}")
    prices: dict[str, float] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            prices[row["date"]] = float(row["close"])
    return prices


def _spearman_corr(xs: list[float], ys: list[float]) -> float | None:
    """純 Python 實作 Spearman rank correlation（環境沒裝 scipy/numpy）：兩序列
    各自排名（同值取平均名次）後算 Pearson correlation，等價於 Spearman。"""
    n = len(xs)
    if n < 2:
        return None

    def _ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg_rank
            i = j + 1
        return ranks

    rx, ry = _ranks(xs), _ranks(ys)
    mean_rx, mean_ry = sum(rx) / n, sum(ry) / n
    cov = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry))
    var_x = sum((a - mean_rx) ** 2 for a in rx)
    var_y = sum((b - mean_ry) ** 2 for b in ry)
    if var_x == 0 or var_y == 0:
        return None
    return cov / (var_x * var_y) ** 0.5


def _resolve_ic_anchor_date(coin: str) -> str:
    """rolling_spearman_ic 需要 forward_return 已經『走完』，但本地 CSV 是賽事
    提供的靜態資料集（五幣都停在同一天，不是即時更新），funding rate 卻是即時
    抓的——直接拿『今天』當 now，t+horizon 幾乎必然落在 CSV 涵蓋範圍之外，
    永遠配不出樣本（這是改用 anchor 之前實測發現的問題，不是 lookback window
    給得不夠長）。這裡把公式裡的 now 錨定在『本地 CSV 實際涵蓋到的最後一天』，
    funding rate 也跟著抓那個日期附近的歷史區間，兩邊時間基準才會對齊。"""
    prices = _load_price_series(coin)
    if not prices:
        raise RuntimeError(f"{coin} 本地價格資料是空的")
    return max(prices)


async def _fetch_funding_history_before(symbol: str, anchor_date: str, horizon_days: int) -> list[dict]:
    """抓 [anchor_date - 2×horizon_days, anchor_date] 這段歷史 funding rate，
    用 startTime/endTime 錨定在 anchor_date（＝本地 CSV 最後一天），不是抓
    『最近 N 筆』——那會錨在今天，跟停在幾個月前的本地價格對不上。多抓一倍
    天數的理由跟原本一樣：t 必須落在 anchor_date 之前至少 horizon_days 天，
    forward_return(t, t+horizon) 才有已實現的價格可用。"""
    anchor_dt = datetime.strptime(anchor_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_dt = anchor_dt - timedelta(days=horizon_days * 2)
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{FAPI_BASE}/fundingRate",
            params={
                "symbol": symbol,
                "startTime": int(start_dt.timestamp() * 1000),
                "endTime": int(anchor_dt.timestamp() * 1000),
                "limit": MAX_FUNDING_LIMIT,
            },
        )
        resp.raise_for_status()
        return resp.json()


def _daily_funding_series(rows: list[dict]) -> dict[str, float]:
    """把每 8 小時一筆的 funding rate 依日期分組取平均，跟本地 CSV 的日頻價格
    對齊，才能配對算 forward return。"""
    buckets: dict[str, list[float]] = {}
    for r in rows:
        day = datetime.fromtimestamp(int(r["fundingTime"]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        buckets.setdefault(day, []).append(float(r["fundingRate"]))
    return {day: sum(vals) / len(vals) for day, vals in buckets.items()}


def _compute_rolling_spearman_ic(
    coin: str, horizon_days: int, anchor_date: str, funding_daily: dict[str, float]
) -> dict:
    """13 文件定義的 rolling_spearman_ic：
        IC(horizon) = spearman_corr(factor_value(t), forward_return(t, t+horizon))
        for t in [now-horizon, now]

    公式裡的 `now` 錨定在 `_resolve_ic_anchor_date()` 算出來的日期（本地 CSV
    實際涵蓋到的最後一天），不是今天的日曆日期——本地 CSV 是賽事提供的靜態
    資料集，funding rate 卻是即時抓的，兩邊時間基準沒對齊的話，t+horizon
    幾乎必然落在 CSV 涵蓋範圍之外，樣本數會結構性等於 0（這是改用 anchor
    之前實測發現的問題）。`_fetch_funding_history_before()` 已經照這個 anchor
    多抓一倍天數的歷史 funding 資料備好，這裡只要對齊配對就好。窗口長度仍然
    是 horizon_days，只是 now 的定義從「今天」改成「本地資料實際能驗證到的
    最後一天」。13 文件拍板不設 min_sample_size 防呆：樣本太少導致的失真 IC，
    留給後面 Stage 5/6 排序時自然淘汰，這裡不提前擋。"""
    prices = _load_price_series(coin)
    price_dates = sorted(prices)
    date_to_idx = {d: i for i, d in enumerate(price_dates)}

    factor_values: list[float] = []
    forward_returns: list[float] = []
    for day in sorted(funding_daily):
        idx = date_to_idx.get(day)
        if idx is None:
            continue
        target_idx = idx + horizon_days
        if target_idx >= len(price_dates):
            continue
        base_price = prices[day]
        if base_price == 0:
            continue
        forward_return = (prices[price_dates[target_idx]] - base_price) / base_price
        factor_values.append(funding_daily[day])
        forward_returns.append(forward_return)

    ic = _spearman_corr(factor_values, forward_returns)
    sample_size = len(factor_values)
    if sample_size == 0:
        note = (
            f"樣本數＝0：now 已經錨定在本地 CSV 最後一天（{anchor_date}），還是配不出任何一組"
            "『t 與 t+horizon 都有價格』的樣本——通常代表 horizon 太長，往前推 2×horizon_days 已經"
            "超出本地 CSV 的涵蓋範圍（CSV 只有 5 年）。這裡照實回報 0，不偷偷再放大窗口去湊數字。"
        )
    else:
        note = (
            f"now 錨定在本地 CSV 最後一天（{anchor_date}，不是今天的日曆日期——CSV 是賽事提供的靜態"
            f"資料集），t 落在 {anchor_date} 往前 {horizon_days}~{horizon_days * 2} 天這段窗口"
            "（forward_return 到 anchor_date 已經走完）。樣本數小的話 IC 本身會不穩定，13 文件刻意"
            "不設 min_sample_size 防呆，交給後面排序階段自然淘汰失真訊號，這裡如實回報 sample_size "
            "讓人自行判斷。"
        )
    return {
        "algorithm": "rolling_spearman_ic",
        "ic": ic,
        "sample_size": sample_size,
        "input_horizon_days": horizon_days,
        "anchor_date": anchor_date,
        "note": note,
    }

app = FastAPI(title="Stage 1 Demo API")

# 保留 CORS 是為了防呆：如果之後改成用瀏覽器直接開 14_流程圖視覺報告.html（file://）
# 呼叫這支 API，同源限制會擋掉請求，開著 CORS 才不會莫名其妙打不通。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Execution Log ----------
# 命題文件把 `execution_log.jsonl` 列為交付項目之一（「每一步驟的執行紀錄」）。
# 正式 pipeline 走 `agent/logging_utils.ExecutionLogger` 寫檔；這支 demo API 是
# 無狀態的、一個 stage 一個 HTTP 端點，沒有「一次執行」的檔案可寫，所以改成
# **每個請求各自收集、隨回應一起回傳**，前端跨 stage 累積後統一呈現並可下載成
# 同格式的 .jsonl。欄位刻意對齊 `agent/schemas.LogEntry`（ts／phase／action／
# detail／status／layer／metrics），這樣兩邊的紀錄是同一種東西、可以並排比對。
#
# 用 contextvars 而不是傳參數：stage5 會在同一個 async 呼叫樹裡跑 asyncio.gather
# 併發呼叫五個 factor 的 stage2/3/4，逐層傳 logger 要改動十幾個函式簽名；
# contextvar 在 asyncio 下每個 task 自帶副本，天然安全。
_run_log: contextvars.ContextVar[list | None] = contextvars.ContextVar("demo_run_log", default=None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(
    action: str,
    detail: str = "",
    status: str = "ok",
    phase: str = "collect",
    layer: str | None = None,
    metrics: dict | None = None,
) -> None:
    """記一筆執行紀錄。沒有在 `_capture_log()` 區塊裡時靜默略過（單獨呼叫某個
    helper 做測試時不該因為沒有 log 容器就爆掉）。"""
    entries = _run_log.get()
    if entries is None:
        return
    entries.append(
        {
            "ts": _now_iso(),
            "phase": phase,
            "action": action,
            "detail": detail,
            "status": status,
            "layer": layer,
            "metrics": metrics or {},
        }
    )


@contextlib.contextmanager
def _capture_log():
    """開一個收集區塊；離開時還原，避免污染其他請求。

    **巢狀時沿用外層那一份**：`/api/stage6` 內部會直接呼叫 `stage5_all()`
    （同一個 process，不是再發一次 HTTP），若兩層各開一份，Stage 2-5 的紀錄
    會留在內層那份、跟著 stage5 的回應被丟掉，stage6 的 log 只剩下建圖那幾行。
    合併成同一條時間軸才看得出「這次查詢從頭到尾做了什麼」。
    """
    existing = _run_log.get()
    if existing is not None:
        yield existing
        return
    entries: list = []
    token = _run_log.set(entries)
    try:
        yield entries
    finally:
        _run_log.reset(token)


@contextlib.contextmanager
def _timed(action: str, detail: str = "", phase: str = "collect", layer: str | None = None):
    """量一段工作的耗時並記錄；拋例外時記成 error 再往上拋（不吞例外）。

    耗時是 execution log 最有價值的欄位之一——命題有 15 分鐘硬性上限，
    「哪一層吃掉多少秒」是事後檢討與現場判斷要不要降級的依據。
    """
    started = time.monotonic()
    try:
        yield
    except BaseException as exc:  # noqa: BLE001 - 記錄後原樣拋出
        _log(
            action,
            f"{detail}｜失敗：{type(exc).__name__}: {exc}" if detail else f"失敗：{type(exc).__name__}: {exc}",
            status="error",
            phase=phase,
            layer=layer,
            metrics={"elapsed_ms": round((time.monotonic() - started) * 1000)},
        )
        raise
    else:
        _log(
            action,
            detail,
            phase=phase,
            layer=layer,
            metrics={"elapsed_ms": round((time.monotonic() - started) * 1000)},
        )

SYSTEM_PROMPT = """你是加密貨幣研究助理的 Query Understanding 模組。
針對使用者輸入的自然語言問題，用「同一次」判斷抽取三個欄位——這三個欄位是同一次
LLM 判斷的產物，不是三次獨立呼叫：

- asset：問題涉及的幣種代號陣列（可能的值：BTC、ETH、SOL、BNB、XRP）。題目沒明確
  提到幣種時，選最相關的一個並在 reasoning 註明是推測
- horizon：這個問題適合的分析時間尺度。自己判斷、自己決定怎麼表達，不限定於固定
  選項或固定格式——可以是「3天」「2週」「6個月」「1年」，也可以直接寫天數，
  依問題內容判斷最貼切的講法，不要被少數幾個預設桶綁住
- research_goal：這個問題屬於哪一種研究目標，只能是以下三選一：Trend（趨勢判斷）、
  Event（事件驅動）、Risk（風險評估）

只輸出一個 JSON 物件，不要有任何 JSON 以外的文字或 markdown code fence：
{"asset": ["BTC"], "horizon": "2週", "research_goal": "Trend", "reasoning": "一句話說明判斷依據"}
"""

# 每個 factor 的資料頻率／特性都不一樣，窗口判斷的背景知識必須跟著換——共用一份
# 寫死 funding_rate 的 prompt 會讓 LLM 幫 active_address／cpi 判斷時講出「funding
# rate 週期性變化」這種驢頭不對馬嘴的理由（這是實際踩到的 bug，不是假設性風險）。
FACTOR_WINDOW_CONTEXT = {
    "funding_rate": (
        "- 資料頻率：永續合約資金費率每 8 小時結算一次（一天固定 3 筆）\n"
        "- 這個 factor 反映的是槓桿倉位的擁擠程度，訊號衰減快，狀態常在數日內反轉\n"
        "- 窗口太短：樣本太少，Percentile／Trend 容易被單一次極端結算值主導\n"
        "- 窗口太長：把早就平倉的舊擁擠狀態算進來，稀釋掉當下的倉位結構"
    ),
    "active_address": (
        "- 資料頻率：鏈上每日活躍地址數，一天一筆（blockchain.info）\n"
        "- 這個 factor 反映的是網路實際使用量的結構性趨勢，不是短線 timing 訊號；\n"
        "  近期研究指出 ETF／機構化之後價格與鏈上使用量會脫鉤，訊號延續性比早年弱\n"
        "- 資料本身有「當日尚未收斂、隔天補齊」的 revision 現象，最新一兩筆可能被修正\n"
        "- 窗口太短：單日跳動與 revision 雜訊會蓋過真正的使用量趨勢\n"
        "- 窗口太長：把上一個市場週期的使用量水準算進來，Percentile 會失去當期意義"
    ),
    "cpi": (
        "- 資料頻率：美國 CPI 是**月頻**，一個月一筆（FRED CPIAUCSL），且公布時間\n"
        "  落後參考月份約一個月\n"
        "- 這個 factor 是總經系統性因子，全幣種同時適用，不是逐幣種的市場微結構訊號\n"
        "- 它有雙重時間尺度：公布當下的即時衝擊（數日），以及透過 Fed 政策預期影響\n"
        "  流動性環境（數週到數月）\n"
        "- 注意：你回答的 window_days 之後會被換算成「幾個月」（除以 30 四捨五入），\n"
        "  所以給天數時要意識到最終落到月頻上會變成多少筆樣本——例如 90 天只有 3 筆，\n"
        "  對 Percentile 來說可能太少"
    ),
    "panews_sentiment": (
        "- 資料頻率：中文加密媒體報導，準即時（快訊近乎即時，深度文章數小時到數天一篇），\n"
        "  單日相符文章數可能從個位數到數十篇不等\n"
        "- 這個 factor 反映的是媒體敘事情緒，學術實證指出它的預測力是**狀態依存**的：\n"
        "  在恐懼／貪婪極端狀態下較顯著，正常狀態下對大市值資產（如 BTC）較弱\n"
        "- ⚠️ 這裡的 window 只決定「預設往回抓多深」，不是硬性過濾邊界：超出窗口的文章\n"
        "  會被標記為非近期但照樣保留計入。所以窗口給長一點的代價只是多抓幾頁，\n"
        "  給太短的代價卻是整段敘事脈絡看不到——判斷時可以偏寬鬆一些\n"
        "- 窗口太短：樣本篇數太少，情緒均值容易被單一則爆炸性新聞主導\n"
        "- 窗口太長：把上一輪行情的敘事情緒混進來，稀釋掉當下的媒體氛圍"
    ),
    "etf": (
        "- 資料頻率：美國現貨 BTC ETF 逐日淨流量，一天一筆（bitbo.io，免key）\n"
        "- ⚠️ 資料源天花板：這個免費頁面只給近 9-10 個交易日＋統計列，沒有多年歷史——\n"
        "  不管你判斷出多長的 window，實際能用到的資料都被這個上限卡住，這不是\n"
        "  你判斷錯誤，是資料源本身的限制\n"
        "- 這個 factor 反映機構資金透過 ETF 申購/贖回管道的流向，學術實證顯示\n"
        "  它跟價格是**雙向回饋迴圈**（flows 造成 returns，returns 也造成 flows），\n"
        "  不是單純的領先指標\n"
        "- 窗口太短：樣本點太少，Trend 容易被單一天的極端流量主導（例如單日反轉 $300M+）\n"
        "- 窗口太長：反正也拿不到，資料源給多少就是多少"
    ),
}

WINDOW_SYSTEM_PROMPT_TEMPLATE = """你是加密貨幣分析 pipeline 的 Stage 2 Feature Extraction 模組。
任務：根據使用者這次查詢的分析 Horizon（自由文字，可能是「3天」「6個月」等任意
表達方式，不是固定選項），自己判斷、自己思考要抓多少天的歷史 **{factor_id}** 資料，
用來計算 Percentile（相對歷史的位置）跟 Trend（近期方向）這兩個特徵。

這個 factor 的背景知識（不同 factor 特性不同，請只依據以下這幾條判斷，不要套用
其他 factor 的常識）：
{factor_context}
- Horizon 是自由文字，先自己理解它大概對應多長的時間，再判斷合理的抓取天數

理由請針對「{factor_id} 這個 factor」寫，不要提到其他 factor 的名字或特性。

只輸出一個 JSON 物件，不要有任何 JSON 以外的文字或 markdown code fence：
{{"window_days": 14, "reasoning": "一句話說明為什麼選這個天數"}}
"""


def _window_system_prompt(factor_id: str) -> str:
    return WINDOW_SYSTEM_PROMPT_TEMPLATE.format(
        factor_id=factor_id,
        factor_context=FACTOR_WINDOW_CONTEXT.get(factor_id, "- （這個 factor 沒有額外背景知識，依一般統計特徵判斷即可）"),
    )


# Stage 4 的 horizon_days 跟 Stage 2 的抓取窗口是兩件不同的事：Stage 2 問的是
# 「要抓多少歷史來算 percentile／trend」（逐 factor 不同，看資料頻率），Stage 4
# 的 horizon 是 IC 公式裡 forward_return 要往前看多久（＝這次查詢的分析期間本身，
# 跟哪個 factor 無關）。所以這裡用一支中性的換算 prompt，不借用某個 factor 的
# 抓取窗口當 IC horizon。
HORIZON_DAYS_SYSTEM_PROMPT = """你的任務只有一件事：把一段自由文字描述的分析時間尺度，換算成天數。

例如「兩週」→14、「3個月」→90、「一年」→365、「5天」→5。
這純粹是時間單位換算，跟任何金融指標、資料頻率都無關，不要加入其他考量。

只輸出一個 JSON 物件，不要有任何 JSON 以外的文字或 markdown code fence：
{"horizon_days": 14, "reasoning": "一句話說明換算依據"}
"""


async def _resolve_horizon_days_via_llm(horizon: str | None) -> tuple[int, str]:
    """把 Stage 1 給的自由文字 Horizon 換算成天數，供 Stage 4 的 IC 公式用。
    回傳 (days, source)，source 是 "llm" 或 "fallback"。"""
    if not horizon:
        return FALLBACK_WINDOW_DAYS, "fallback（Horizon 未提供）"
    settings = get_settings()
    try:
        client = build_llm_client(settings)
        raw = await asyncio.to_thread(
            client.converse, HORIZON_DAYS_SYSTEM_PROMPT, f"Horizon: {horizon}", 200
        )
        days = int(_extract_json(raw)["horizon_days"])
        if days < 1:
            raise ValueError(f"horizon_days 不合理：{days}")
        return days, "llm"
    except Exception as exc:  # noqa: BLE001
        return FALLBACK_WINDOW_DAYS, f"fallback（換算失敗，非 LLM 判斷）：{exc}"

STAGE4_MODIFIER_SYSTEM_PROMPT = """你是加密貨幣分析 pipeline 的 Stage 4 Dynamic Evidence Weight Engine 模組。
任務：根據下面四條線索，給出一個 [0.5, 2.0] 區間的 context_modifier 數字
（1.0＝中性），不要套加權公式逐項計算，直接綜合判斷後給一個數字＋理由——這是
13 文件拍板的設計：LLM 解釋給出，不是公式加總。

四條線索：
1. market_regime：目前的總經利率環境（rate_cutting／rate_hiking／rate_hold）
2. time_horizon_match：這次查詢的 Horizon，跟 funding_rate 這個 factor 擅長的
   Primary Horizon 接近程度——越接近應該調高，差越多應該調低
3. cross_source_consensus：跟 funding_rate 相關的其他訊號（open_interest／
   long_short_ratio）今天是否同向
4. freshness：資料時間戳距離現在多久

重要：如果某條線索被標示為「尚未接上真實資料源」，不要假裝有答案、不要自己編一
個合理的數字或方向——把那條線索當作「未知，不加分也不扣分」處理，並在理由裡
明講哪些線索是真數據、哪些是缺資料的中性假設，讓看的人清楚知道這個 modifier
有多少是真的算出來的、多少是保守假設。

只輸出一個 JSON 物件，不要有任何 JSON 以外的文字或 markdown code fence：
{"context_modifier": 1.0, "reasoning": "..."}
"""


class Stage1Request(BaseModel):
    query: str


class Stage2FundingRequest(BaseModel):
    coin: str
    horizon: str | None = None


class Stage4FundingRequest(BaseModel):
    coin: str
    horizon: str | None = None
    horizon_days: int | None = None


class Stage5FundingRequest(BaseModel):
    coin: str
    horizon: str | None = None
    horizon_days: int | None = None


def _extract_json(text: str) -> dict:
    """LLM 有時仍會夾 ```json 圍欄或前後贅字，這裡盡量把 JSON 物件挖出來。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"回應內容找不到 JSON 物件：{text[:200]}")
    return json.loads(match.group(0))


@app.get("/")
def index():
    report_path = _resolve_report_html()
    if report_path is None:
        raise HTTPException(
            404,
            f"找不到報告檔案，兩個位置都沒有：{REPORT_HTML_VAULT}（vault 正本）／"
            f"{REPORT_HTML_REPO}（repo 副本）",
        )
    # 這頁在開發階段會一直改，瀏覽器快取住舊版會讓人以為「改了沒生效」
    # （實際踩過：畫面停在改版前的 Stage 4 單一 factor 版面）。demo 用途不需要
    # 快取，直接關掉，每次重整都拿最新檔案。
    return FileResponse(report_path, headers={"Cache-Control": "no-store, must-revalidate"})


@app.post("/api/stage1")
def stage1(req: Stage1Request):
    query = req.query.strip()
    if not query:
        raise HTTPException(400, "問題不能是空的")

    with _capture_log() as run_log:
        settings = get_settings()
        _log(
            "stage1_received",
            f"query 長度 {len(query)} 字，backend={settings.llm_backend}",
            phase="collect",
            layer="S1_query_understanding",
        )
        try:
            client = build_llm_client(settings)
        except Exception as exc:  # noqa: BLE001
            _log("llm_client_init", f"失敗：{exc}", status="error", layer="S1_query_understanding")
            raise HTTPException(
                500, f"LLM client 初始化失敗（backend={settings.llm_backend}）：{exc}"
            ) from exc

        try:
            with _timed(
                "stage1_llm_judgment",
                "單一 LLM 呼叫判斷 Asset／Horizon／Research Goal",
                phase="reason",
                layer="S1_query_understanding",
            ):
                raw = client.converse(SYSTEM_PROMPT, query, max_tokens=1024)
                result = _extract_json(raw)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                502,
                f"LLM 呼叫或解析失敗（backend={settings.llm_backend}）：{exc}。"
                f"若 backend=bedrock，常見原因是 AWS_SESSION_TOKEN 過期，需要重新產生。",
            ) from exc

        _log(
            "stage1_resolved",
            f"asset={result.get('asset')}, horizon={result.get('horizon')}, "
            f"goal={result.get('research_goal')}",
            phase="reason",
            layer="S1_query_understanding",
        )

        return {
            "query": query,
            "backend": settings.llm_backend,
            "asset": result.get("asset"),
            "horizon": result.get("horizon"),
            "research_goal": result.get("research_goal"),
            "reasoning": result.get("reasoning"),
            "execution_log": run_log,
        }


async def _resolve_window_days_via_llm(horizon: str | None, factor_id: str) -> tuple[int, str, str]:
    """真的打一次 LLM，讓它依 Horizon 判斷窗口天數——這是 13 原文「窗口由 LLM
    依 Horizon 決定」的核心，不是查表。回傳 (window_days, reasoning, source)，
    source 是 "llm" 或 "fallback"（LLM 呼叫/解析失敗時才會是 fallback，且
    reasoning 會如實說明失敗原因，不偽裝成 LLM 判斷）。"""
    settings = get_settings()
    user_prompt = f"Horizon: {horizon}" if horizon else "Horizon: 未提供，請給一個保守通用的天數"
    try:
        client = build_llm_client(settings)
        # client.converse 是同步呼叫（boto3／google-genai 都是阻塞式 I/O），
        # 丟進 thread 執行才不會卡住這支 async endpoint 的 event loop。
        raw = await asyncio.to_thread(
            client.converse, _window_system_prompt(factor_id), user_prompt, 256
        )
        result = _extract_json(raw)
        days = int(result["window_days"])
        if days < 1:
            raise ValueError(f"window_days 不合理：{days}")
        return days, str(result.get("reasoning", "")), "llm"
    except Exception as exc:  # noqa: BLE001
        return (
            FALLBACK_WINDOW_DAYS,
            f"LLM 窗口判斷失敗，退回保守預設值 {FALLBACK_WINDOW_DAYS} 天（非 LLM 判斷）：{exc}",
            "fallback",
        )


async def _resolve_effective_horizon_days(horizon: str | None, explicit_days: int | None) -> tuple[int, str]:
    """決定 Stage 4 IC 與 time_horizon_match 要用的分析期間（天）。
    呼叫端有明確給就用它；沒給就用中性 prompt 把自由文字 Horizon 換算成天數——
    不能直接退回 FALLBACK_WINDOW_DAYS，那會讓「問一年」跟「問兩週」算出同一個
    horizon_days，time_horizon_match 就永遠比對錯的數字（實際踩過這個 bug）。"""
    if explicit_days and explicit_days > 0:
        return explicit_days, "caller"
    return await _resolve_horizon_days_via_llm(horizon)


def _series_trend(rates: list[float]) -> str:
    """把整段抓到的序列對半切，比較前半／後半平均值判斷趨勢方向（不是嚴謹統計
    檢定，只用來對應 Stage 2 schema 的 Trend 欄位示範）。刻意不用固定天數窗口，
    因為抓取窗口本身已經隨 Horizon 變動，trend 判斷要跟著同一段窗口走，不能假設
    窗口一定有 7 天。通用函式，funding_rate／active_address 共用。"""
    if len(rates) < 4:
        return "資料不足以判斷趨勢"
    mid = len(rates) // 2
    prior, recent = rates[:mid], rates[mid:]
    prior_avg = sum(prior) / len(prior)
    recent_avg = sum(recent) / len(recent)
    if recent_avg > prior_avg:
        return "Increasing"
    if recent_avg < prior_avg:
        return "Decreasing"
    return "Flat"


@app.post("/api/stage2/funding_rate")
async def stage2_funding_rate(req: Stage2FundingRequest):
    """Stage 2 Feature Extraction 的 funding_rate 版本：真的去抓 Binance 資料。
    抓取窗口由 LLM 依傳入的 horizon（來自 Stage 1 判斷）現場判斷天數，不是查表。

    端點、查詢參數、要算哪些欄位**全部讀自 `Stage 2 — Feature Extraction/funding_rate.yaml`**
    （跟 Stage 3/4 讀 .md 同一個模式：規格檔是單一事實來源，程式只負責讀）。
    yaml 的 `{window * 3}` 樣板就是「窗口天數 × 每天 3 筆結算」的換算。"""
    coin = req.coin.upper()
    symbol = PERP_SYMBOL.get(coin)
    if symbol is None:
        raise HTTPException(400, f"不支援的幣種：{coin}（支援：{', '.join(PERP_SYMBOL)}）")

    spec = load_feature_spec("funding_rate")
    window_days, window_reasoning, window_source = await _resolve_window_days_via_llm(req.horizon, "funding_rate")
    samples_per_day = int(spec.get("samples_per_day", FUNDING_SAMPLES_PER_DAY))
    params = render_params(spec["params"], symbol=symbol, window_days=window_days)
    # Binance 單次查詢上限 1000 筆，窗口很長時把 yaml 算出來的 limit 夾住
    params["limit"] = str(min(max(int(params["limit"]), samples_per_day), MAX_FUNDING_LIMIT))

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.get(spec["endpoint"], params=params)
            resp.raise_for_status()
            rows = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Binance funding rate 抓取失敗：{exc}") from exc

    if not rows:
        raise HTTPException(502, "Binance 回傳空序列")

    rates = [float(r["fundingRate"]) for r in rows]
    latest_rate = rates[-1]
    percentile = percentile_rank(latest_rate, rates)
    features, feature_report = compute_series_features(
        "funding_rate",
        spec,
        rates,
        samples_per_day=samples_per_day,
        expected_count=window_days * samples_per_day,
        # crowd_label 是 percentile 的分級解讀，實作在 agent/collectors/derivatives.py，
        # 不在本層重造一份
        provided={"crowd_label": crowd_label(percentile)},
    )

    return {
        "coin": coin,
        "factor": "funding_rate",
        "horizon": req.horizon,
        "window_days": window_days,
        "window_source": window_source,
        "window_reasoning": window_reasoning,
        "funding": f"{latest_rate * 100:+.4f}%",
        "percentile": f"{percentile:.0f}th",
        "trend": f"{_series_trend(rates)}（{window_days}-day window）",
        "crowd_label": crowd_label(percentile),
        "sample_count": len(rates),
        "source": f"Binance Futures {spec['endpoint']}",
        "features": features,
        "feature_spec": feature_report,
    }


class Stage2ActiveAddressRequest(BaseModel):
    coin: str
    horizon: str | None = None


def _supported_assets(factor_id: str) -> list[str]:
    """支援哪些幣種讀自 Stage 3 Knowledge 的 `supported_assets`，不在程式裡另外
    維護一份清單——active_address 只有 BTC 是資料源現實（blockchain.info 僅涵蓋
    BTC UTXO 鏈），那件事已經寫在知識庫裡了。"""
    try:
        assets = _load_knowledge_md(factor_id).get("supported_assets") or []
    except Exception:  # noqa: BLE001
        return []
    return [str(a).upper() for a in assets]


@app.post("/api/stage2/active_address")
async def stage2_active_address(req: Stage2ActiveAddressRequest):
    """Stage 2 Feature Extraction 的 active_address 版本：真的去抓
    blockchain.info Charts API（免 key）。端點與 `timespan={window}days` 參數樣板
    讀自 `Stage 2 — Feature Extraction/active_address.yaml`，支援幣種讀自 Stage 3
    Knowledge 的 `supported_assets`——兩件事都不在程式裡另外寫死一份。

    窗口跟 funding_rate 共用同一支 `_resolve_window_days_via_llm`（單位都是天，
    不用另外設計一套 prompt）。"""
    coin = req.coin.upper()
    supported = _supported_assets("active_address")
    if coin not in supported:
        raise HTTPException(
            400,
            f"active_address 目前只支援 {'/'.join(supported) or '（知識庫沒列出支援幣種）'}"
            f"（資料源 blockchain.info 僅涵蓋 BTC UTXO 鏈，見 Stage 3 active_address.md 的 supported_assets），收到：{coin}",
        )

    spec = load_feature_spec("active_address")
    window_days, window_reasoning, window_source = await _resolve_window_days_via_llm(req.horizon, "active_address")
    params = render_params(spec["params"], window_days=window_days)

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.get(spec["endpoint"], params=params)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"blockchain.info active_address 抓取失敗：{exc}") from exc

    values = [float(p["y"]) for p in payload.get("values", [])]
    if not values:
        raise HTTPException(502, "blockchain.info 回傳空序列")

    current = values[-1]
    percentile = percentile_rank(current, values)
    features, feature_report = compute_series_features(
        "active_address", spec, values, expected_count=window_days
    )

    return {
        "coin": coin,
        "factor": "active_address",
        "horizon": req.horizon,
        "window_days": window_days,
        "window_source": window_source,
        "window_reasoning": window_reasoning,
        "current_value": f"{current:,.0f}",
        "percentile": f"{percentile:.0f}th",
        "trend": f"{_series_trend(values)}（{window_days}-day window）",
        "sample_count": len(values),
        "source": f"blockchain.info Charts API {spec['endpoint']}",
        "note": "⚠ 已知資料特性：blockchain.info 位址計數常有「當日資料尚未收斂、隔天補齊」的 revision 現象，最新一筆數字可能之後會被修正（見 Stage 2 active_address.yaml）。",
        "features": features,
        "feature_spec": feature_report,
    }


class Stage2CPIRequest(BaseModel):
    horizon: str | None = None


def _round_or_none(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _hours_since(timestamp: str | None) -> int | None:
    """規格檔裡的 `hours_since_event` 是寫檔當下的示範值（cpi.yaml 寫的是「以
    2026-08-02 為基準」），拿它當現值會愈放愈舊。這裡用 `announcement_time`
    對現在重算——事件時程本身讀規格檔，但「距今多久」是每次執行才算得出來的。"""
    if not timestamp:
        return None
    try:
        event_time = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return int((datetime.now(timezone.utc) - event_time).total_seconds() // 3600)


def _parse_fred_csv(text: str) -> list[tuple[str, float]]:
    """FRED fredgraph.csv 是「日期,數值」兩欄、依時間正序排列（最舊在前），
    缺值以 "." 表示——這裡略過缺值，不補值（跟 cpi.yaml 的 missing_ratio
    設計一致：缺值要如實反映在 sample_size，不是幫它填一個猜測值）。

    ⚠️ 回傳 (日期, 數值) 而不是只有數值：這個序列**真的會缺月**（2026-08-02 抓下來
    的 CPIAUCSL 缺 2025-10，2025-09 直接跳到 2025-11）。丟掉日期就只能用位置索引
    往回數，缺一個月整排位移一格，年增率會從正確的 3.46% 變成 3.73%——不會報錯、
    數字也很合理，只有拿日期對照才看得出來。"""
    series: list[tuple[str, float]] = []
    for row in csv.reader(text.splitlines()):
        if len(row) < 2 or row[1] in ("", "."):
            continue
        try:
            series.append((row[0], float(row[1])))
        except ValueError:
            continue
    return series


@app.post("/api/stage2/cpi")
async def stage2_cpi(req: Stage2CPIRequest):
    """Stage 2 Feature Extraction 的 cpi 版本：真的去抓 FRED 公開 CSV（免 key，
    月頻，全幣種通用，不用逐幣種抓）。窗口單位是「月」不是「天」——重用日頻
    的 `_resolve_window_days_via_llm` 結果再換算成月，不是另外設計一套月頻
    LLM prompt（cpi.yaml 本身也說這是換算問題，不是完全不同的判斷邏輯）。

    這個 factor 的規格檔有兩塊，兩塊都讀：
    - `feature:` 是 Event Factor 骨架（事件何時公布、幾個來源確認、影響幾個標的），
      規格檔寫的就是資料本身，照抄不另算；`hours_since_event` 例外，改用
      `announcement_time` 對現在重算，不用 yaml 裡那個寫死的示範值
    - `value_source:` 是「這次公布的數字」要去哪抓（FRED CPIAUCSL）。Event 骨架
      本來沒有數值端點這一格，2026-08-02 補這段，免得 CPI 變成唯一端點還寫死在
      程式裡的 factor"""
    spec = load_feature_spec("cpi")
    value_source = load_value_source("cpi")
    if not value_source:
        raise HTTPException(500, "cpi.yaml 缺 value_source 區塊（數值端點無處可讀）")

    window_days, window_reasoning, window_source = await _resolve_window_days_via_llm(req.horizon, "cpi")
    window_months = max(1, round(window_days / 30))

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.get(value_source["endpoint"], params=value_source["params"])
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"FRED CPI 抓取失敗：{exc}") from exc

    dated = _parse_fred_csv(resp.text)
    if not dated:
        raise HTTPException(502, "FRED CPI 資料是空的或格式解析失敗")

    windowed_dated = dated[-window_months:] if window_months < len(dated) else dated
    windowed = [v for _, v in windowed_dated]
    current = windowed[-1]
    percentile = percentile_rank(current, windowed)
    # 年增率固定用完整序列、而且**用日期對齊往回 12 個月**（cpi.yaml 那行已標明）。
    # 不能用 series[-13]：序列會缺月，位置索引會對到錯的基準月
    yoy_pct, yoy_note = pct_change_vs_month(dated, months_back=12)

    values, value_report = compute_series_features(
        "cpi",
        value_source["fields"],
        windowed,
        provided={"yoy_pct": _round_or_none(yoy_pct)},
    )
    events, event_report = compute_series_features(
        "cpi",
        spec,
        [],
        # yaml 裡的 hours_since_event 是寫檔當下的示範值，這裡對「現在」重算
        provided={"hours_since_event": _hours_since(spec.get("announcement_time"))},
    )

    return {
        "factor": "cpi",
        "horizon": req.horizon,
        "window_months": window_months,
        "window_source": window_source,
        "window_reasoning": f"{window_reasoning}（換算：{window_days} 天 ≈ {window_months} 個月，CPI 是月頻資料，見 cpi.yaml）",
        "current_value": f"{current:.2f}",
        "percentile": f"{percentile:.0f}th",
        "mom_pct": f"{values['mom_pct']:+.2f}%" if values.get("mom_pct") is not None else None,
        "yoy_pct": f"{yoy_pct:+.2f}%" if yoy_pct is not None else None,
        "yoy_basis": yoy_note,
        "sample_count": len(windowed),
        "source": f"FRED CPIAUCSL {value_source['endpoint']}",
        "features": {**events, **values},
        "feature_spec": {
            "event_skeleton": event_report,
            "value_source": {**value_report, "endpoint": value_source["endpoint"]},
        },
    }


LIQUIDATION_MAX_LISTEN_SECONDS = 20  # 防呆上限，避免 demo request 掛太久


class Stage2LiquidationRequest(BaseModel):
    coin: str
    listen_seconds: int = 8


@app.post("/api/stage2/liquidation")
async def stage2_liquidation(req: Stage2LiquidationRequest):
    """Stage 2 Feature Extraction 的 liquidation 版本：真的開 WebSocket 監聽，
    不是查歷史——Binance 舊版查歷史清算單的 REST API 已停用，只剩即時推送頻道
    （見 Stage 2 liquidation.yaml 的結構性限制說明）。percentile／trend／
    slope／rolling_* 這類需要歷史時間序列的欄位這個 factor 結構性沒有，一律
    不產生，不編造假的歷史推算值——**哪幾格不產生現在是讀 yaml 讀出來的**
    （那份檔案裡明寫 null 的就是），不是程式裡的 if。"""
    coin = req.coin.upper()
    symbol = PERP_SYMBOL.get(coin)
    if symbol is None:
        raise HTTPException(400, f"不支援的幣種：{coin}（支援：{', '.join(PERP_SYMBOL)}）")

    spec = load_feature_spec("liquidation")
    ws_url = spec["endpoint"]
    listen_seconds = max(1, min(req.listen_seconds, LIQUIDATION_MAX_LISTEN_SECONDS))
    events: list[dict] = []

    try:
        async with websockets.connect(ws_url, open_timeout=10) as ws:
            # window_start 要在連線建立「之後」才開始算，不然 WebSocket handshake
            # 花的時間會被算進「監聽窗口」，讓 window_end-window_start 跟
            # listen_seconds 對不上、看起來像 bug。
            window_start = datetime.now(timezone.utc)
            loop = asyncio.get_event_loop()
            deadline = loop.time() + listen_seconds
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                payload = json.loads(msg)
                order = payload.get("o", {})
                if order.get("s") == symbol:
                    events.append(order)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Liquidation WebSocket 監聽失敗：{exc}") from exc

    window_end = datetime.now(timezone.utc)
    observed_notional = sum(float(o.get("q", 0)) * float(o.get("ap", 0)) for o in events)

    # 這四格是 WebSocket 監聽的產物，不是從序列算出來的；yaml 其餘明寫 null 的欄位
    # （percentile／slope／roc／rolling_*／z_score／missing_ratio）會整格不產生
    features, feature_report = compute_series_features(
        "liquidation",
        spec,
        [],
        provided={
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "observed_count": len(events),
            "observed_notional": round(observed_notional, 2),
        },
    )

    return {
        "coin": coin,
        "factor": "liquidation",
        "listen_seconds": listen_seconds,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "observed_count": len(events),
        "observed_notional": f"{observed_notional:,.2f}",
        "percentile": None,
        "trend": None,
        "features": features,
        "feature_spec": feature_report,
        "note": (
            "結構性限制（見 Stage 2 liquidation.yaml）：Binance 舊版查歷史清算單的 REST API 已停用，"
            "只剩即時推送頻道，這裡是真的開 WebSocket 監聽固定秒數、統計窗口內剛好發生的清算單，不是"
            "查歷史。observed_count=0 不代表沒有清算風險，只代表這段短窗口沒有觀測到——單一交易對在"
            f"{listen_seconds} 秒內經常觀測不到事件是正常現象，不是程式錯誤。percentile／trend／slope"
            "等需要歷史序列的欄位這個 factor 結構性沒有，一律不產生。"
        ),
        "source": f"Binance USDⓈ-M forceOrder WebSocket {ws_url}",
    }


PANEWS_ENDPOINT = "https://universal-api.panewslab.com/articles"
PANEWS_PAGE_SIZE = 100          # 分頁大小，Stage 2 panews_sentiment.yaml 的實測用值
PANEWS_MAX_PAGES = 30           # demo 防呆上限（3000 篇）。⚠ 這不是「抓到這裡就夠了」，
                                # 是不讓單次 demo request 打太多頁——實測 PANews 中文站約
                                # 每天 130+ 篇，一個 28 天窗口要 ~38 頁才蓋得滿，所以這個上限
                                # 經常會被觸到。被觸到時 coverage_note 會明講實際只蓋到幾天，
                                # 不靜靜截斷（實測：15 頁只蓋到 11 天，30 頁約 22 天）
PANEWS_PAGE_CONCURRENCY = 6     # 同一個 host 併發上限，別把對方打爆（實測 15 頁約 5 秒）

# ⚠️ 簡化版利多／利空詞表——Stage 2 panews_sentiment.yaml 已經寫明這是「臨時的
# 簡化代理，不是最終設計」，這裡照那份方法論實作，缺點原封不動繼承：
#   1. 跟 pipeline/fetch_media_kol_mentions.py「不做規則式看多看空分類」的既有原則
#      衝突（那支腳本的理由是完整句子丟給 LLM 判斷立場比關鍵字計數準）。這裡需要一個
#      能逐日聚合、拿去跑 IC 的連續數值才暫時這樣做，待 Ken 拍板兩種用途能不能用不同方法
#   2. 覆蓋率普通：一半左右的文章命中不到任何關鍵字，立場資訊完全沒被捕捉到
#   3. 正解應該是接真的中文金融情緒模型（FinBERT 類），這次沒有現成模型可用
# ⚠️ 另外一件要講清楚的事：Stage 2 yaml 記錄的那次離線示範（1095 篇、命中率 0.491）
# 用的腳本沒有留下來，詞表內容不可能完全一致——這裡是**照方法論重建**，不是重跑同一份
# 程式，所以命中率不會剛好等於 0.491。要對得上數字得先把當時的詞表補進版控。
PANEWS_BULL_WORDS = [
    "上涨", "大涨", "暴涨", "反弹", "突破", "新高", "利好", "看涨", "增持", "买入",
    "流入", "增长", "获批", "通过", "合作", "采用", "复苏", "乐观", "创纪录", "回暖",
]
PANEWS_BEAR_WORDS = [
    "下跌", "大跌", "暴跌", "回落", "新低", "利空", "看跌", "抛售", "减持", "卖出",
    "流出", "崩盘", "清算", "爆仓", "亏损", "黑客", "攻击", "被盗", "诉讼", "破产",
    "恐慌", "下滑", "风险", "警告", "打击",
]


def _panews_article_score(title: str, desc: str) -> tuple[float, bool]:
    """單篇文章的情緒分數＝(利多詞數 - 利空詞數) / (利多詞數 + 利空詞數)，
    一個詞命中算一次（不重複計同一個詞）。回傳 (分數, 是否命中任一詞)——
    沒命中的記 0 分，但要跟「命中後剛好抵銷成 0」分開統計，這是 nonzero_ratio
    這個欄位存在的理由（Stage 2 yaml 用它揭露詞表覆蓋率）。"""
    haystack = f"{title} {desc}"
    bull = sum(1 for w in PANEWS_BULL_WORDS if w in haystack)
    bear = sum(1 for w in PANEWS_BEAR_WORDS if w in haystack)
    if bull + bear == 0:
        return 0.0, False
    return (bull - bear) / (bull + bear), True


def _panews_match_coin(coin: str, title: str, desc: str) -> bool:
    """幣種比對直接用 pipeline/fetch_media_kol_mentions.py 那份 COIN_KEYWORDS／
    COIN_EXCLUDE_KEYWORDS（Stage 2 yaml 明講「同一份規則」），不在這裡另外維護
    第二份關鍵字表——排除詞是實測踩過的假陽性（ETH Zurich），複製一份遲早會走鐘。"""
    haystack = f"{title} {desc}"
    if any(kw in haystack for kw in PANEWS_COIN_EXCLUDE.get(coin, [])):
        return False
    return any(kw in haystack for kw in PANEWS_COIN_KEYWORDS.get(coin, []))


async def _fetch_panews_page(client: httpx.AsyncClient, sem: asyncio.Semaphore, page: int) -> list[dict]:
    async with sem:
        resp = await client.get(
            PANEWS_ENDPOINT, params={"take": PANEWS_PAGE_SIZE, "skip": page * PANEWS_PAGE_SIZE}
        )
        resp.raise_for_status()
        payload = resp.json()
    return payload if isinstance(payload, list) else []


def _panews_published(article: dict) -> datetime | None:
    raw = article.get("publishedAt") or article.get("createdAt")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


class Stage2PanewsRequest(BaseModel):
    coin: str
    horizon: str | None = None


@app.post("/api/stage2/panews_sentiment")
async def stage2_panews_sentiment(req: Stage2PanewsRequest):
    """Stage 2 Feature Extraction 的 panews_sentiment 版本：真的去打 PANews
    的分頁端點（免 key），照 Stage 2 panews_sentiment.yaml 的方法論算情緒特徵。

    這個 factor 的 `window` 語意跟其他 factor 不同（yaml 明講）：它只決定
    **預設往回抓多深**，不是硬性過濾邊界——超出 window 的文章標「⚠️非近期」
    但照樣保留、照樣計入，跟 agent/collectors/news.py 的 `_recency_note` 同一個
    原則。理由是一則 5 個月前的監管訴訟新聞可能現在還在影響市場，在 Stage 2
    這一步用 window 砍掉，下游就再也看不到它了。

    分頁深度不是固定值：先抓第一頁量出「一天大概幾篇」，再估算蓋滿 window
    需要幾頁，最後受 PANEWS_MAX_PAGES 上限約束。被上限截斷時 coverage_note
    會明講實際只蓋到幾天，不假裝抓滿了。"""
    coin = req.coin.upper()
    if coin not in PANEWS_COIN_KEYWORDS:
        raise HTTPException(
            400,
            f"panews_sentiment 不支援的幣種：{coin}"
            f"（關鍵字表涵蓋：{', '.join(PANEWS_COIN_KEYWORDS)}）",
        )

    window_days, window_reasoning, window_source = await _resolve_window_days_via_llm(
        req.horizon, "panews_sentiment"
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    sem = asyncio.Semaphore(PANEWS_PAGE_CONCURRENCY)
    articles: list[dict] = []
    pages_fetched = 0
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            articles = await _fetch_panews_page(client, sem, 0)
            if not articles:
                raise HTTPException(502, "PANews 回傳空列表")
            pages_fetched = 1

            # 一批一批往回翻，直到最舊一篇早於 cutoff（＝window 蓋滿了）或碰到頁數上限。
            # ⚠️ 這裡刻意不用「第一頁密度 × window 天數」一次估算要抓幾頁——實測那樣會低估：
            # 第一頁只跨幾個小時，量出來的密度比實際低（估 107 篇/天，實際約 136 篇/天），
            # 結果是抓完 15 頁只蓋到 11 天、卻又沒觸及上限，看起來像「抓夠了」其實沒有。
            while pages_fetched < PANEWS_MAX_PAGES:
                oldest_so_far = _panews_published(articles[-1])
                if oldest_so_far is not None and oldest_so_far <= cutoff:
                    break
                batch = list(range(pages_fetched, min(pages_fetched + PANEWS_PAGE_CONCURRENCY, PANEWS_MAX_PAGES)))
                pages = await asyncio.gather(*(_fetch_panews_page(client, sem, p) for p in batch))
                new_articles = [a for page in pages for a in page]
                if not new_articles:
                    break  # 資料源翻到底了，不是上限擋住
                articles += new_articles
                pages_fetched += len(batch)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"PANews articles 抓取失敗：{exc}") from exc

    matched: list[tuple[datetime | None, float, bool]] = []
    for art in articles:
        title, desc = str(art.get("title") or ""), str(art.get("desc") or "")
        if not _panews_match_coin(coin, title, desc):
            continue
        score, hit = _panews_article_score(title, desc)
        matched.append((_panews_published(art), score, hit))

    if not matched:
        raise HTTPException(
            502,
            f"這次抓到的 {len(articles)} 篇文章裡沒有任何一篇命中 {coin} 的關鍵字——"
            "不是程式錯誤，可能是這段期間中文媒體沒報導這個幣種，也可能是關鍵字表覆蓋不足。",
        )

    scores = [s for _, s, _ in matched]
    mean_score = sum(scores) / len(scores)
    variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
    nonzero_ratio = sum(1 for _, _, hit in matched if hit) / len(matched)
    non_recent = sum(1 for ts, _, _ in matched if ts is not None and ts < cutoff)

    # 逐日聚合：mention_growth 比的是「最近一天 vs 前一天」，跟 yaml 定義一致。
    # ⚠️ 最近一天幾乎必然是「還沒過完的今天」，篇數天生偏低——實測跑出來常常是
    # -70%~-90% 這種看起來像雪崩的數字，那是統計窗口不完整，不是輿論真的冷掉。
    # 這裡不偷偷改成「比前兩個完整日」去美化數字，而是照 yaml 定義算、在 note 裡講明。
    daily_counts: dict[str, int] = {}
    for ts, _, _ in matched:
        if ts is not None:
            daily_counts[ts.strftime("%Y-%m-%d")] = daily_counts.get(ts.strftime("%Y-%m-%d"), 0) + 1
    days_sorted = sorted(daily_counts)
    mention_growth = None
    if len(days_sorted) >= 2 and daily_counts[days_sorted[-2]]:
        mention_growth = (daily_counts[days_sorted[-1]] - daily_counts[days_sorted[-2]]) / daily_counts[days_sorted[-2]]

    timestamps = [ts for ts, _, _ in matched if ts is not None]
    oldest = min(timestamps).strftime("%Y-%m-%d") if timestamps else None
    covered_days = (max(timestamps) - min(timestamps)).days if len(timestamps) >= 2 else 0
    # 覆蓋判斷用「翻到的最舊那篇有沒有早於 cutoff」，不是用相符文章的跨度——相符文章
    # 可能中間有幾天完全沒被報導，那不算沒抓到。
    all_published = [ts for ts in (_panews_published(a) for a in articles) if ts is not None]
    reached_cutoff = bool(all_published) and min(all_published) <= cutoff
    truncated = not reached_cutoff

    return {
        "coin": coin,
        "factor": "panews_sentiment",
        "horizon": req.horizon,
        "window_days": window_days,
        "window_source": window_source,
        "window_reasoning": window_reasoning,
        "sentiment_score": f"{mean_score:+.4f}",
        "sentiment_std": f"{variance ** 0.5:.4f}",
        "mention_count": len(matched),
        "mention_growth": f"{mention_growth:+.1%}" if mention_growth is not None else None,
        "nonzero_ratio": f"{nonzero_ratio:.3f}",
        "non_recent_count": non_recent,
        "articles_scanned": len(articles),
        "pages_fetched": pages_fetched,
        "covered_days": covered_days,
        "oldest_matched": oldest,
        "window_covered": reached_cutoff,
        "sample_count": len(matched),
        "source": f"PANews {PANEWS_ENDPOINT}（take={PANEWS_PAGE_SIZE} 分頁）",
        "coverage_note": (
            f"⚠ 翻到 PANEWS_MAX_PAGES={PANEWS_MAX_PAGES} 頁上限就停了，最舊只翻到 "
            f"{min(all_published).strftime('%Y-%m-%d') if all_published else '未知'}，還沒回溯到 window "
            f"要求的 {window_days} 天前——這是 demo 的防呆上限，不是資料源沒有更早的資料"
            "（Stage 2 yaml 記錄該端點 BTC 標籤可回溯到 2023-01-14）。這次的特徵值只反映抓到的這段。"
            if truncated
            else f"window={window_days} 天已完整回溯（翻了 {pages_fetched} 頁、掃 {len(articles)} 篇，"
            f"其中相符文章橫跨 {covered_days} 天），未觸及分頁上限。"
        ),
        "note": (
            f"情緒分數用的是簡化版關鍵字計分（利多詞 {len(PANEWS_BULL_WORDS)} 個／利空詞 "
            f"{len(PANEWS_BEAR_WORDS)} 個），不是 NLP 情緒模型——nonzero_ratio={nonzero_ratio:.3f} "
            "就是這套方法的覆蓋率，沒命中任何關鍵字的文章記 0 分。Stage 2 yaml 記錄的那次離線示範"
            "（命中率 0.491）用的腳本沒有留下來，這裡是照方法論重建、不是重跑同一份程式，數字不會完全一致。"
            f"另有 {non_recent} 篇超出 window 的文章被標記為非近期但**照樣計入**（window 只決定抓多深，"
            "不是過濾邊界，見 yaml 與 agent/collectors/news.py 的 _recency_note）。"
            "mention_growth 比的是「最近一天 vs 前一天」（yaml 定義），而最近一天通常是還沒過完的今天，"
            "所以這個數字常常是大幅負值——那是窗口不完整造成的，不是輿論真的退燒。"
        ),
    }


# ---------------------------------------------------------------------------
# Stage 2 — etf（bitbo.io HTML table，非 JSON API）
# ---------------------------------------------------------------------------

_ETF_TABLE_RE = re.compile(r'<table class="stats-table larger-table">(.*?)</table>', re.DOTALL)
_ETF_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
_ETF_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL)
_ETF_TAG_RE = re.compile(r"<[^>]+>")
_ETF_SUMMARY_ROWS = {"Date", "Total", "Average", "Maximum", "Minimum"}


def _parse_etf_flow_table(html: str) -> list[tuple[str, float]]:
    """解析 bitbo.io ETF flow 頁面的逐日 `Totals` 欄，回傳依日期由舊到新排序的
    (date, value) 序列（單位百萬美元）。免費頁面只給近 9-10 個交易日＋
    Total/Average/Maximum/Minimum 四行統計（見 Stage 2 etf.yaml 已知落差），
    這裡把表頭與統計列排除，只留逐日資料。

    ⚠️ HTML table 解析比 JSON API 脆弱——bitbo.io 改版面這裡就會壞，這是
    Stage 2 etf.yaml 早就記錄過的已知技術債，不是這次遺漏。"""
    match = _ETF_TABLE_RE.search(html)
    if not match:
        raise RuntimeError("bitbo.io 頁面找不到 ETF flow 表格（table.stats-table.larger-table），可能改版了")

    rows: list[tuple[str, float]] = []
    for row_html in _ETF_ROW_RE.findall(match.group(1)):
        cells = [_ETF_TAG_RE.sub("", c).strip() for c in _ETF_CELL_RE.findall(row_html)]
        cells = [c for c in cells if c]
        if not cells or cells[0] in _ETF_SUMMARY_ROWS:
            continue
        try:
            date = datetime.strptime(cells[0], "%b %d, %Y").strftime("%Y-%m-%d")
            total = float(cells[-1])
        except (ValueError, IndexError):
            continue  # 這列格式看不懂就跳過，不讓一行壞資料炸掉整個解析
        rows.append((date, total))

    rows.sort(key=lambda r: r[0])
    return rows


class Stage2ETFRequest(BaseModel):
    coin: str
    horizon: str | None = None


@app.post("/api/stage2/etf")
async def stage2_etf(req: Stage2ETFRequest):
    """Stage 2 Feature Extraction 的 etf 版本：真的去抓 bitbo.io 的 ETF flow 頁面
    （HTML table，非 JSON API，免 key）。端點讀自 `Stage 2 — Feature Extraction/etf.yaml`，
    支援幣種讀自 Stage 3 Knowledge 的 `supported_assets`（目前只有 BTC）。

    ⚠️ window 由 LLM 判斷，但實際能拿到的資料受資料源天花板限制——這個免費頁面
    只給近 9-10 個交易日＋統計列，沒有分頁機制，一次請求就是資料源當下能給的全部，
    不管 LLM 判斷出多長的 window 都不會拿到更多（跟 panews_sentiment 用 window
    決定要不要多翻頁是不同的情況）。這點如實回報在 `note`，不假裝滿足了 window 要求。"""
    coin = req.coin.upper()
    supported = _supported_assets("etf")
    if coin not in supported:
        raise HTTPException(
            400,
            f"etf 目前只支援 {'/'.join(supported) or '（知識庫沒列出支援幣種）'}"
            f"（資料源 bitbo.io 只追蹤美國現貨 BTC ETF，見 Stage 3 etf.md 的 supported_assets），收到：{coin}",
        )

    spec = load_feature_spec("etf")
    window_days, window_reasoning, window_source = await _resolve_window_days_via_llm(req.horizon, "etf")

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.get(spec["endpoint"], headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"bitbo.io ETF flow 抓取失敗：{exc}") from exc

    try:
        dated_series = _parse_etf_flow_table(resp.text)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    if not dated_series:
        raise HTTPException(502, "bitbo.io 頁面解析出來是空序列")

    values = [v for _, v in dated_series]
    available_days = len(values)
    capped = window_days > available_days
    current = values[-1]
    percentile = percentile_rank(current, values)
    features, feature_report = compute_series_features(
        "etf", spec, values, expected_count=window_days
    )

    return {
        "coin": coin,
        "factor": "etf",
        "horizon": req.horizon,
        "window_days": window_days,
        "window_source": window_source,
        "window_reasoning": window_reasoning,
        "current_value": f"{current:+.1f}M",
        "percentile": f"{percentile:.0f}th",
        "trend": f"{_series_trend(values)}（{available_days}-day window，資料源天花板）",
        "sample_count": available_days,
        "date_range": f"{dated_series[0][0]} ~ {dated_series[-1][0]}",
        "source": f"bitbo.io ETF flow {spec['endpoint']}",
        "note": (
            f"⚠ 資料源天花板：bitbo.io 免費頁面只給近 {available_days} 個交易日＋統計列。"
            + (
                f"LLM 判斷的 window={window_days} 天超出這個上限，實際只用得到 {available_days} 天。"
                if capped
                else f"這次 LLM 判斷的 window={window_days} 天沒有超出資料源上限。"
            )
            + "不管 window 給多長，這個 factor 目前都無法取得更長歷史（見 Stage 2 etf.yaml 已知落差）。"
        ),
        "features": features,
        "feature_spec": feature_report,
    }


@app.get("/api/stage3/{factor_id}")
def stage3_factor(factor_id: str):
    """Stage 3 Knowledge Layer：純查表，不打 LLM。內容讀自
    `Stage 3 — Knowledge Layer/{factor_id}.md` 的 yaml 區塊——Ken 手動研究、
    附真實出處的正式版本。07/13 原文都講清楚 Stage 3 本身是 library，只回答
    「這個 factor 是什麼」，不是推理層——所以這裡直接讀檔回傳，沒有任何 LLM
    呼叫。四個 factor 共用同一支路由，不是各自複製一份幾乎一樣的處理函式。"""
    if factor_id not in KNOWN_FACTORS:
        raise HTTPException(404, f"未知 factor：{factor_id}（目前支援：{', '.join(KNOWN_FACTORS)}）")
    try:
        knowledge = _load_knowledge_md(factor_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"讀取 Stage 3 知識庫檔案失敗：{exc}") from exc

    return {"knowledge": knowledge, "source_file": f"Stage 3 — Knowledge Layer/{factor_id}.md"}

# ---------------------------------------------------------------------------
# Stage 4 — Dynamic Evidence Weight Engine（四個 factor 通用）
# ---------------------------------------------------------------------------

# 每個 factor 的「歷史序列從哪來」差很多，Prior Weight 要算 IC 就得逐 factor
# 取回可跟價格對齊的時間序列。liquidation 沒有歷史可查（見 Stage 2/3 文件），
# 這是結構性限制，不是這裡偷懶不做。
ACTIVE_ADDRESS_IC_COINS = {"BTC"}


async def _fetch_active_address_history_before(anchor_date: str, horizon_days: int) -> dict[str, float]:
    """抓 [anchor_date - 2×horizon_days, anchor_date] 的每日活躍地址數。
    blockchain.info Charts API 支援 `start` 參數，可以錨定到本地 CSV 最後一天，
    不是只能抓「最近 N 天」。

    端點同樣讀自 Stage 2 規格檔；`start` 是這裡多加的（規格檔的 params 只描述
    Stage 2「抓最近一段」那個用法，Stage 4 算 IC 要往回錨定到別的日期）。"""
    spec = load_feature_spec("active_address")
    anchor_dt = datetime.strptime(anchor_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_dt = anchor_dt - timedelta(days=horizon_days * 2)
    params = render_params(spec["params"], window_days=horizon_days * 2)
    params["start"] = start_dt.strftime("%Y-%m-%d")
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(spec["endpoint"], params=params)
        resp.raise_for_status()
        payload = resp.json()
    series: dict[str, float] = {}
    for point in payload.get("values", []):
        day = datetime.fromtimestamp(int(point["x"]), tz=timezone.utc).strftime("%Y-%m-%d")
        series[day] = float(point["y"])
    return series



async def _factor_history_before(
    factor_id: str, coin: str, anchor_date: str, horizon_days: int
) -> tuple[dict[str, float] | None, str]:
    """回傳 (factor 的歷史時間序列, 說明字串)。序列是 None 代表「這個 factor
    結構性沒有可用歷史」，不是抓取失敗——呼叫端要照實回報，不能當成錯誤吞掉、
    也不能拿別的東西湊一個數字出來。"""
    if factor_id == "funding_rate":
        symbol = PERP_SYMBOL[coin]
        rows = await _fetch_funding_history_before(symbol, anchor_date, horizon_days)
        if not rows:
            raise RuntimeError("Binance funding rate 回傳空序列")
        return _daily_funding_series(rows), "Binance funding rate（每 8 小時一筆，日內取平均對齊日頻價格）"

    if factor_id == "active_address":
        if coin not in ACTIVE_ADDRESS_IC_COINS:
            return None, (
                f"active_address 的資料源 blockchain.info 只涵蓋 BTC UTXO 鏈，"
                f"這次查詢的 {coin} 沒有對應的鏈上活躍地址序列可用，IC 無法計算。"
            )
        series = await _fetch_active_address_history_before(anchor_date, horizon_days)
        if not series:
            raise RuntimeError("blockchain.info 回傳空序列")
        return series, "blockchain.info 每日活躍地址數（日頻）"

    # cpi（Event Factor）／liquidation（資料源結構性缺歷史）／panews_sentiment
    # （ic 是離線算好寫進 .md 的）都不走現場算 ic 這條路徑，Prior Weight 一律
    # 由 Stage 4 的 .md 檔案給（見 `_resolve_prior_weight`），所以不會走到這裡。
    raise ValueError(f"{factor_id} 不適用 rolling_spearman_ic（不該呼叫到這裡）")


def _applicable_days(knowledge: dict) -> list | None:
    """取這個 factor 的適用分析期間區間（天）。Statistical／Sentiment 骨架放在
    `primary_horizon.applicable_days`，Event 骨架（cpi）沒有 primary_horizon，
    直接放在頂層 `applicable_days`——兩種都支援，找不到就回 None。"""
    ph = knowledge.get("primary_horizon")
    if isinstance(ph, dict) and ph.get("applicable_days"):
        return ph["applicable_days"]
    if knowledge.get("applicable_days"):
        return knowledge["applicable_days"]
    return None


def _horizon_match(horizon_days: int, knowledge: dict) -> tuple[float | None, str]:
    """13 定義的 time_horizon_match：「比較 Stage 1 輸出的 horizon vs Stage 3
    Knowledge.primary_horizon 的接近程度」。2026-08-02 拍板 Option B 之後，
    Knowledge 那邊有了可數值比對的 `applicable_days`，這條線索就能真的算，
    不必再把一段散文丟給 LLM 讓它自己讀「短期」跟「2 週」搭不搭。

    回傳 (score, 說明)。score 落在 0~1：查詢期間落在 factor 適用區間內＝1.0，
    落在區間外則依偏離倍數遞減。**這裡算的只是四條線索之一**，最終的
    context_modifier 仍然由 LLM 綜合判斷給出（13 拍板「LLM 解釋給出，不套公式」），
    這裡不代替它下結論。"""
    rng = _applicable_days(knowledge)
    if not rng or len(rng) != 2:
        return None, "這個 factor 的知識庫沒有 applicable_days，無法數值比對（當未知處理）"

    lo, hi = float(rng[0]), float(rng[1])
    if lo <= horizon_days <= hi:
        return 1.0, f"查詢期間 {horizon_days} 天落在 factor 適用區間 [{rng[0]}, {rng[1]}] 天之內，時間尺度匹配"
    if horizon_days < lo:
        # 查詢比 factor 擅長的尺度更短
        score = max(0.0, horizon_days / lo) if lo > 0 else 0.0
        return score, (
            f"查詢期間 {horizon_days} 天**短於** factor 適用區間 [{rng[0]}, {rng[1]}] 天的下限，"
            f"偏離比例 {score:.2f}（1.0 表示完全匹配）"
        )
    # 查詢比 factor 擅長的尺度更長
    score = max(0.0, hi / horizon_days) if horizon_days > 0 else 0.0
    return score, (
        f"查詢期間 {horizon_days} 天**長於** factor 適用區間 [{rng[0]}, {rng[1]}] 天的上限，"
        f"偏離比例 {score:.2f}（1.0 表示完全匹配）"
    )


def _stage4_modifier_prompt(
    factor_id: str, knowledge: dict, horizon: str | None, horizon_days: int, freshness_note: str
) -> str:
    """Dynamic Modifier 的四條線索要逐 factor 換內容——confirms／conflicts 直接
    讀該 factor 自己的 Stage 3 知識庫，不是共用 funding_rate 的關聯訊號清單。

    cpi 是 Event Knowledge schema（category=event），欄位名跟 Statistical
    Knowledge 完全不同——沒有 primary_horizon／confirms／conflicts，對應的是
    reaction_window／expected_duration（時間）跟 usually_affects／related_events
    （關聯）。共用同一組欄位名會讓 cpi 全部讀成「未知」，明明 Stage 3 cpi.md
    裡有實際資料（見 Stage 4 — Dynamic Evidence Weight Engine/cpi.md 的設計註解）。"""
    is_event = knowledge.get("category") == "event"
    if is_event:
        related = "／".join(
            str(knowledge.get(k)) for k in ("usually_affects", "related_events") if knowledge.get(k)
        ) or "（該 factor 知識庫沒有列出關聯訊號）"
        scale_note = (
            f"{factor_id} 是排定時程事件，"
            f"Reaction Window={knowledge.get('reaction_window') or '未知'}，"
            f"Expected Duration={knowledge.get('expected_duration') or '未知'}"
        )
    else:
        related = "／".join(
            str(knowledge.get(k)) for k in ("confirms", "conflicts") if knowledge.get(k)
        ) or "（該 factor 知識庫沒有列出關聯訊號）"
        ph = knowledge.get("primary_horizon")
        if isinstance(ph, dict):
            scale_note = f"{factor_id} 擅長的尺度＝{ph.get('scale') or '未知'}；理由：{(ph.get('rationale') or '').strip()}"
        else:
            scale_note = f"{factor_id} 的 Primary Horizon={ph or '未知'}"

    # time_horizon_match 已經可以數值比對（Option B：Knowledge 有 applicable_days），
    # 直接把算好的分數與說明交給 LLM，不再要它自己讀散文猜「短期」跟「2 週」搭不搭。
    match_score, match_note = _horizon_match(horizon_days, knowledge)
    score_text = "無法計算" if match_score is None else f"{match_score:.2f}（1.00 = 完全匹配，越低表示尺度差越多）"
    time_property = (
        f"這次查詢 Horizon={horizon or '未提供'}（換算 {horizon_days} 天）。"
        f"比對結果 match={score_text}——{match_note}。"
        f"參考：{scale_note}"
    )
    return (
        f"這次評估的 factor：{factor_id}\n\n"
        f"1. market_regime：尚未接上真實 FOMC／利率資料源（這輪 demo 沒做，當未知處理）\n"
        f"2. time_horizon_match：{time_property}\n"
        f"3. cross_source_consensus：該 factor 知識庫列出的關聯訊號為「{related}」，"
        f"但這些關聯 factor 今天的方向這輪 demo 還沒接上真實資料（當未知處理）\n"
        f"4. freshness：{freshness_note}"
    )


async def _resolve_prior_weight(factor_id: str, coin: str, horizon_days: int) -> dict:
    """Prior Weight 有三種來源（13 文件 2026-08-02 拍板，不是三套互不相容的系統，
    是同一個 evidence_weight 概念下的不同填法）：

    1. `rolling_spearman_ic`——Statistical Factor（funding_rate／active_address）：
       現場真的算，ic 就是 Prior Weight 的值
    2. `impact_level`——Event Factor（cpi）：**不算 ic**（離散事件沒有「每天的值」
       可以跟每天的 forward_return 配對），值直接讀 Stage 4 .md 的分級映射
    3. `domain_knowledge`——資料源結構性缺歷史序列（liquidation）：ic 算不出來，
       值一樣讀 Stage 4 .md，附上為什麼給這個數字的理由

    後兩種的值跟理由都寫在 `Stage 4 — Dynamic Evidence Weight Engine/*.md` 裡，
    這裡只負責讀，不在程式碼裡自己訂數字。

    ⚠️ 還有第四種情況（panews_sentiment）：basis 也是 `rolling_spearman_ic`，但
    值是**離線算好寫進 .md** 的，不是這裡現場算——因為它的 factor_value(t) 是
    逐日情緒分數，要重算得先把整段歷史文章抓回來重新計分（demo 單次請求做不到），
    而且當初算 ic=0.051 的那支離線腳本沒有留下來。這種情況一樣走「讀 .md」這條路，
    只是 note 要講清楚它跟 cpi/liquidation 的 null 不是同一回事。"""
    weight_md = _load_weight_md(factor_id)
    md_prior = (weight_md or {}).get("prior_weight") or {}

    # --- 來源 2/3（以及離線算好 ic 的 panews_sentiment）：值寫在 Stage 4 .md 裡，不現場算 ---
    if md_prior.get("value") is not None:
        basis = md_prior.get("basis") or "domain_knowledge"
        md_ic = ((weight_md or {}).get("historical_predictability") or {}).get("ic") or {}
        example_run = md_ic.get("example_run") or {}
        offline_ic = basis == "rolling_spearman_ic"
        return {
            "basis": basis,
            "value": float(md_prior["value"]),
            # ic 現場沒算，但如果 .md 裡有離線跑過的紀錄就照實帶出來，不要讓畫面上
            # 顯示「ic: null」誤導成「這個 factor 沒有 ic 概念」（那是 cpi 的情況）
            "ic": example_run.get("computed_value") if offline_ic else None,
            "sample_size": example_run.get("sample_size") if offline_ic else None,
            "ic_source": "offline（.md 紀錄，非本次現場計算）" if offline_ic else None,
            "impact_level": md_prior.get("impact_level"),
            # `confidence` 是 panews_sentiment 這輪新加的欄位（樣本 44 天）。照實帶出來給
            # 卡片顯示，但**不影響排序**——2026-08-02 拍板一律照 evidence_weight 單鍵排序。
            "confidence": md_prior.get("confidence"),
            "reason": (md_prior.get("reason") or "").strip(),
            "computable": True,
            "source_file": f"Stage 4 — Dynamic Evidence Weight Engine/{factor_id}.md",
            "note": (
                (
                    f"這個 factor 的 ic 是**離線算好寫進 .md** 的（{example_run.get('computed_value')}，"
                    f"樣本數 {example_run.get('sample_size')}），不是本次現場計算——它的 factor_value(t) "
                    "是逐日情緒分數，重算得先把整段歷史文章抓回來重新計分，單次 demo 請求做不到；"
                    "當初那支離線腳本也沒有留下來（見 Stage 4 .md）。這跟 cpi／liquidation 的 "
                    "ic=null 不是同一回事：那兩個是結構性沒有 ic 可算，這個是算過但沒接進即時流程。"
                )
                if offline_ic
                else (
                    "這個 factor 不走 rolling_spearman_ic：ic 欄位是 null 不是缺口，"
                    "是 13 文件拍板的分類結果（Event Factor 用 impact_level 分級／"
                    "資料源缺歷史序列的用 Domain Knowledge），Prior Weight 的值與理由"
                    "都讀自上面那份 .md，程式沒有自己訂數字。"
                )
            ),
        }

    # --- 來源 1：Statistical Factor，現場算 ic ---
    anchor_date = _resolve_ic_anchor_date(coin)
    try:
        series, series_note = await _factor_history_before(factor_id, coin, anchor_date, horizon_days)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"{factor_id} Prior Weight 歷史序列抓取失敗：{exc}") from exc

    if series is None:
        return {
            "basis": "rolling_spearman_ic",
            "value": None,
            "ic": None,
            "sample_size": 0,
            "input_horizon_days": horizon_days,
            "anchor_date": anchor_date,
            "computable": False,
            "note": series_note,
        }

    computed = _compute_rolling_spearman_ic(coin, horizon_days, anchor_date, series)
    return {
        "basis": "rolling_spearman_ic",
        # Statistical Factor 的 Prior Weight 就是 ic 本身
        "value": computed["ic"],
        "ic": computed["ic"],
        "sample_size": computed["sample_size"],
        "input_horizon_days": computed["input_horizon_days"],
        "anchor_date": computed["anchor_date"],
        "computable": computed["ic"] is not None,
        "factor_series_source": series_note,
        "note": computed["note"],
    }


async def _compute_stage4(factor_id: str, coin: str, horizon: str | None, horizon_days: int) -> dict:
    """Stage 4 的共用實作：Prior Weight × Dynamic Modifier（LLM 判斷）＝
    final_evidence_weight。四個 factor 走同一套流程，差別只在 Prior Weight 從
    哪來（ic 現場算／impact_level 分級／Domain Knowledge），見
    `_resolve_prior_weight`。"""
    prior_weight = await _resolve_prior_weight(factor_id, coin, horizon_days)

    # --- Dynamic Modifier ---
    try:
        knowledge = _load_knowledge_md(factor_id)
    except Exception:  # noqa: BLE001
        knowledge = {}

    if factor_id == "cpi":
        freshness_note = "CPI 是月頻資料且公布落後參考月份約一個月，最新一筆本質上不可能「很新」"
    elif factor_id == "panews_sentiment":
        freshness_note = (
            "媒體報導是準即時的（快訊近乎即時），這次抓的是當下最新分頁；但要注意這個 factor 的"
            "freshness 門檻應該比日頻／月頻的 factor 更嚴格——幾小時前的敘事就可能已經過時"
        )
    else:
        freshness_note = "資料是這次請求當下即時打 API 拿到的，非常新鮮"
    user_prompt = _stage4_modifier_prompt(factor_id, knowledge, horizon, horizon_days, freshness_note)

    settings = get_settings()
    try:
        client = build_llm_client(settings)
        raw = await asyncio.to_thread(client.converse, STAGE4_MODIFIER_SYSTEM_PROMPT, user_prompt, 512)
        result = _extract_json(raw)
        context_modifier = max(0.5, min(2.0, float(result["context_modifier"])))
        modifier_reasoning = str(result.get("reasoning", ""))
        modifier_source = "llm"
    except Exception as exc:  # noqa: BLE001
        context_modifier = 1.0
        modifier_reasoning = f"LLM 判斷失敗，退回中性值 1.0（非 LLM 判斷，不是算出來的）：{exc}"
        modifier_source = "fallback"

    prior_value = prior_weight.get("value")
    final_weight = prior_value * context_modifier if prior_value is not None else None

    # 把算好的 time_horizon_match 一起回傳，讓前端看得到「這條線索是怎麼算出來的」，
    # 不是只看到 LLM 綜合完的一個 modifier 數字。
    match_score, match_note = _horizon_match(horizon_days, knowledge)
    return {
        "factor": factor_id,
        "coin": coin,
        "horizon": horizon,
        "horizon_days": horizon_days,
        "prior_weight": prior_weight,
        "dynamic_modifier": {
            "context_modifier": context_modifier,
            "reasoning": modifier_reasoning,
            "source": modifier_source,
            "time_horizon_match": {
                "score": match_score,
                "applicable_days": _applicable_days(knowledge),
                "query_horizon_days": horizon_days,
                "note": match_note,
            },
            "inputs_status": {
                "market_regime": "stub（尚未接上真實資料源）",
                "time_horizon_match": "real（程式用 applicable_days 數值比對算出，非 LLM 讀散文猜）",
                "cross_source_consensus": "stub（關聯 factor 今天的方向這輪未接上）",
                "freshness": "real（依該 factor 的資料頻率如實描述）",
            },
        },
        "final_evidence_weight": final_weight,
    }


@app.post("/api/stage4/{factor_id}")
async def stage4_factor(factor_id: str, req: Stage4FundingRequest):
    """Stage 4 Dynamic Evidence Weight Engine，四個 factor 共用一支路由。
    Prior Weight 真的算 rolling_spearman_ic（各 factor 自己的歷史序列 × 本地
    CSV 價格的 forward return）；Dynamic Modifier 真的打一次 LLM。
    liquidation 沒有歷史序列可用，IC 會回 null 並說明是結構性限制。"""
    if factor_id not in KNOWN_FACTORS:
        raise HTTPException(404, f"未知 factor：{factor_id}（目前支援：{', '.join(KNOWN_FACTORS)}）")
    coin = req.coin.upper()
    if PERP_SYMBOL.get(coin) is None:
        raise HTTPException(400, f"不支援的幣種：{coin}（支援：{', '.join(PERP_SYMBOL)}）")
    # 沒帶 horizon_days 就用中性的「自由文字 Horizon → 天數」換算（不是退回固定 14 天，
    # 那會讓 time_horizon_match 不管問幾年都以為在問兩週）。
    horizon_days, _ = await _resolve_effective_horizon_days(req.horizon, req.horizon_days)
    return await _compute_stage4(factor_id, coin, req.horizon, horizon_days)


# ---------------------------------------------------------------------------
# Stage 5 — Evidence Card ＋ Prioritization（四個 factor 一起組裝、一起排序）
# ---------------------------------------------------------------------------

# 13 文件的 evidence_id 命名規則標「待定」，這裡先用 {FACTOR}_{COIN} 的固定格式，
# 不自己發明一套看起來很正式、實際上沒人拍板的編號規則。
def _evidence_id(factor_id: str, coin: str) -> str:
    return f"{factor_id.upper()}_{coin}"


async def _stage2_fact_for(factor_id: str, coin: str, horizon: str | None) -> dict:
    """取各 factor 的 Stage 2 輸出（Fact 層）。四個 factor 的欄位結構本來就不同，
    這裡不強行統一成同一組欄位名，Evidence Card 的 `fact` 只挑該 factor 真的有的
    欄位放進去。"""
    if factor_id == "funding_rate":
        return await stage2_funding_rate(Stage2FundingRequest(coin=coin, horizon=horizon))
    if factor_id == "active_address":
        return await stage2_active_address(Stage2ActiveAddressRequest(coin=coin, horizon=horizon))
    if factor_id == "cpi":
        return await stage2_cpi(Stage2CPIRequest(horizon=horizon))
    if factor_id == "liquidation":
        return await stage2_liquidation(Stage2LiquidationRequest(coin=coin, listen_seconds=6))
    if factor_id == "panews_sentiment":
        return await stage2_panews_sentiment(Stage2PanewsRequest(coin=coin, horizon=horizon))
    if factor_id == "etf":
        return await stage2_etf(Stage2ETFRequest(coin=coin, horizon=horizon))
    raise ValueError(f"未知 factor：{factor_id}")


async def _build_evidence_card(factor_id: str, coin: str, horizon: str | None, horizon_days: int) -> dict:
    """組裝一張 Evidence Card。

    **卡片有哪些格子、fact 有哪些欄位、哪一格是對應到 Knowledge 的別的欄位，全部讀自
    `Stage 5 — Evidence Card ＋ Prioritization/{factor}.md`**（見 webapp/stage_specs.py）——
    跟 Stage 3/4 讀 .md 同一個模式。以前這幾件事寫死在 `_fact_summary()` 的 if 鏈裡，
    卡片檔改了程式不會跟著改，兩邊哪天不一致沒人會發現。

    幾個原本靠 if 表達、現在讀檔讀出來的例子：
    - liquidation 的 fact 只有三格，**沒有 percentile／trend**（不是放 null）
    - cpi 走 Event Knowledge，`primary_horizon` 對應到 `reaction_window`、
      `persistence` 對應到 `expected_duration`（卡片檔用 `→ 欄位名` 記這件事）
    - liquidation 的 traceability 帶一段「單次觀察窗，非統計訊號」的降級處理說明，
      那段文字是 Stage 2 liquidation.yaml 指定要寫在卡片上的，照抄不改寫

    下面幾個 key 是**執行期才有的東西**，卡片檔不會有（也不該有）：weight_detail
    （這次的計算過程）、confidence、ranking_value／weight_direction（排序用）。"""
    with _timed(
        f"stage2_fetch:{factor_id}",
        f"{coin} 真實資料抓取（Feature Extraction）",
        phase="collect",
        layer="S2_feature_extraction",
    ):
        stage2 = await _stage2_fact_for(factor_id, coin, horizon)
    with _timed(
        f"stage3_knowledge:{factor_id}",
        "讀 Stage 3 — Knowledge Layer/*.md（查表，不打 LLM）",
        phase="collect",
        layer="S3_knowledge",
    ):
        knowledge = stage3_factor(factor_id)["knowledge"]
    with _timed(
        f"stage4_weight:{factor_id}",
        "Prior Weight ＋ LLM Dynamic Modifier",
        phase="reason",
        layer="S4_weight_engine",
    ):
        stage4 = await _compute_stage4(factor_id, coin, horizon, horizon_days)
    _log(
        f"stage4_weight_result:{factor_id}",
        f"evidence_weight={stage4.get('final_evidence_weight')}",
        phase="reason",
        layer="S4_weight_engine",
        metrics={"evidence_weight": stage4.get("final_evidence_weight")},
    )

    card, card_report = build_evidence_card(
        factor_id,
        evidence_id=_evidence_id(factor_id, coin),
        stage2=stage2,
        knowledge=knowledge,
        evidence_weight=stage4["final_evidence_weight"],
        features=stage2.get("features"),
        # `confidence`（目前只有 panews_sentiment 的卡片檔有這格：ic 樣本只有 44 天）是
        # **顯示資訊，不影響排序**——2026-08-02 拍板一律照 evidence_weight 單鍵排序，
        # 不因信賴度分組。算不出值時整格不產生（同日拍板），不留 null。
        runtime_values={"confidence": (stage4.get("prior_weight") or {}).get("confidence")},
    )

    return {
        **card,
        "factor": factor_id,
        "weight_detail": stage4,
        "card_spec": card_report,
        # --- 排序用的量值與方向（2026-08-02 Ken 拍板：排序取絕對值）---
        # evidence_weight 保持**帶號原值**不動（那是 Stage 4 算出來的東西，不該被排序
        # 需求改寫）；排序另外用 ranking_value = |evidence_weight|。
        # 為什麼要取絕對值：ic 是相關係數，值域 [-1, 1]，負值代表**反向訊號**
        # （factor 越高、後續報酬越低）——那是有預測力的訊號，不是沒有訊號。
        # 實測 BTC funding_rate ic=-0.55 是五個 factor 裡強度最高的一個，照帶號值
        # 由大到小排會被排到最後一名，等於把最強的訊號當成最弱的。
        # ⚠️ 代價要講清楚：取絕對值之後，排序只回答「訊號強不強」，不回答「往哪邊」。
        # 方向資訊沒有消失，留在 evidence_weight 的正負號與 weight_direction 這格，
        # 下游（Stage 6 Graph／Stage 7-9 推理鏈）要判斷方向時讀那兩個欄位，不是讀名次。
        "ranking_value": abs(stage4["final_evidence_weight"]) if stage4["final_evidence_weight"] is not None else None,
        "weight_direction": _weight_direction(stage4),
    }


def _weight_direction(stage4: dict) -> dict:
    """排序取絕對值之後，方向要有地方標示，不能只剩一個沒有正負的數字。
    只有 ic 型的權重才有「方向」可言——impact_level／domain_knowledge 給的是
    [0, 1] 的重要性分數，本來就恆正，那不是「正向訊號」，是「沒有方向這個概念」，
    兩者不能混為一談。"""
    basis = (stage4.get("prior_weight") or {}).get("basis")
    weight = stage4.get("final_evidence_weight")
    if basis != "rolling_spearman_ic":
        return {
            "sign": None,
            "label": "不適用",
            "note": (
                f"Prior Weight 來源是 {basis}（重要性分數，值域 [0, 1] 恆正），"
                "「方向」這個概念對它不成立——不是「正向訊號」，是沒有方向可言。"
                "取絕對值對這種卡片不會改變任何東西。"
            ),
        }
    if weight is None:
        return {"sign": None, "label": "無法判斷", "note": "權重算不出來，方向也無從談起。"}
    if weight < 0:
        return {
            "sign": "negative",
            "label": "反向訊號",
            "note": (
                f"ic 為負（final_weight={weight:.4f}）：這個 factor 的值越高，horizon 之後的報酬"
                "越低。這是**有預測力**的訊號，只是方向相反，排序照 |weight| 算強度，"
                "方向留在這裡給下游讀。"
            ),
        }
    return {
        "sign": "positive",
        "label": "同向訊號",
        "note": f"ic 為正（final_weight={weight:.4f}）：factor 值越高，horizon 之後的報酬越高。",
    }


@app.post("/api/stage5")
async def stage5_all(req: Stage5FundingRequest):
    """Stage 5 端點：開一個 execution log 收集區塊，實作在 `_stage5_impl()`。

    拆兩層是為了讓 `/api/stage6` 能在自己的收集區塊裡直接呼叫 `_stage5_impl()`，
    把 Stage 2-5 的紀錄併進同一條時間軸（見 `_capture_log()` 的巢狀說明）。
    """
    with _capture_log() as run_log:
        result = await _stage5_impl(req)
        result["execution_log"] = run_log
        return result


async def _stage5_impl(req: Stage5FundingRequest) -> dict:
    """Stage 5 Evidence Card ＋ Prioritization：組裝層，不重新運算——直接呼叫
    Stage 2/3/4 的處理函式（同一個 process 內直接呼叫，不是另外發 HTTP request），
    把五個 factor 各自的 Fact／Knowledge／Weight 組成統一格式卡片，再依
    **|evidence_weight|（絕對值）**由大到小排序（13 拍板：原 Stage 6 Evidence
    Prioritizer 併入這裡，排序輸入收斂成 evidence_weight 單一鍵；2026-08-02 補充
    拍板取絕對值，理由見 `prioritization.note` 與 `_weight_direction()`）。

    `evidence_coverage` 定義 13 還沒拍板，不產生這個欄位假裝有定案。
    算不出 evidence_weight 的卡片（例如 liquidation 結構性沒有歷史序列）不會被
    刪除——13 明講排序「不刪除，只排序」——只是排在有權重的卡片後面，並在
    卡片裡保留說不出數字的原因。"""
    coin = req.coin.upper()
    if PERP_SYMBOL.get(coin) is None:
        raise HTTPException(400, f"不支援的幣種：{coin}（支援：{', '.join(PERP_SYMBOL)}）")
    _log(
        "stage5_received",
        f"coin={coin}, horizon={req.horizon!r}",
        phase="collect",
        layer="S5_evidence_card",
    )
    # 沒帶 horizon_days 就用中性的「自由文字 Horizon → 天數」換算（不是退回固定 14 天，
    # 那會讓 time_horizon_match 不管問幾年都以為在問兩週）。
    with _timed(
        "resolve_horizon_days",
        "Horizon 自由文字 → 天數（LLM 判斷）",
        phase="reason",
        layer="S5_evidence_card",
    ):
        horizon_days, _ = await _resolve_effective_horizon_days(req.horizon, req.horizon_days)
    _log(
        "horizon_days_resolved",
        f"horizon_days={horizon_days}",
        phase="reason",
        layer="S5_evidence_card",
        metrics={"horizon_days": horizon_days},
    )

    results = await asyncio.gather(
        *(_build_evidence_card(f, coin, req.horizon, horizon_days) for f in KNOWN_FACTORS),
        return_exceptions=True,
    )

    cards: list[dict] = []
    failed: list[dict] = []
    for factor_id, result in zip(KNOWN_FACTORS, results):
        if isinstance(result, BaseException):
            # 單一 factor 失敗不該讓整個 Stage 5 掛掉，但也不能靜靜吞掉——
            # 如實列在 failed 裡，讓看的人知道這張卡為什麼不在排序結果中。
            failed.append({"factor": factor_id, "error": f"{type(result).__name__}: {result}"})
        else:
            cards.append(result)

    # 2026-08-02 拍板：排序鍵仍然是 evidence_weight（單一鍵不變），但比大小時**取絕對值**
    # ——ic 是相關係數，負值是反向訊號、不是弱訊號，照帶號值排會把最強的訊號排到最後。
    # evidence_weight 本身不動（帶號原值留在卡片上），排序用 ranking_value=|weight|。
    cards_sorted = sorted(
        cards,
        key=lambda c: (c["ranking_value"] is not None, c["ranking_value"] or 0),
        reverse=True,
    )
    _log(
        "stage5_prioritized",
        f"{len(cards_sorted)} 張卡片依 |evidence_weight| 排序完成"
        + (f"，{len(failed)} 個 factor 失敗（已列在 failed_factors）" if failed else ""),
        status="ok" if not failed else "skipped",
        phase="reason",
        layer="S5_evidence_card",
        metrics={"cards": len(cards_sorted), "failed": len(failed)},
    )

    return {
        "coin": coin,
        "horizon": req.horizon,
        "prioritization": {
            "ranking_key": "evidence_weight",
            "ranking_transform": "abs",
            "output_count": len(cards_sorted),
            "note": (
                "照 |evidence_weight|（絕對值）由大到小排序——13 拍板排序鍵一律是 evidence_weight，"
                "2026-08-02 補充拍板：比大小時取絕對值。理由：ic 是相關係數，負值代表反向訊號"
                "（factor 越高、後續報酬越低），那是有預測力的訊號；照帶號值排會讓 |ic| 最大的"
                "factor 排到最後一名，等於把最強的訊號當最弱的。⚠ 代價：名次只表達訊號強度、"
                "不表達方向，方向留在每張卡的 evidence_weight 正負號與 weight_direction 欄位，"
                "下游要判方向請讀那兩格、不要讀名次。算不出權重的卡片排最後但不刪除。"
                "evidence_coverage 定義尚未拍板，故不產生該欄位。"
            ),
        },
        "evidence_cards": cards_sorted,
        "failed_factors": failed,
    }


# ---------------------------------------------------------------------------
# Stage 6 — Evidence Graph（設計見 `Stage 6 — Evidence Graph/design.md`）
# ---------------------------------------------------------------------------

# related_evidence 的值是 Stage 3 Knowledge 手寫的自然語言字串（例如
# "open_interest（未平倉量）"、"funding_rate ＋ open_interest（未平倉量）"），
# 不是乾淨的 factor_id 清單——這裡解析出開頭的識別碼，不是重新設計一套
# 結構化格式（那要動 Stage 3 四份 .md，這輪不做）。
_RELATION_SPLIT = re.compile(r"[＋+、]")


def _parse_related_factor_names(raw: str | None) -> list[str]:
    """從一段 confirms／conflicts／independent 的自然語言字串解析出前導識別碼。
    例：「funding_rate ＋ open_interest（未平倉量）」→ ["funding_rate", "open_interest"]。
    像 liquidation.conflicts 那種「（無已知穩定的矛盾對象...）」開頭就是全形括號的，
    解析出空字串，這裡過濾掉——不當成一個「有關係但沒卡片」的項目，因為那句話
    本來就不是在指涉任何 factor。"""
    if not raw:
        return []
    names: list[str] = []
    for piece in _RELATION_SPLIT.split(raw):
        # 只取第一個全形／半形括號之前的部分當識別碼
        token = re.split(r"[（(]", piece.strip(), maxsplit=1)[0].strip()
        if token:
            names.append(token)
    return names


def _normalize_factor_token(token: str) -> str:
    """比對用的正規化：忽略大小寫、hyphen／underscore 視為同一個字元。
    Stage 3 Knowledge 裡有的用 hyphen（hash-rate、vol-compression），有的用
    underscore（funding_rate）——這是各自撰寫時的措辭習慣，不是刻意的兩套命名法，
    比對時要互通，不然 active_address 的 confirms=hash-rate 永遠對不上任何卡片。"""
    return token.strip().lower().replace("-", "_")


def _build_evidence_graph(cards: list[dict]) -> dict:
    """對應 `Stage 6 — Evidence Graph/design.md` 的建圖規則：只把 Stage 3
    Knowledge 已經寫好的 confirms／conflicts／independent 畫成圖，不重新判斷
    任何關係。分成三部分回傳：
    - nodes：這批卡片本身，`isolated` 標記這張卡在這批圖裡有沒有連到任何邊
    - edges：兩端都在這批卡片裡的關係
    - referenced_but_no_card：Stage 3 Knowledge 提到、但這批查詢沒有對應卡片的
      關聯 factor（例：funding_rate 的 confirms=open_interest，這批只查了
      funding_rate/active_address/cpi/liquidation 四個，open_interest 不在裡面）——
      這種關係「是真的」，只是這次沒有一起分析，不能略過不提，也不能編一個假節點
    """
    by_factor = {c["factor"]: c for c in cards}
    connected: set[str] = set()
    edges: list[dict] = []
    referenced_but_no_card: list[dict] = []

    for card in cards:
        related = card.get("related_evidence") or {}
        for relation in ("confirms", "conflicts", "independent"):
            relation_label = {"confirms": "supports", "conflicts": "conflicts", "independent": "independent"}[relation]
            for name in _parse_related_factor_names(related.get(relation)):
                target_factor = next(
                    (f for f in by_factor if _normalize_factor_token(f) == _normalize_factor_token(name)),
                    None,
                )
                if target_factor is None:
                    referenced_but_no_card.append({
                        "from": card["evidence_id"],
                        "relation": relation_label,
                        "referenced_factor": name,
                    })
                    continue
                if target_factor == card["factor"]:
                    continue  # 防呆：不該發生，但不要讓自我關係畫成一條邊
                edges.append({
                    "from": card["evidence_id"],
                    "to": by_factor[target_factor]["evidence_id"],
                    "relation": relation_label,
                })
                connected.add(card["evidence_id"])
                connected.add(by_factor[target_factor]["evidence_id"])

    nodes = [
        {
            "evidence_id": c["evidence_id"],
            "factor": c["factor"],
            "category": c.get("category"),
            "isolated": c["evidence_id"] not in connected,
        }
        for c in cards
    ]

    return {"nodes": nodes, "edges": edges, "referenced_but_no_card": referenced_but_no_card}


@app.post("/api/stage6")
async def stage6_graph(req: Stage5FundingRequest):
    """Stage 6 Evidence Graph：吃 Stage 5 排序後的卡片，畫出彼此的關係——這一層
    不重新判斷任何關係，只是把 Stage 3 Knowledge 已經寫好的 confirms／conflicts／
    independent 組裝成圖（跟 Stage 5 是「組裝層」同一種精神）。內部直接呼叫
    `stage5_all`（同一個 process，不是另外發 HTTP request），不重複抓一次資料。

    已知會出現的兩種誠實缺口（見 `Stage 6 — Evidence Graph/design.md`）：
    - `referenced_but_no_card`：Stage 3 Knowledge 提到的關聯 factor（例如
      open_interest／hash-rate／price）這批查詢沒有對應卡片，不會畫成邊，但
      會列出來，不是關係不存在，是這次沒有一起分析
    - cpi 這張卡自己永遠不會發出邊：Event Knowledge 的關係欄位（`usually_affects`／
      `related_events`）跟 Statistical／Sentiment Knowledge 的 `confirms`／
      `conflicts`／`independent` 不是同一組 key，Stage 5 組裝時對 cpi 讀不到，
      這是已知的 schema 落差，這裡不繞過去湊一條邊——但 cpi 不一定是孤立節點，
      別的卡片（例如 liquidation.independent）可能反過來指向它
    """
    with _capture_log() as run_log:
        # 直接呼叫實作而非端點函式：端點那層會再包一次 execution_log 進回應，
        # 這裡只需要卡片本身，紀錄靠共用的收集區塊自然併進來。
        stage5_result = await _stage5_impl(req)
        with _timed(
            "stage6_build_graph",
            "依 Stage 3 Knowledge 的 confirms／conflicts／independent 建圖（不重新判斷關係）",
            phase="reason",
            layer="S6_evidence_graph",
        ):
            graph = _build_evidence_graph(stage5_result["evidence_cards"])
        isolated = sum(1 for n in graph["nodes"] if n["isolated"])
        _log(
            "stage6_graph_built",
            f"{len(graph['nodes'])} 節點／{len(graph['edges'])} 邊／"
            f"{len(graph['referenced_but_no_card'])} 條指向未分析 factor／{isolated} 個孤立節點",
            phase="reason",
            layer="S6_evidence_graph",
            metrics={
                "nodes": len(graph["nodes"]),
                "edges": len(graph["edges"]),
                "referenced_but_no_card": len(graph["referenced_but_no_card"]),
                "isolated_nodes": isolated,
            },
        )
        return {
            "coin": stage5_result["coin"],
            "horizon": stage5_result["horizon"],
            "evidence_cards": stage5_result["evidence_cards"],
            "graph": graph,
            "note": (
                f"{len(graph['edges'])} 條邊（兩端都在這批卡片裡）、"
                f"{len(graph['referenced_but_no_card'])} 條關係指向這批沒有分析的 factor、"
                f"{isolated} 個孤立節點。"
            ),
            "execution_log": run_log,
        }

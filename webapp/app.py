"""簡易 Web UI：輸入幣種／題目，執行同一套 run_pipeline()，顯示報告並提供下載。

與 CLI（main.py）共用 agent/orchestrator.py 的 run_pipeline()，
不會有兩套分析邏輯。用於 Live Demo 展示，非正式比賽執行方式
（正式執行仍以現場 CLI 一次執行為準）。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

import markdown as md
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from markupsafe import Markup

from agent.collectors.coin_map import SUPPORTED_COINS
from agent.integrity import assess_integrity
from agent.orchestrator import run_pipeline
from agent.reasoning.consistency import normalize_nested_consistency
from agent.report.text_formatting import normalize_embedded_lists
from agent.schemas import Evidence

BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = Path("output") / "webapp_runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_DOWNLOAD_FILENAMES = {
    "report.md",
    "evidence.json",
    "execution_log.jsonl",
    "report_view.json",
    "validation_results.json",
    "research_context.json",
    "report.html",
    "evidence.html",
    "execution_log.html",
    "deliverables.html",
}

# --- 公開部署的濫用防護（2026-08-01）------------------------------------
# 這個服務架在**主辦方的 AWS 帳號**上、無認證對外開放，而每次真實執行約
# 7 萬 tokens、4-6 分鐘。沒有防護的話，一支掃描機器人就能持續燒主辦方的錢，
# 或用並發請求把 t3.small 打垮。以下三道限制只擋真實執行，dry-run 不受影響
# （0.7 秒、不呼叫 Bedrock、零成本），評審要試玩隨時可以。

# 題目長度上限。命題範例題型都在 50 字以內，300 字已經很寬鬆；
# 沒有上限的話可以塞一大段文字進 prompt 灌爆 token 用量。
MAX_QUESTION_CHARS = 300

# 同時間只准一個真實執行。t3.small 跑一次就吃滿，並發只會讓大家一起逾時，
# 不如讓後來者拿到明確的「稍後再試」而不是轉圈圈轉到斷線。
#
# **用「持有者開始時間」而不是 Semaphore**：2026-08-01 實測踩到——用 Semaphore 時，
# 客戶端在執行途中斷線（會場網路很常見）會讓名額洩漏，之後**所有人**都拿到
# 「已有分析在執行」而實際上沒有，只能重啟服務才能恢復。評審時發生等於 demo 直接死。
# 改記下開始時間後，超過上限就視為前一位已經不在，自動接手——會自癒，不需人工介入。
MAX_RUN_SECONDS = 900  # 命題硬性上限即 15 分鐘，超過必然已結束或已失敗
_active_run_started_at: float | None = None
_slot_lock = threading.Lock()


def _acquire_run_slot() -> bool:
    """取得真實執行名額。前一位超過 MAX_RUN_SECONDS 未釋放時視為已消失並接手。"""
    global _active_run_started_at
    now = time.monotonic()
    with _slot_lock:
        started = _active_run_started_at
        if started is not None and (now - started) < MAX_RUN_SECONDS:
            return False
        _active_run_started_at = now
        return True


def _release_run_slot() -> None:
    global _active_run_started_at
    with _slot_lock:
        _active_run_started_at = None

# 同一 IP 兩次真實執行的間隔。評審看完一次結果再想下一題不只五分鐘，
# 但足以擋掉自動化連打。
REAL_RUN_COOLDOWN_SECONDS = 300
_last_real_run_by_ip: dict[str, float] = {}
_cooldown_lock = threading.Lock()

# 冷卻豁免名單：現場／評審端的對外 NAT IP。
#
# 為什麼需要這個：cooldown 是「每個 IP」計算的，用意是擋自動化連打。但評審多半
# 共用同一組會場出口 IP——五分鐘限一次會變成「所有評審加起來五分鐘只能跑一次」，
# 把防濫用機制變成擋住正常使用者的東西。
#
# **只豁免 cooldown，不豁免全站單一併發鎖**（`_acquire_run_slot`）：那道不是防濫用，
# 是真的資源限制——一次真實執行 4-6 分鐘、7 次 Bedrock 呼叫，多人同時跑會互相
# 拖慢甚至撞上 15 分鐘上限。豁免它反而會讓現場更容易出事。
#
# 可用 `REAL_RUN_COOLDOWN_EXEMPT_IPS`（逗號分隔）追加，不必改程式碼重新部署。
_DEFAULT_EXEMPT_IPS = {
    "60.250.15.18", "60.250.15.19",
    "60.250.15.34", "60.250.15.35", "60.250.15.36",
    "60.250.15.50", "60.250.15.51", "60.250.15.52",
}
COOLDOWN_EXEMPT_IPS = _DEFAULT_EXEMPT_IPS | {
    ip.strip()
    for ip in os.getenv("REAL_RUN_COOLDOWN_EXEMPT_IPS", "").split(",")
    if ip.strip()
}


def _client_ip(request: Request) -> str:
    """取請求來源 IP。目前直接對外沒有反向代理，client.host 就是真實來源。"""
    return request.client.host if request.client else "unknown"


def _check_real_run_allowed(ip: str) -> str | None:
    """真實執行的冷卻檢查。可執行回 None，否則回要顯示給使用者的理由。"""
    now = time.monotonic()
    if ip in COOLDOWN_EXEMPT_IPS:
        # 仍然記錄時間戳：豁免的是「被擋」，不是「不留紀錄」——之後若要回頭看
        # 現場實際打了幾次，這個字典是唯一的依據。
        with _cooldown_lock:
            _last_real_run_by_ip[ip] = now
        return None
    with _cooldown_lock:
        last = _last_real_run_by_ip.get(ip)
        if last is not None and (now - last) < REAL_RUN_COOLDOWN_SECONDS:
            wait = int(REAL_RUN_COOLDOWN_SECONDS - (now - last))
            return (
                f"真實執行每 {REAL_RUN_COOLDOWN_SECONDS // 60} 分鐘限一次"
                f"（本服務執行於主辦方 AWS 帳號，需節制用量），請於 {wait} 秒後再試。"
                "想立即試用請改勾「快速模式」，它不呼叫 Bedrock、約 1 秒完成。"
            )
        _last_real_run_by_ip[ip] = now
    return None


def _clear_cooldown(ip: str) -> None:
    """真實執行沒能真的開始時，把剛記下的冷卻時間戳收回，不佔用配額。"""
    with _cooldown_lock:
        _last_real_run_by_ip.pop(ip, None)

app = FastAPI(title="HOYA BIT 加密市場分析 AI Agent")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _render_longtext(text: str) -> Markup:
    """四面板顯示 LLM 長文（market_judgment／bull_argument／bear_argument）用：
    跟 report.md 走同一套邏輯——當成 markdown 渲染，而不是把整段字串塞進
    <p> 讓瀏覽器把換行/清單/粗體全部吃掉變成一面文字牆。
    """
    if not text:
        return Markup("")
    html = md.markdown(normalize_embedded_lists(text), extensions=["extra", "sane_lists"])
    return Markup(html)


templates.env.filters["render_longtext"] = _render_longtext


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"coins": sorted(SUPPORTED_COINS)})


@app.post("/analyze", response_class=HTMLResponse)
def analyze(
    request: Request,
    coin: str = Form(...),
    question: str = Form(...),
    coin2: str = Form(""),
    dry_run: bool = Form(False),
    with_baseline: bool = Form(False),
):
    run_id = uuid.uuid4().hex[:8]
    out_dir = RUNS_DIR / run_id

    result = None
    error = None

    # --- 入口守門：先擋掉不合法與濫用的請求，再談執行 ---
    coin_uc = coin.strip().upper()
    coin2_uc = coin2.strip().upper() if coin2.strip() else None
    guard: str | None = None

    if coin_uc not in SUPPORTED_COINS:
        guard = f"幣種僅支援命題指定的 {'／'.join(sorted(SUPPORTED_COINS))}，收到的是「{coin[:20]}」。"
    elif coin2_uc and coin2_uc not in SUPPORTED_COINS:
        guard = f"比較對象幣種僅支援 {'／'.join(sorted(SUPPORTED_COINS))}。"
    elif len(question.strip()) > MAX_QUESTION_CHARS:
        guard = f"題目請控制在 {MAX_QUESTION_CHARS} 字以內（目前 {len(question.strip())} 字）。"
    elif not question.strip():
        guard = "請輸入題目。"

    acquired = False
    ip = _client_ip(request)
    if guard is None and not dry_run:
        guard = _check_real_run_allowed(ip)
        if guard is None:
            # 拿不到名額就直接回覆，不要排隊等——排隊只會讓瀏覽器等到斷線
            acquired = _acquire_run_slot()
            if not acquired:
                _clear_cooldown(ip)  # 沒真的跑到，不該扣掉這次配額
                guard = (
                    "目前已有一個真實分析正在執行（每次約 4-6 分鐘），"
                    "同時間僅允許一個以確保執行品質。請稍後再試，"
                    "或改勾「快速模式」立即查看完整流程。"
                )

    if guard is not None:
        error = guard
    else:
        try:
            result = run_pipeline(
                coin=coin_uc,
                question=question,
                dry_run=dry_run,
                output_dir=str(out_dir),
                coin2=coin2_uc,
                with_baseline=with_baseline,
            )
        except Exception as exc:  # noqa: BLE001
            # Web UI 是展示用途，任何未預期例外都應顯示錯誤頁面而非讓伺服器 500，
            # 真正的失敗容錯（collector/LLM 步驟）已經在 orchestrator 內處理。
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if acquired:
                _release_run_slot()

    # 報告分頁改為排版化 HTML 顯示（僅供 Web UI 呈現，report.md 交付檔本身不受影響）
    report_html: str = ""
    if result is not None:
        # toc extension：即使不插入 [TOC] 標記，也會替每個標題自動加 id，
        # 供前端產生「跳到章節」導覽列與錨點捲動使用
        report_html = md.markdown(
            result.report_markdown, extensions=["extra", "sane_lists", "toc"]
        )

    # Read execution log entries and view metrics for template tabs
    log_entries: list[dict] = []
    view_metrics: dict = {}
    view_data: dict = {}
    raw_log: str = ""

    log_path = out_dir / "execution_log.jsonl"
    if log_path.exists():
        raw_log = log_path.read_text(encoding="utf-8")
        for line in raw_log.strip().split("\n"):
            if line.strip():
                log_entries.append(json.loads(line))

    view_path = out_dir / "report_view.json"
    if view_path.exists():
        view_data = json.loads(view_path.read_text(encoding="utf-8"))
        view_meta = view_data.get("meta", {})
        # RunMetrics 本身沒有 generated_at（它是 meta 的手足欄位，不在 metrics 裡），
        # 這裡併進同一個 dict 讓模板只需讀一份 view_metrics
        view_metrics = {**view_meta.get("metrics", {}), "generated_at": view_meta.get("generated_at", "")}

    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "run_id": run_id,
            "coin": coin.upper(),
            "coin2": coin2.upper() if coin2 else None,
            "question": question,
            "result": result,
            "report_html": report_html,
            "error": error,
            "log_entries": log_entries,
            "view_metrics": view_metrics,
            "view_data": view_data,
            "raw_log": raw_log,
        },
    )


@app.get("/view/{run_id}", response_class=HTMLResponse)
def view_panel(request: Request, run_id: str):
    safe_run_id = "".join(c for c in run_id if c.isalnum())
    view_path = RUNS_DIR / safe_run_id / "report_view.json"
    if not view_path.exists():
        return HTMLResponse("Report view not found", status_code=404)
    view_data = json.loads(view_path.read_text(encoding="utf-8"))

    # v1.1 向後相容：既有四份真實 Demo 產於一致性／PARTIAL 護欄之前。
    # 歷史檔案保持原樣，但顯示時用同一份 evidence 重新判定，避免舊畫面繼續
    # 顯示「缺整類資料卻 INTACT」或已知的事件月份換算矛盾。
    evidence_path = RUNS_DIR / safe_run_id / "evidence.json"
    if evidence_path.exists():
        evidences = [
            Evidence.model_validate(item)
            for item in json.loads(evidence_path.read_text(encoding="utf-8"))
        ]
        view_data, _ = normalize_nested_consistency(view_data, evidences)
        coins = [view_data.get("meta", {}).get("coin", "")]
        coin2 = view_data.get("meta", {}).get("coin2")
        if coin2:
            coins.append(coin2)
        assessment = assess_integrity(evidences, [coin for coin in coins if coin])
        current_status = view_data.get("meta", {}).get("metrics", {}).get("integrity_status")
        if current_status != "DEGRADED" and assessment.status != "INTACT":
            view_data["meta"]["metrics"]["integrity_status"] = assessment.status
            view_data["meta"]["metrics"]["degraded_reasons"] = assessment.reasons
            view_data["panel4_report"]["integrity_status"] = assessment.status
            view_data["panel4_report"]["degraded_reasons"] = assessment.reasons
    return templates.TemplateResponse(request, "view.html", {"run_id": run_id, "view": view_data})


@app.get("/download/{run_id}/{filename}")
def download(run_id: str, filename: str):
    if filename not in ALLOWED_DOWNLOAD_FILENAMES:
        return HTMLResponse("Not found", status_code=404)
    # run_id 由伺服器端 uuid4 產生，但仍做基本防護避免路徑穿越
    safe_run_id = "".join(c for c in run_id if c.isalnum())
    path = RUNS_DIR / safe_run_id / filename
    if not path.exists():
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(path, filename=filename)

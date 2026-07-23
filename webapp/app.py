"""簡易 Web UI：輸入幣種／題目，執行同一套 run_pipeline()，顯示報告並提供下載。

與 CLI（main.py）共用 agent/orchestrator.py 的 run_pipeline()，
不會有兩套分析邏輯。用於 Live Demo 展示，非正式比賽執行方式
（正式執行仍以現場 CLI 一次執行為準）。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import markdown as md
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agent.collectors.coin_map import SUPPORTED_COINS
from agent.orchestrator import run_pipeline

BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = Path("output") / "webapp_runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_DOWNLOAD_FILENAMES = {"report.md", "evidence.json", "execution_log.jsonl", "report_view.json"}

app = FastAPI(title="HOYA BIT 加密市場分析 AI Agent")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


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
    try:
        result = run_pipeline(
            coin=coin.upper(),
            question=question,
            dry_run=dry_run,
            output_dir=str(out_dir),
            coin2=coin2.upper() if coin2 else None,
            with_baseline=with_baseline,
        )
    except Exception as exc:  # noqa: BLE001
        # Web UI 是展示用途，任何未預期例外都應顯示錯誤頁面而非讓伺服器 500，
        # 真正的失敗容錯（collector/LLM 步驟）已經在 orchestrator 內處理。
        error = f"{type(exc).__name__}: {exc}"

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

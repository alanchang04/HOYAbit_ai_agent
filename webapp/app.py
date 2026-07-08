"""簡易 Web UI：輸入幣種／題目，執行同一套 run_pipeline()，顯示報告並提供下載。

與 CLI（main.py）共用 agent/orchestrator.py 的 run_pipeline()，
不會有兩套分析邏輯。用於 Live Demo 展示，非正式比賽執行方式
（正式執行仍以現場 CLI 一次執行為準）。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agent.collectors.coin_map import SUPPORTED_COINS
from agent.orchestrator import run_pipeline

BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = Path("output") / "webapp_runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_DOWNLOAD_FILENAMES = {"report.md", "evidence.json", "execution_log.jsonl"}

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
        )
    except Exception as exc:  # noqa: BLE001
        # Web UI 是展示用途，任何未預期例外都應顯示錯誤頁面而非讓伺服器 500，
        # 真正的失敗容錯（collector/LLM 步驟）已經在 orchestrator 內處理。
        error = f"{type(exc).__name__}: {exc}"

    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "run_id": run_id,
            "coin": coin.upper(),
            "coin2": coin2.upper() if coin2 else None,
            "question": question,
            "result": result,
            "error": error,
        },
    )


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

"""將正式交付物輸出成可離線閱讀的 HTML。

HTML 是評審閱讀介面，不取代 report.md、evidence.json、execution_log.jsonl
這三份權威／機器可讀交付物。所有頁面皆內嵌樣式，不依賴 Web 服務或外部資源。
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import markdown as md

from agent.schemas import Evidence, LogEntry


_STYLE = """
:root { color-scheme: light; --ink:#172033; --muted:#627087; --line:#dce3ec;
  --brand:#3157d5; --paper:#fff; --wash:#f4f7fb; --ok:#147d64; }
* { box-sizing:border-box; }
body { margin:0; background:var(--wash); color:var(--ink); font:15px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { width:min(1120px,calc(100% - 32px)); margin:32px auto; background:var(--paper);
  padding:clamp(24px,5vw,56px); border:1px solid var(--line); border-radius:18px; box-shadow:0 10px 35px #1c2e4f14; }
h1,h2,h3 { line-height:1.25; } h1 { margin-top:0; } h2 { margin-top:2em; border-bottom:1px solid var(--line); padding-bottom:.35em; }
a { color:var(--brand); } code { background:#eef2f8; padding:.12em .35em; border-radius:4px; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; background:#111a2b; color:#edf2ff; padding:16px; border-radius:10px; }
table { width:100%; border-collapse:collapse; margin:18px 0; font-size:14px; }
th,td { border:1px solid var(--line); padding:9px 11px; text-align:left; vertical-align:top; overflow-wrap:anywhere; }
th { background:#eef3fa; } tr:nth-child(even) td { background:#fafbfd; }
.meta { color:var(--muted); margin:-8px 0 28px; } .notice { border-left:4px solid var(--brand); background:#eef3ff; padding:12px 16px; border-radius:6px; }
.pill { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:1px 8px; margin:2px; font-size:12px; }
.ok { color:var(--ok); font-weight:700; } .error { color:#b42318; font-weight:700; }
.cards { display:grid; gap:14px; } .card { border:1px solid var(--line); border-radius:12px; padding:16px; }
.card h2 { margin:.1em 0 .6em; border:0; padding:0; font-size:18px; }
.kv { display:grid; grid-template-columns:minmax(130px,180px) 1fr; gap:5px 14px; }
.kv dt { color:var(--muted); font-weight:600; } .kv dd { margin:0; overflow-wrap:anywhere; }
.deliverable { display:grid; grid-template-columns:minmax(160px,220px) 1fr; gap:14px; padding:15px 0; border-bottom:1px solid var(--line); }
@media (max-width:700px) { main { width:100%; margin:0; border:0; border-radius:0; padding:22px 16px; } .kv,.deliverable { grid-template-columns:1fr; } table { display:block; overflow-x:auto; } }
@media print { body { background:#fff; } main { width:100%; margin:0; border:0; box-shadow:none; } }
"""


def _e(value: Any) -> str:
    if value is None:
        return "—"
    return html.escape(str(value))


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} else None


def _link(value: str | None, label: str | None = None) -> str:
    safe = _safe_url(value)
    if safe is None:
        return _e(value)
    return f'<a href="{html.escape(safe, quote=True)}" rel="noopener noreferrer">{_e(label or safe)}</a>'


def _page(title: str, body: str, metadata: dict[str, Any]) -> str:
    generated = metadata.get("generated_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    descriptor = " · ".join(
        _e(value) for value in (metadata.get("coin"), metadata.get("coin2"), metadata.get("integrity_status")) if value
    )
    return (
        "<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(title)}</title><style>{_STYLE}</style></head><body><main>"
        f"<h1>{_e(title)}</h1><p class=\"meta\">{descriptor}<br>產生時間：{_e(generated)}</p>"
        f"{body}</main></body></html>"
    )


def _render_report(report_markdown: str) -> str:
    # 先 escape LLM／外部資料可能帶入的 raw HTML，再交給 Markdown 產生安全的結構標籤。
    escaped = html.escape(report_markdown)
    rendered = md.markdown(escaped, extensions=["extra", "sane_lists", "toc"])
    # Markdown link 語法仍可能攜帶 javascript:；只保留 http(s)、相對路徑與頁內錨點。
    def clean_href(match: re.Match[str]) -> str:
        quote, value = match.group(1), html.unescape(match.group(2)).strip()
        parsed = urlparse(value)
        if parsed.scheme and parsed.scheme not in {"http", "https"}:
            return f'href={quote}#{quote}'
        return match.group(0)

    return re.sub(r'href=(["\'])(.*?)\1', clean_href, rendered, flags=re.IGNORECASE)


def _evidence_body(evidences: list[Evidence]) -> str:
    cards: list[str] = [
        '<p class="notice">此頁是 <code>evidence.json</code> 的閱讀版；稽核與程式處理請以原始 JSON 為準。</p>',
        f"<p>共 <strong>{len(evidences)}</strong> 筆證據。</p>",
        '<div class="cards">',
    ]
    for evidence in evidences:
        item = evidence.model_dump(mode="json")
        source_url = item.get("reference_url") or item.get("source_url")
        window = " → ".join(str(v) for v in (item.get("window_start"), item.get("window_end")) if v) or "—"
        cards.append(
            '<section class="card">'
            f'<h2>{_e(item["id"])} · {_e(item["source_type"])}</h2>'
            '<dl class="kv">'
            f'<dt>幣種</dt><dd>{_e(item["coin"])}</dd>'
            f'<dt>來源</dt><dd>{_e(item["source"])} · {_link(source_url, "開啟來源")}</dd>'
            f'<dt>擷取時間</dt><dd>{_e(item["fetched_at"])}</dd>'
            f'<dt>資料窗</dt><dd>{_e(window)} <span class="pill">{_e(item.get("horizon_class"))}</span></dd>'
            f'<dt>來源權重</dt><dd>{_e(item.get("source_weight"))} — {_e(item.get("weight_reason"))}</dd>'
            f'<dt>內容</dt><dd>{_e(item["content_reference"])}</dd>'
            f'<dt>關聯主張</dt><dd>{_e(item["related_claim"])}</dd>'
            '</dl></section>'
        )
    cards.append("</div>")
    return "".join(cards)


def _log_body(entries: list[LogEntry]) -> str:
    rows: list[str] = []
    for entry in entries:
        item = entry.model_dump(mode="json")
        status = item["status"]
        metrics = json.dumps(item.get("metrics") or {}, ensure_ascii=False, sort_keys=True)
        rows.append(
            "<tr>"
            f'<td>{_e(item["ts"])}</td><td>{_e(item["phase"])}</td>'
            f'<td>{_e(item["action"])}</td><td class="{_e(status)}">{_e(status)}</td>'
            f'<td>{_e(item.get("detail"))}</td><td><code>{_e(metrics)}</code></td>'
            "</tr>"
        )
    return (
        '<p class="notice">此頁是 <code>execution_log.jsonl</code> 的閱讀版；逐行事件原始值以 JSONL 為準。</p>'
        f"<p>共 <strong>{len(entries)}</strong> 筆事件，包含完整 <code>pipeline_end</code>。</p>"
        "<table><thead><tr><th>時間</th><th>階段</th><th>動作</th><th>狀態</th><th>細節</th><th>指標</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _index_body(metadata: dict[str, Any]) -> str:
    question = metadata.get("question")
    question_html = f"<h2>本次題目</h2><p>{_e(question)}</p>" if question else ""
    return (
        '<p class="notice"><strong>交付原則：</strong>HTML 是離線閱讀副本，不會取代命題要求的原始／機器可讀檔。</p>'
        f"{question_html}<h2>評審交付物對照</h2>"
        '<div class="deliverable"><strong>Final Report</strong><div><a href="report.md">report.md</a>（權威原檔） · <a href="report.html">report.html</a>（閱讀版）</div></div>'
        '<div class="deliverable"><strong>Evidence List</strong><div><a href="evidence.json">evidence.json</a>（權威原檔） · <a href="evidence.html">evidence.html</a>（閱讀版）</div></div>'
        '<div class="deliverable"><strong>Execution Log</strong><div><a href="execution_log.jsonl">execution_log.jsonl</a>（權威原檔） · <a href="execution_log.html">execution_log.html</a>（閱讀版）</div></div>'
        '<div class="deliverable"><strong>Interactive View</strong><div><a href="report_view.json">report_view.json</a>；啟動 Web UI 後可使用四面板檢視。</div></div>'
        '<div class="deliverable"><strong>Validation Audit</strong><div><a href="validation_results.json">validation_results.json</a>（逐筆 Validation Certificate） · <a href="research_context.json">research_context.json</a>（Structured Features／Knowledge／Evidence Graph）。</div></div>'
        '<div class="deliverable"><strong>Reproducibility</strong><div><a href="run_manifest.json">run_manifest.json</a>（版本、模型、非機密設定、資料/API/產物指紋）。</div></div>'
        '<div class="deliverable"><strong>Source / Config</strong><div>由 GitHub repository、<code>README.md</code>、<code>.env.example</code> 與原始碼樹交付；不複製成 HTML，避免與可執行版本分叉。</div></div>'
        '<h2>決賽提交包（命題文件第 3 頁）</h2>'
        '<div class="deliverable"><strong>1. 提案簡報</strong><div>內容底稿為 repository 的 <code>PITCH_REFERENCE.md</code>；正式提交仍應匯出為投影片或 PDF，並包含解題方向、AI 技術、數據應用與 AWS 架構圖。</div></div>'
        '<div class="deliverable"><strong>2. Live Demo / 影片</strong><div>提交已部署網址與現場完整執行錄影連結。兩者是 URL／影片，不以本 HTML 取代。</div></div>'
        '<div class="deliverable"><strong>3. GitHub</strong><div>提交完整 repository 連結，包含原始碼、設定範例與執行說明。</div></div>'
        '<div class="deliverable"><strong>4. 數據與資源</strong><div>本資料夾即包含 Final Report、Evidence List、Execution Log 與其 HTML 閱讀版；提交時整包保留。</div></div>'
    )


def export_html_bundle(
    out_dir: str | Path,
    report_markdown: str,
    evidences: list[Evidence],
    log_entries: list[LogEntry],
    metadata: dict[str, Any] | None = None,
) -> list[Path]:
    """輸出四個 standalone HTML，回傳寫入路徑。"""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    meta = dict(metadata or {})
    pages = {
        "report.html": _page("Final Report", _render_report(report_markdown), meta),
        "evidence.html": _page("Evidence List", _evidence_body(evidences), meta),
        "execution_log.html": _page("Execution Log", _log_body(log_entries), meta),
        "deliverables.html": _page("評審交付物索引", _index_body(meta), meta),
    }
    paths: list[Path] = []
    for filename, content in pages.items():
        path = target / filename
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths

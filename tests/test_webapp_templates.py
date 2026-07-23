"""Webapp 模板渲染回歸測試。

背景：view.html 曾因 Jinja 的 `dict.items` 屬性/方法解析衝突（`view.panel1_raw_feed.items`
會解析到 dict 內建方法而非 "items" key）在真實路由上 500，但既有測試只驗證
report_view.json 內容、從未實際渲染模板，因此漏接。本檔用 TestClient 走真實
路由確保 result.html 與 view.html 都渲染得出來。
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from webapp.app import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def dry_run_result(client: TestClient) -> dict:
    """跑一次 dry-run 分析（含 baseline），回傳 run_id 與 result 頁 HTML。"""
    resp = client.post(
        "/analyze",
        data={
            "coin": "BTC",
            "question": "BTC short-term outlook based on multiple sources",
            "dry_run": "true",
            "with_baseline": "true",
        },
    )
    assert resp.status_code == 200
    match = re.search(r"view/([a-z0-9]+)", resp.text)
    assert match, "result 頁應含四面板連結 /view/{run_id}"
    return {"run_id": match.group(1), "html": resp.text}


def test_index_renders(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200


def test_result_page_renders(dry_run_result: dict) -> None:
    assert "報告" in dry_run_result["html"]


def test_result_page_stat_cards_not_na(dry_run_result: dict) -> None:
    """回歸測試：result.html 的 stat-grid 曾因 view_metrics key 打錯
    （模板讀 confidence_score，RunMetrics 實際欄位是 confidence；且
    generated_at 誤讀成 metrics 的子欄位）靜默顯示 N/A，未被任何測試攔到。"""
    html = dry_run_result["html"]
    assert "N/A%" not in html
    assert "N/A" not in re.search(r'<span class="stat-label">信心</span>.*?</span>', html, re.S).group()

    # report.md 已渲染成排版化 HTML，不應殘留原始 markdown 語法符號
    body = re.search(r'id="report-body">(.*?)</div>\s*</div>', html, re.S)
    assert body is not None
    assert "##" not in body.group(1)
    assert "<h2 " in body.group(1)  # toc extension 加了 id 屬性，標題不再是裸 <h2>


def test_view_page_renders_four_panels(client: TestClient, dry_run_result: dict) -> None:
    """四面板頁必須渲染成功（曾因 dict.items 衝突 500）。"""
    resp = client.get(f"/view/{dry_run_result['run_id']}")
    assert resp.status_code == 200

    html = resp.text
    assert "原始證據流" in html
    assert "信任提煉流水線" in html
    # R12 改版後的新區塊
    assert "Phase 2 去重" in html
    assert "F9 情緒分布（詞典法）" in html
    # 面板①的證據項目有實際渲染（非空面板）
    assert "fingerprint-badge" in html


def test_view_page_unknown_run_id_404(client: TestClient) -> None:
    resp = client.get("/view/doesnotexist")
    assert resp.status_code == 404


def _render_view_html(view: dict) -> str:
    """直接以 webapp 的 Jinja 設定渲染 view.html（dry-run 不會產生多輪辯論，
    故手構 view dict 走模板本身）。"""
    from webapp.app import templates

    template = templates.env.get_template("view.html")
    return template.render(run_id="test", view=view)


def _minimal_view(l5_debate: dict) -> dict:
    """組一個能讓 view.html 渲染的最小 view，只關心面板③ L5 的辯論區塊。"""
    return {
        "meta": {"coin": "BTC", "coin2": None, "question": "q", "question_type": "multi_source",
                 "generated_at": "2026-07-23", "metrics": {"confidence": 58,
                 "noise_removal_rate": 0.1, "integrity_status": "INTACT", "total_tokens": 100}},
        "panel1_raw_feed": {"count": 0, "items": []},
        "panel2_naive_baseline": {"enabled": False, "steps": []},
        "panel3_refinement": {
            "noise_removal_rate": 0.1,
            "skipped_layers": [],
            "log_events_by_layer": {},
            "layers": [{
                "layer": "L5_conclusion",
                "confidence_breakdown": {"base": 35, "auth_bonus": 0,
                    "contradiction_penalty": 0, "gap_penalty": 0, "final": 58},
                "debate": l5_debate,
            }],
        },
        "panel4_report": {"integrity_status": "INTACT", "degraded_reasons": [],
            "confidence": 58, "market_judgment": "x", "summary": {"has_debate": False},
            "core_facts": [], "bullish_evidence": [], "risk_evidence": [],
            "limitations": [], "invalidation_conditions": [], "follow_up_watchpoints": []},
    }


def test_view_html_renders_multi_round_debate() -> None:
    """多輪辯論：面板③ L5 應逐輪渲染，並顯示輪數與收斂原因（缺口一）。"""
    debate = {
        "bull": "最後一輪多方", "bear_critique": "最後一輪批評", "bear": "最後一輪空方",
        "round_count": 2, "stopped_reason": "converged",
        "stopped_reason_label": "反方自認已無新的實質論點，辯論提前收斂",
        "rounds": [
            {"round": 1, "bull": "第一輪多方論點", "bear_critique": "第一輪批評", "bear": "第一輪空方論點"},
            {"round": 2, "bull": "第二輪多方論點", "bear_critique": "第二輪批評", "bear": "第二輪空方論點"},
        ],
    }
    html = _render_view_html(_minimal_view(debate))
    assert "共 2 輪" in html
    assert "提前收斂" in html
    assert "第 1 輪" in html and "第 2 輪" in html
    assert "第一輪多方論點" in html and "第二輪多方論點" in html


def test_view_html_falls_back_to_flat_debate_without_rounds() -> None:
    """無 rounds（單模型 fallback 或舊資料）時退回扁平單段顯示，不報錯。"""
    debate = {"bull": "多方論點", "bear_critique": "空方批評", "bear": "空方論點",
              "rounds": [], "round_count": 0, "stopped_reason": "", "stopped_reason_label": ""}
    html = _render_view_html(_minimal_view(debate))
    assert "多方論點" in html
    assert "共 " not in html  # 沒有多輪標頭
    assert "第 1 輪" not in html

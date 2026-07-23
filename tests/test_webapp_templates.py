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

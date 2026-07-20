"""合規檢查測試：R9 — 全部面板文案無投資建議語彙；INTACT=分析完整性。

驗收條件：
- 所有面板與 baseline 輸出 SHALL NOT 出現 buy/sell/hold/進場價/停損點/停利等投資建議語彙
- INTACT 語意 SHALL 為「分析完整性」
- 模板文案不含投資建議語彙
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent.orchestrator import run_pipeline
from agent.reasoning.baseline import BASELINE_SYSTEM_PROMPT, run_baseline_dry_run

# 禁止出現的投資建議語彙
FORBIDDEN_TERMS = [
    "buy",
    "sell",
    "hold",
    "進場價",
    "停損點",
    "停利",
    "建議買入",
    "建議賣出",
]

# 模板檔案路徑
TEMPLATE_DIR = Path(__file__).parent.parent / "webapp" / "templates"


def _collect_all_text_values(obj: object) -> list[str]:
    """遞迴取出 JSON 結構中所有字串值。"""
    texts: list[str] = []
    if isinstance(obj, str):
        texts.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            texts.extend(_collect_all_text_values(v))
    elif isinstance(obj, list):
        for item in obj:
            texts.extend(_collect_all_text_values(item))
    return texts


def _check_forbidden_terms(text: str) -> list[str]:
    """檢查文字中是否含有禁止的投資建議語彙。回傳命中的詞彙列表。"""
    found: list[str] = []
    text_lower = text.lower()
    for term in FORBIDDEN_TERMS:
        # 英文詞做 word boundary 比對；中文詞做子字串比對
        if term.isascii():
            # word boundary match for English terms
            if re.search(rf"\b{re.escape(term)}\b", text_lower):
                found.append(term)
        else:
            if term in text:
                found.append(term)
    return found


class TestReportViewCompliance:
    """dry-run pipeline 產出的 report_view.json 合規檢查。"""

    @pytest.fixture(scope="class")
    def view_data(self, tmp_path_factory: pytest.TempPathFactory) -> dict:
        """執行一次 dry-run pipeline，回傳 report_view.json 內容。"""
        tmp_path = tmp_path_factory.mktemp("compliance")
        run_pipeline(
            coin="BTC",
            question="分析 BTC 市場近期走勢與風險因素",
            dry_run=True,
            output_dir=str(tmp_path),
            with_baseline=True,
        )
        view_path = tmp_path / "report_view.json"
        assert view_path.exists(), "report_view.json 未產出"
        return json.loads(view_path.read_text(encoding="utf-8"))

    def test_panel1_no_forbidden_terms(self, view_data: dict) -> None:
        """panel1 原始證據流：無投資建議語彙。"""
        texts = _collect_all_text_values(view_data["panel1_raw_feed"])
        all_text = " ".join(texts)
        found = _check_forbidden_terms(all_text)
        assert found == [], f"panel1 含禁止語彙: {found}"

    def test_panel2_no_forbidden_terms(self, view_data: dict) -> None:
        """panel2 未過濾基準對照：無投資建議語彙。"""
        texts = _collect_all_text_values(view_data["panel2_naive_baseline"])
        all_text = " ".join(texts)
        found = _check_forbidden_terms(all_text)
        assert found == [], f"panel2 含禁止語彙: {found}"

    def test_panel3_no_forbidden_terms(self, view_data: dict) -> None:
        """panel3 信任提煉流水線：無投資建議語彙。"""
        texts = _collect_all_text_values(view_data["panel3_refinement"])
        all_text = " ".join(texts)
        found = _check_forbidden_terms(all_text)
        assert found == [], f"panel3 含禁止語彙: {found}"

    def test_panel4_no_forbidden_terms(self, view_data: dict) -> None:
        """panel4 分析報告：無投資建議語彙。"""
        texts = _collect_all_text_values(view_data["panel4_report"])
        all_text = " ".join(texts)
        found = _check_forbidden_terms(all_text)
        assert found == [], f"panel4 含禁止語彙: {found}"

    def test_integrity_status_means_completeness(self, view_data: dict) -> None:
        """INTACT 語意為「分析完整性」，只用於 integrity_status 欄位。"""
        # integrity_status 在 panel4 和 meta.metrics 中
        panel4_status = view_data["panel4_report"]["integrity_status"]
        meta_status = view_data["meta"]["metrics"]["integrity_status"]

        # 正常 dry-run 無失敗，應為 INTACT
        assert panel4_status == "INTACT"
        assert meta_status == "INTACT"

        # 檢查 INTACT 不出現在非 integrity_status 的文本欄位中
        # （排除 integrity_status 本身）
        all_texts = _collect_all_text_values(view_data)
        intact_occurrences = [
            t for t in all_texts
            if "INTACT" in t and t not in ("INTACT", "DEGRADED")
        ]
        # INTACT 若出現在其他文字中，應與「完整性」語境相關
        for text in intact_occurrences:
            assert "完整" in text or "integrity" in text.lower(), (
                f"INTACT 出現在非完整性語境: {text!r}"
            )


class TestBaselineCompliance:
    """baseline 相關合規。"""

    def test_baseline_prompt_forbids_investment_advice(self) -> None:
        """BASELINE_SYSTEM_PROMPT 明確禁止投資建議。"""
        assert "嚴禁" in BASELINE_SYSTEM_PROMPT
        assert "投資建議" in BASELINE_SYSTEM_PROMPT
        # prompt 中列出了禁止的詞彙
        for term in ["buy", "sell", "hold", "進場價", "停損點", "停利"]:
            assert term in BASELINE_SYSTEM_PROMPT, f"baseline prompt 未列出禁止詞 {term!r}"

    def test_baseline_dry_run_output_no_forbidden_terms(self) -> None:
        """dry-run baseline 輸出不含投資建議語彙。"""
        result = run_baseline_dry_run("分析 BTC 市場", coin="BTC")
        all_text = result.get("analysis", "") + " " + result.get("caveat", "")
        found = _check_forbidden_terms(all_text)
        assert found == [], f"baseline dry-run 輸出含禁止語彙: {found}"

    def test_baseline_dry_run_coin2_no_forbidden_terms(self) -> None:
        """雙幣 dry-run baseline 輸出不含投資建議語彙。"""
        result = run_baseline_dry_run("比較 BTC 與 ETH", coin="BTC", coin2="ETH")
        all_text = result.get("analysis", "") + " " + result.get("caveat", "")
        found = _check_forbidden_terms(all_text)
        assert found == [], f"baseline dry-run (coin2) 輸出含禁止語彙: {found}"


class TestTemplateCompliance:
    """HTML 模板靜態文案合規檢查。"""

    def test_view_html_no_forbidden_terms(self) -> None:
        """view.html 模板文案不含投資建議語彙。"""
        template_path = TEMPLATE_DIR / "view.html"
        assert template_path.exists(), f"模板不存在: {template_path}"
        content = template_path.read_text(encoding="utf-8")
        found = _check_forbidden_terms(content)
        assert found == [], f"view.html 含禁止語彙: {found}"

    def test_result_html_no_forbidden_terms(self) -> None:
        """result.html 模板文案不含投資建議語彙。"""
        template_path = TEMPLATE_DIR / "result.html"
        assert template_path.exists(), f"模板不存在: {template_path}"
        content = template_path.read_text(encoding="utf-8")
        found = _check_forbidden_terms(content)
        assert found == [], f"result.html 含禁止語彙: {found}"

    def test_view_html_integrity_label_is_completeness(self) -> None:
        """view.html 中 integrity_status 顯示為「完整性」。"""
        template_path = TEMPLATE_DIR / "view.html"
        content = template_path.read_text(encoding="utf-8")
        # 面板中 integrity_status 的顯示文字應與「完整性」相關
        assert "完整性" in content, "view.html 未使用「完整性」標籤描述 integrity_status"

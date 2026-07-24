"""test_text_formatting：驗證 LLM 長文內嵌編號列點的正規化邏輯。"""

from __future__ import annotations

import markdown as md
import pytest

from agent.report.text_formatting import normalize_embedded_lists


class TestNormalizeEmbeddedLists:
    def test_no_pattern_returns_original_text(self):
        text = "這是一段沒有編號列點的普通論述文字。"
        assert normalize_embedded_lists(text) == text

    def test_single_parenthetical_number_not_misdetected(self):
        """只有一個括號數字（如年份、單一註記）不應被誤判成列點。"""
        text = "根據 2026 年（1）季度數據顯示成長。"
        assert normalize_embedded_lists(text) == text

    def test_sequential_fullwidth_numbers_converted_to_ordered_list(self):
        text = "核心依據：（1）第一點內容；（2）第二點內容；（3）第三點內容。"
        result = normalize_embedded_lists(text)
        assert "1. 第一點內容" in result
        assert "2. 第二點內容" in result
        assert "3. 第三點內容" in result
        # 轉換後應能被 markdown 正確渲染成 <ol><li>
        html = md.markdown(result, extensions=["extra", "sane_lists"])
        assert html.count("<li>") == 3
        assert "<ol>" in html

    def test_non_sequential_numbers_not_converted(self):
        """括號數字不連續（缺 2）不視為列點結構，原文不動。"""
        text = "（1）第一點；（3）第三點，中間跳號。"
        assert normalize_embedded_lists(text) == text

    def test_two_independent_runs_both_converted(self):
        """同一段文字裡兩組各自從 1 開始的獨立編號序列都要處理。"""
        text = (
            "先回應批評：（1）回應一；（2）回應二。\n\n"
            "可能推翻條件：（1）條件一；（2）條件二；（3）條件三。"
        )
        result = normalize_embedded_lists(text)
        html = md.markdown(result, extensions=["extra", "sane_lists"])
        assert html.count("<ol>") == 2
        assert html.count("<li>") == 5

    def test_ascii_parens_also_supported(self):
        text = "重點：(1) 第一項；(2) 第二項。"
        result = normalize_embedded_lists(text)
        assert "1. 第一項" in result
        assert "2. 第二項" in result

    def test_preserves_existing_paragraph_breaks(self):
        """已存在的 \\n\\n 段落分隔應保留，讓 markdown 正確斷段。"""
        text = "第一段內容。\n\n第二段內容。"
        result = normalize_embedded_lists(text)
        html = md.markdown(result, extensions=["extra", "sane_lists"])
        assert html.count("<p>") == 2

    def test_empty_string(self):
        assert normalize_embedded_lists("") == ""

    def test_ordinal_transitions_broken_into_paragraphs(self):
        """有些論述完全不用括號數字，改用中文序數詞（首先/其次/第三...）
        當分點標記，整段話一個換行都沒有——這種也要斷段。"""
        text = (
            "市場狀態脆弱。首先，價格加速下跌。其次，量能持續放大。"
            "第三，資金費率轉負。"
        )
        result = normalize_embedded_lists(text)
        html = md.markdown(result, extensions=["extra", "sane_lists"])
        assert html.count("<p>") == 4
        assert "首先，價格加速下跌" in result
        assert "其次，量能持續放大" in result

    def test_ordinal_word_mid_sentence_not_misdetected(self):
        """序數詞出現在句子中間（前面不是句號）不應被誤判成分點標記。"""
        text = "這是關於第三方支付平台的分析，首先聲明立場中立。"
        assert normalize_embedded_lists(text) == text

    def test_real_bear_argument_no_newlines_gets_paragraph_breaks(self):
        """實測過的真實情境：反方論證完全沒有換行，用六個中文序數詞分點，
        結尾還接一組全形括號的推翻條件清單——兩種模式要同時處理。"""
        text = (
            "市場脆弱。首先，價格下跌。其次，量能放大。第三，資金費率轉負。"
            "第四，情緒指標轉差。第五，技術面破位。第六，缺乏催化劑。"
            "可能推翻條件：（1）價格站上關鍵均線；（2）資金費率轉正；（3）情緒好轉。"
        )
        result = normalize_embedded_lists(text)
        html = md.markdown(result, extensions=["extra", "sane_lists"])
        assert html.count("<p>") >= 7  # 開頭 + 六個序數段落
        assert html.count("<ol>") == 1
        assert html.count("<li>") == 3

    def test_real_bedrock_output_pattern(self):
        """實測過的真實 Bedrock 輸出結構：一組全形括號列點接一段 --- 分隔線，
        後面接原生 markdown「1. 」清單——兩種列點語法混用在同一段文字裡。"""
        text = (
            "針對批評逐項回應：\n\n"
            "（1）第一項回應。\n\n"
            "（2）第二項回應。\n\n"
            "---\n\n"
            "**已知限制**\n\n"
            "1. 限制一。\n\n"
            "2. 限制二。\n\n"
            "3. 限制三。"
        )
        result = normalize_embedded_lists(text)
        html = md.markdown(result, extensions=["extra", "sane_lists"])
        assert html.count("<ol>") == 2
        assert html.count("<li>") == 5
        assert "<hr" in html
        assert "<strong>已知限制</strong>" in html

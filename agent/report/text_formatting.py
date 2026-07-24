"""LLM 生成長文的顯示層易讀性處理。

LLM 產出的論述文字（market_judgment／bull_argument／bear_argument）其實
已經有段落換行、**粗體小標題**、甚至標準 markdown 清單語法——但顯示層
過去直接把整段字串塞進 <p>，HTML 預設會把換行吃掉變成一整面文字牆。
正確做法（業界 LLM 對話介面的標準做法）是把這類文字當 markdown 渲染，
而不是純文字。這裡處理三件事：
1. 把「（1）...（2）...（3）...」這種夾在同一段落裡、markdown 不認得的
   全形括號編號，正規化成標準 `N. ` 有序清單語法
2. 有些論述完全不用括號數字，而是用「首先／其次／第三／第四...」這種中文
   序數詞當分點標記，整段話一個換行都沒有——這種也要在每個序數詞前面
   斷段，否則前面兩步都救不了這種寫法
3. 交給呼叫端（webapp）用既有的 markdown 渲染器轉成 HTML

純粹是顯示層的重排版，不改變論述本身的文字內容或引用的 evidence id。
"""

from __future__ import annotations

import re

_FULLWIDTH_NUM_RE = re.compile(r"[（(](\d+)[）)]")

# 只在「句號＋序數詞＋逗號」這個嚴格模式才斷段（例如「...嚴重。其次，量能..."），
# 避免誤判「第三方」「首先聲明」這類序數詞出現在句子中間、不是真的在起新論點。
_ORDINAL_TRANSITION_RE = re.compile(
    r"。(首先|其次|再次|再者|第三|第四|第五|第六|第七|第八|第九|第十|最後)，"
)


def _break_ordinal_transitions(text: str) -> str:
    """把「首先／其次／第三...」這種中文序數詞分點，轉成真正的段落分隔。"""
    return _ORDINAL_TRANSITION_RE.sub(lambda m: f"。\n\n{m.group(1)}，", text)


def normalize_embedded_lists(text: str) -> str:
    """把內嵌在段落裡的列點結構正規化成 markdown 認得的語法。

    處理兩種模式：
    1. 「（1）...（2）...（3）...」全形括號編號——一段文字裡可能出現好幾組
       獨立序列（各自從 1 開始），只有連續且從 1 開始的序列（至少 2 點）
       才視為列點結構，避免誤判文字裡剛好出現的其他括號數字
    2. 「首先／其次／第三...」中文序數詞分點——整段話可能完全沒有換行，
       在每個序數詞前面斷段
    找不到任何這種結構時原文不動。
    """
    text = _break_ordinal_transitions(text)
    matches = list(_FULLWIDTH_NUM_RE.finditer(text))
    if not matches:
        return text

    runs: list[list[re.Match]] = []
    current: list[re.Match] = []
    for m in matches:
        n = int(m.group(1))
        if current and n == int(current[-1].group(1)) + 1:
            current.append(m)
        elif n == 1:
            if len(current) >= 2:
                runs.append(current)
            current = [m]
        else:
            if len(current) >= 2:
                runs.append(current)
            current = []
    if len(current) >= 2:
        runs.append(current)

    replacements = [
        (m.start(), m.end(), f"\n\n{m.group(1)}. ") for run in runs for m in run
    ]
    if not replacements:
        return text
    replacements.sort(key=lambda r: r[0])

    pieces: list[str] = []
    cursor = 0
    for start, end, repl in replacements:
        pieces.append(text[cursor:start].rstrip("；;，, "))
        pieces.append(repl)
        # 括號後常緊接一個半形空格（如 "(1) 內容"），跳過它避免跟 repl
        # 自帶的空格疊成兩個空格
        cursor = end + 1 if text[end : end + 1] == " " else end
    pieces.append(text[cursor:])
    return "".join(pieces)

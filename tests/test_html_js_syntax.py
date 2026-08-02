"""HTML 內嵌 JavaScript 的語法檢查。

背景（2026-08-02 真實事故）：`14_流程圖視覺報告.html` 的 Execution Log 區塊曾被
推上 v3，其中一行是

    [executionLog.map(e => JSON.stringify(e)).join("
    ") + "
    "],

——字串字面量裡是真正的換行（產生 HTML 的腳本把 `\\n` 還原成換行字元了），JS
解析直接 `SyntaxError: Invalid or unexpected token`。因為整頁只有一個 `<script>`
區塊，**一個語法錯誤會讓整頁所有互動全死**：不只是 Execution Log，連 Stage 1 的
送出按鈕都不會有反應。

當時的驗證方式是 `curl` 拿到 HTTP 200 ＋ grep 到關鍵字就當作沒問題——但 200 只
代表檔案送得出去，跟 JS 跑不跑得動完全無關，所以整個壞掉的版本就這樣進了 repo。

這支測試把那個缺口補起來：抽出每個 HTML 的內嵌 `<script>`，丟給 `node --check`
做真正的語法解析。純語法檢查，不執行、不需要瀏覽器，毫秒級。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# 只檢查「自己手寫、且會被瀏覽器直接執行」的 HTML。
# `agent/report/html_export.py` 產生的交付檔不在此列——它是程式產生的，
# 內容由 Python 端的測試覆蓋。
HTML_FILES = [
    "14_流程圖視覺報告.html",
    "webapp/templates/result.html",
    "pipeline/02改_資料網格.html",
]

# 有 `src=` 的是外部檔案（本檔沒有內容可檢查）；`type="application/json"` 之類的
# 資料區塊也不是 JS。只挑真正內嵌的可執行腳本。
_SCRIPT_RE = re.compile(r"<script([^>]*)>(.*?)</script>", re.DOTALL | re.IGNORECASE)


def _inline_scripts(html: str) -> list[tuple[int, str]]:
    """回傳 [(在檔案中的起始行號, JS 內容)]，只含可執行的內嵌腳本。"""
    out: list[tuple[int, str]] = []
    for match in _SCRIPT_RE.finditer(html):
        attrs, body = match.group(1), match.group(2)
        if "src=" in attrs.lower():
            continue  # 外部檔案，這裡沒有內容可檢查
        type_match = re.search(r'type\s*=\s*["\']([^"\']+)', attrs, re.IGNORECASE)
        if type_match and type_match.group(1).lower() not in (
            "text/javascript",
            "application/javascript",
            "module",
        ):
            continue  # application/json 這類資料區塊不是 JS
        if not body.strip():
            continue
        start_line = html[: match.start(2)].count("\n") + 1
        out.append((start_line, body))
    return out


def _node_check(js: str) -> tuple[bool, str]:
    """用 `node --check` 做語法解析。回傳 (是否通過, 錯誤訊息)。"""
    with tempfile.TemporaryDirectory() as tmp:
        js_path = Path(tmp) / "snippet.js"
        js_path.write_text(js, encoding="utf-8")
        proc = subprocess.run(
            ["node", "--check", str(js_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    return proc.returncode == 0, (proc.stderr or proc.stdout or "").strip()


pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    # 沒有 node 就跳過而不是失敗：這支測試是額外的防護網，不該讓沒裝 node 的
    # 環境（例如精簡的部署容器）整套測試掛掉。但開發機與 CI 應該要有 node，
    # 否則這道防護等於沒開。
    reason="找不到 node，跳過內嵌 JS 語法檢查（開發機請安裝 node 以啟用這道防護）",
)


@pytest.mark.parametrize("rel_path", HTML_FILES)
def test_inline_javascript_parses(rel_path: str):
    """每個內嵌 <script> 都要能通過 JS 解析。

    失敗訊息會指出是哪個檔案的第幾個 script、在檔案中的起始行號，以及 node
    回報的原始錯誤——踩到時可以直接跳到出事的那一行。
    """
    path = REPO_ROOT / rel_path
    if not path.exists():
        pytest.skip(f"{rel_path} 不在這個 checkout 裡")

    html = path.read_text(encoding="utf-8")
    scripts = _inline_scripts(html)
    assert scripts, f"{rel_path} 找不到任何內嵌 <script>——是不是檔案結構改了？"

    for index, (start_line, js) in enumerate(scripts):
        # Jinja 樣板語法不是合法 JS，node 一定會噴錯。目前三個檔案的 script 區塊
        # 都沒有 Jinja（已確認），但之後若有人加了，這裡誠實跳過而不是假性失敗。
        if "{%" in js or "{{" in js:
            continue
        ok, err = _node_check(js)
        assert ok, (
            f"{rel_path} 的第 {index + 1} 個 <script>（檔案第 {start_line} 行起）"
            f"語法錯誤，整頁 JS 會失效：\n{err}"
        )


def test_the_2026_08_02_regression_would_be_caught():
    """把當時真的推上去的那個壞法重現一次，確認這道防護抓得到。

    沒有這條，上面那支測試「永遠綠燈」也可能只是因為 `_node_check` 根本沒在跑。
    """
    # 重現當時的壞法：`join("\n")` 的 `\n` 被還原成真正的換行，
    # 於是字串字面量在第一行就沒閉合。
    broken = 'const blob = new Blob([xs.join("\n") + "\n"]);'
    ok, err = _node_check(broken)
    assert not ok, "未閉合的字串字面量竟然通過了語法檢查，這道防護是壞的"
    assert "SyntaxError" in err or "Invalid" in err

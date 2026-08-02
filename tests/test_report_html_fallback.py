"""Stage 1-5 demo 首頁的報告 HTML 要在「只 clone 這個 repo」的環境也找得到。

`14_流程圖視覺報告.html` 的正本在 vault（`2026-07-雲湧智生黑客松/`），不在這個 repo 裡。
隊友 clone HOYAbit_ai_agent、或部署到 demo 機器時，那個路徑根本不存在，首頁會 404
（API 全部正常，只有頁面拿不到——這種壞法很容易被誤判成「服務掛了」）。所以 repo 內
放一份副本，並且解析順序是「先 vault 正本、後 repo 副本」：開發機上要送正在編輯的
那份，不然改了畫面不會變。
"""

from pathlib import Path

from webapp import stage1_demo_api as api


def test_prefers_vault_original_when_both_exist(tmp_path, monkeypatch):
    vault = tmp_path / "vault.html"
    repo = tmp_path / "repo.html"
    vault.write_text("正本", encoding="utf-8")
    repo.write_text("副本", encoding="utf-8")
    monkeypatch.setattr(api, "REPORT_HTML_VAULT", vault)
    monkeypatch.setattr(api, "REPORT_HTML_REPO", repo)

    assert api._resolve_report_html() == vault


def test_falls_back_to_repo_copy_when_vault_missing(tmp_path, monkeypatch):
    """clone / 部署環境：vault 那份不存在，要退到 repo 副本，不是直接 404。"""
    repo = tmp_path / "repo.html"
    repo.write_text("副本", encoding="utf-8")
    monkeypatch.setattr(api, "REPORT_HTML_VAULT", tmp_path / "不存在.html")
    monkeypatch.setattr(api, "REPORT_HTML_REPO", repo)

    assert api._resolve_report_html() == repo


def test_returns_none_when_neither_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "REPORT_HTML_VAULT", tmp_path / "a.html")
    monkeypatch.setattr(api, "REPORT_HTML_REPO", tmp_path / "b.html")

    assert api._resolve_report_html() is None


def test_repo_copy_is_actually_committed():
    """副本真的要在 repo 裡——這條測試就是防「有 fallback 邏輯但沒有那個檔案」。"""
    assert api.REPORT_HTML_REPO.exists(), (
        f"repo 內缺少 {api.REPORT_HTML_NAME}；只 clone 這個 repo 的人首頁會 404。"
        f"從 vault 複製一份過來：cp '{api.REPORT_HTML_VAULT}' '{api.REPORT_HTML_REPO}'"
    )
    assert api.REPORT_HTML_REPO.parent == Path(api.__file__).resolve().parent.parent

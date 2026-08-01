"""公開部署的濫用防護（2026-08-01）。

服務架在**主辦方的 AWS 帳號**上、無認證對外開放，每次真實執行約 7 萬 tokens、
4-6 分鐘。沒有防護等於讓任何人持續燒主辦方的錢，或用並發把 t3.small 打垮。

守門只擋真實執行；dry-run 完全不受影響（0.7 秒、不呼叫 Bedrock、零成本），
評審要試玩隨時可以——防護不能把正當使用者一起擋掉。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import webapp.app as webapp_module
from webapp.app import MAX_QUESTION_CHARS, app


@pytest.fixture
def client():
    webapp_module._last_real_run_by_ip.clear()
    return TestClient(app, raise_server_exceptions=False)


def _post(client, **overrides):
    data = {
        "coin": "BTC",
        "question": "分析 BTC 最近兩週的整體市場狀態",
        "dry_run": "true",
    }
    data.update(overrides)
    return client.post("/analyze", data=data)


class TestInputGuards:
    def test_rejects_coin_outside_competition_pool(self, client):
        assert "僅支援命題指定" in _post(client, coin="DOGE").text

    def test_rejects_coin2_outside_pool(self, client):
        assert "比較對象幣種僅支援" in _post(client, coin2="DOGE").text

    def test_rejects_overlong_question(self, client):
        r = _post(client, question="x" * (MAX_QUESTION_CHARS + 1))
        assert "字以內" in r.text

    def test_rejects_blank_question(self, client):
        assert "請輸入題目" in _post(client, question="   ").text

    def test_accepts_lowercase_and_whitespace_coin(self, client):
        """守門不能把正當輸入一起擋掉——小寫與前後空白要正常處理。"""
        r = _post(client, coin="  btc  ")
        assert r.status_code == 200
        assert "僅支援命題指定" not in r.text

    def test_dry_run_is_never_rate_limited(self, client):
        """dry-run 零成本，連跑幾次都不該被擋。"""
        for _ in range(3):
            r = _post(client)
            assert r.status_code == 200
            assert "限一次" not in r.text


class TestRealRunCooldown:
    def setup_method(self):
        webapp_module._last_real_run_by_ip.clear()

    def test_first_real_run_allowed(self):
        assert webapp_module._check_real_run_allowed("1.2.3.4") is None

    def test_second_run_from_same_ip_blocked(self):
        webapp_module._check_real_run_allowed("1.2.3.4")
        msg = webapp_module._check_real_run_allowed("1.2.3.4")
        assert msg is not None
        # 擋下時要告訴使用者還有 dry-run 這條路，不能只說「不行」
        assert "快速模式" in msg

    def test_different_ips_are_independent(self):
        webapp_module._check_real_run_allowed("1.2.3.4")
        assert webapp_module._check_real_run_allowed("5.6.7.8") is None

    def test_clearing_cooldown_restores_quota(self):
        """真實執行沒能真的開始時（例如並發滿了），不該白白扣掉配額。"""
        webapp_module._check_real_run_allowed("1.2.3.4")
        webapp_module._clear_cooldown("1.2.3.4")
        assert webapp_module._check_real_run_allowed("1.2.3.4") is None


class TestConcurrencyLimit:
    def setup_method(self):
        webapp_module._release_run_slot()

    def teardown_method(self):
        webapp_module._release_run_slot()

    def test_only_one_real_run_at_a_time(self):
        assert webapp_module._acquire_run_slot() is True
        assert webapp_module._acquire_run_slot() is False, "同時間不該允許兩個真實執行"

    def test_slot_is_released_after_use(self):
        webapp_module._acquire_run_slot()
        webapp_module._release_run_slot()
        assert webapp_module._acquire_run_slot() is True

    def test_leaked_slot_self_heals_after_max_run_seconds(self, monkeypatch):
        """**這是 2026-08-01 線上實際踩到的 bug 的回歸測試。**

        客戶端在執行途中斷線（會場網路很常見）曾讓名額洩漏，之後所有人都拿到
        「已有分析在執行」而實際上沒有，只能重啟服務。評審時發生等於 demo 直接死。
        現在超過 MAX_RUN_SECONDS 就視為前一位已消失並自動接手。
        """
        base = 1000.0
        monkeypatch.setattr(webapp_module.time, "monotonic", lambda: base)
        assert webapp_module._acquire_run_slot() is True

        # 還在執行時間內：後來者仍該被擋
        monkeypatch.setattr(
            webapp_module.time, "monotonic", lambda: base + webapp_module.MAX_RUN_SECONDS - 1
        )
        assert webapp_module._acquire_run_slot() is False

        # 超過上限：視為洩漏，自動接手，不需人工重啟
        monkeypatch.setattr(
            webapp_module.time, "monotonic", lambda: base + webapp_module.MAX_RUN_SECONDS + 1
        )
        assert webapp_module._acquire_run_slot() is True

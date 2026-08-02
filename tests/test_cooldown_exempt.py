"""真實執行冷卻的豁免名單（現場／評審端 NAT IP）。

背景：cooldown 是「每個 IP 五分鐘一次」，用意是擋自動化連打。但評審多半共用
同一組會場出口 IP，於是防濫用機制會變成「所有評審加起來五分鐘只能跑一次」。
豁免名單把這個副作用拆掉，同時**刻意不豁免全站單一併發鎖**——那道是真的資源
限制（一次真實執行 4-6 分鐘、7 次 Bedrock 呼叫），豁免它會讓現場更容易出事。
"""

from __future__ import annotations

import importlib

import pytest

import webapp.app as webapp_app


@pytest.fixture(autouse=True)
def _clean_cooldown_state():
    """每個測試前後都清掉 cooldown 紀錄，避免互相污染。"""
    webapp_app._last_real_run_by_ip.clear()
    yield
    webapp_app._last_real_run_by_ip.clear()


VENUE_IPS = [
    "60.250.15.18", "60.250.15.19",
    "60.250.15.34", "60.250.15.35", "60.250.15.36",
    "60.250.15.50", "60.250.15.51", "60.250.15.52",
]


@pytest.mark.parametrize("ip", VENUE_IPS)
def test_venue_ip_is_never_blocked_by_cooldown(ip: str):
    """會場 IP 連打都不該被冷卻擋下——這正是加白名單要解決的事。"""
    for attempt in range(5):
        assert webapp_app._check_real_run_allowed(ip) is None, (
            f"{ip} 第 {attempt + 1} 次就被冷卻擋下，白名單沒生效"
        )


def test_non_exempt_ip_still_rate_limited():
    """白名單不能把所有人的防濫用一起關掉。"""
    ip = "203.0.113.7"  # TEST-NET-3，不在名單內
    assert webapp_app._check_real_run_allowed(ip) is None, "第一次就被擋，不合理"
    blocked = webapp_app._check_real_run_allowed(ip)
    assert blocked is not None, "非白名單 IP 第二次仍未被冷卻擋下，防濫用失效"
    assert "分鐘限一次" in blocked


def test_exempt_ip_still_recorded():
    """豁免的是「被擋」，不是「不留紀錄」——現場實際打了幾次要查得到。"""
    ip = VENUE_IPS[0]
    webapp_app._check_real_run_allowed(ip)
    assert ip in webapp_app._last_real_run_by_ip


def test_all_eight_venue_ips_present_in_constant():
    """名單少一個就等於那台機器後面的人會被擋，逐一確認不要手滑漏打。"""
    for ip in VENUE_IPS:
        assert ip in webapp_app.COOLDOWN_EXEMPT_IPS, f"{ip} 不在豁免名單裡"


def test_env_var_can_add_more_ips(monkeypatch):
    """現場臨時多一組出口 IP 時，設環境變數就好，不用改程式碼重新部署。"""
    monkeypatch.setenv("REAL_RUN_COOLDOWN_EXEMPT_IPS", "198.51.100.5, 198.51.100.6")
    reloaded = importlib.reload(webapp_app)
    try:
        assert "198.51.100.5" in reloaded.COOLDOWN_EXEMPT_IPS
        assert "198.51.100.6" in reloaded.COOLDOWN_EXEMPT_IPS
        # 預設那八個不能因為設了環境變數就消失
        assert "60.250.15.18" in reloaded.COOLDOWN_EXEMPT_IPS
    finally:
        # 還原模組狀態，避免影響後續測試
        monkeypatch.delenv("REAL_RUN_COOLDOWN_EXEMPT_IPS", raising=False)
        importlib.reload(webapp_app)


def test_concurrency_slot_is_not_exempted():
    """全站單一併發鎖對白名單 IP 一樣有效——那是資源限制，不是防濫用。"""
    assert webapp_app._acquire_run_slot() is True
    try:
        assert webapp_app._acquire_run_slot() is False, (
            "第二個併發請求竟然拿到名額，單一併發保護失效"
        )
    finally:
        webapp_app._release_run_slot()

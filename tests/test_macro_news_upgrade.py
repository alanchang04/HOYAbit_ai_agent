"""測試 R2-2（macro F&G limit=30 百分位）。

R2-3（news 命中則數量化證據）已隨 news.py 改版移除——news collector 2026-07-20
起改為每幣官方發布源，不再有 CoinDesk/Cointelegraph 通用 feed 可量化命中則數，
原本這裡的對應測試已刪除。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.collectors.macro import MacroCollector
from agent.logging_utils import ExecutionLogger


# --- R2-2: macro F&G limit=30 百分位 ---


@pytest.fixture
def mock_logger(tmp_path):
    return ExecutionLogger(tmp_path / "test.jsonl")


def _make_fng_response_data(values: list[int]) -> dict:
    """建構 Fear & Greed API 假回應，values[0] 為最新。"""
    return {
        "data": [{"value": str(v), "value_classification": "Fear" if v < 50 else "Greed"} for v in values]
    }


@pytest.mark.asyncio
async def test_macro_fng_limit_30_and_percentile(mock_logger):
    """macro collector 應以 limit=30 呼叫 API，content_reference 含 30日百分位。"""
    # 30 個值：當前值 60，其餘 29 個從 30 到 58（步進 1）
    values = [60] + list(range(30, 59))  # 30 個值
    fng_json = _make_fng_response_data(values)

    mock_resp_fng = MagicMock()
    mock_resp_fng.raise_for_status = MagicMock()
    mock_resp_fng.json.return_value = fng_json

    # Frankfurter 回應
    mock_resp_fx = MagicMock()
    mock_resp_fx.raise_for_status = MagicMock()
    mock_resp_fx.json.return_value = {"date": "2025-07-01", "rates": {"EUR": 0.92, "JPY": 150.0, "GBP": 0.79}}

    async def mock_get(url, **kwargs):
        if "fng" in url:
            # 驗證 limit=30 有被傳入
            params = kwargs.get("params", {})
            assert params.get("limit") == 30, f"Expected limit=30, got {params}"
            return mock_resp_fng
        return mock_resp_fx

    collector = MacroCollector(mock_logger)

    with patch("agent.collectors.macro.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        evidences = await collector.fetch("BTC")

    # 找到 F&G 證據
    fng_evidences = [e for e in evidences if "Fear & Greed" in e.source]
    assert len(fng_evidences) == 1

    content = fng_evidences[0].content_reference
    assert "近30天百分位" in content
    assert "近30天範圍" in content
    assert "value=60" in content

    # 驗算百分位：60 在 [60, 30, 31, ..., 58] 中 <= 60 的有 30 個（全部）
    # count_below = 30, percentile = 100 * 30 / 30 = 100.0
    assert "近30天百分位=100.0%" in content
    assert f"近30天範圍={min(values)}-{max(values)}" in content


@pytest.mark.asyncio
async def test_macro_fng_percentile_calculation(mock_logger):
    """驗算百分位公式正確：當前值 50，30 日 [50, 10, 20, ..., 80]。"""
    values = [50, 10, 20, 30, 40, 50, 60, 70, 80, 45, 55, 35, 65, 25, 75, 15, 85, 42, 58, 33, 67, 28, 72, 38, 62, 48, 52, 44, 56, 46]
    fng_json = _make_fng_response_data(values)

    mock_resp_fng = MagicMock()
    mock_resp_fng.raise_for_status = MagicMock()
    mock_resp_fng.json.return_value = fng_json

    mock_resp_fx = MagicMock()
    mock_resp_fx.raise_for_status = MagicMock()
    mock_resp_fx.json.return_value = {"date": "2025-07-01", "rates": {"EUR": 0.92, "JPY": 150.0, "GBP": 0.79}}

    async def mock_get(url, **kwargs):
        if "fng" in url:
            return mock_resp_fng
        return mock_resp_fx

    collector = MacroCollector(mock_logger)

    with patch("agent.collectors.macro.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        evidences = await collector.fetch("BTC")

    fng_evidences = [e for e in evidences if "Fear & Greed" in e.source]
    assert len(fng_evidences) == 1

    content = fng_evidences[0].content_reference
    # 當前值 50，values 中 <= 50 的個數
    count_below = sum(1 for v in values if v <= 50)
    expected_percentile = round(100 * count_below / len(values), 1)
    assert f"近30天百分位={expected_percentile}%" in content

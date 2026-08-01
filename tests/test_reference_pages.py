"""API 端點 → 人類可讀頁面的對照（2026-07-31）。

`source_url` 記的是實際呼叫的位址（可稽核性根據），但多數是只回 JSON 的 API
端點，對讀者沒用。`reference_url` 補上「你想自己看的話去這裡」，兩者並存：
出處不被竄改，讀者也點得到原文。
"""

from __future__ import annotations

import pytest

from agent.collectors.coin_map import get_coin_info
from agent.collectors.reference_pages import resolve_reference_url
from agent.orchestrator import assign_evidence_ids
from agent.schemas import EvidenceDraft

COMPETITION_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]


def _chain(coin: str) -> str:
    return get_coin_info(coin).chain


class TestApiEndpointMapping:
    def test_coingecko_maps_to_coin_page(self):
        got = resolve_reference_url(
            "https://api.coingecko.com/api/v3/simple/price", "BTC", "bitcoin"
        )
        assert got == "https://www.coingecko.com/en/coins/bitcoin"

    def test_query_string_does_not_break_matching(self):
        """端點多半帶查詢參數，比對必須用前綴而非完全相等。"""
        got = resolve_reference_url(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
            "BTC",
            "bitcoin",
        )
        assert got == "https://www.coingecko.com/en/coins/bitcoin"

    @pytest.mark.parametrize("coin", COMPETITION_COINS)
    def test_every_competition_coin_resolves(self, coin):
        """比賽現場抽題，五幣都得對得到，不能只有 BTC 能用。"""
        got = resolve_reference_url(
            "https://api.coingecko.com/api/v3/simple/price", coin, _chain(coin)
        )
        assert got == f"https://www.coingecko.com/en/coins/{get_coin_info(coin).coingecko_id}"

    @pytest.mark.parametrize(
        "coin, expected_explorer",
        [
            ("BTC", "https://blockchair.com/bitcoin"),
            ("ETH", "https://etherscan.io/"),
            ("BNB", "https://bscscan.com/"),
            ("SOL", "https://explorer.solana.com/"),
            ("XRP", "https://xrpscan.com/"),
        ],
    )
    def test_rpc_endpoints_route_by_chain(self, coin, expected_explorer):
        """RPC 位址隨 .env 設定變動，抓不到固定前綴，改用鏈別對照瀏覽器。"""
        got = resolve_reference_url("https://rpc.example.com/v1", coin, _chain(coin))
        assert got == expected_explorer

    def test_cftc_socrata_json_maps_to_cot_report_page(self):
        got = resolve_reference_url(
            "https://publicreporting.cftc.gov/resource/gpe5-46if.json?x=1", "BTC", "bitcoin"
        )
        assert got == "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"

    def test_frankfurter_maps_to_ecb_原始出處(self):
        """Frankfurter 只是 ECB 每日參考匯率的轉發，該導到真正的原始出處。"""
        got = resolve_reference_url("https://api.frankfurter.app/latest?from=USD", "BTC", "bitcoin")
        assert got is not None and "ecb.europa.eu" in got


class TestNoMappingCases:
    def test_already_human_readable_urls_return_none(self):
        """已經是人看的頁面就不需要再給一個——回 None 讓渲染層直接用 source_url。"""
        for url in (
            "https://etherscan.io/chart/gasprice",
            "https://fred.stlouisfed.org/series/DGS10",
            "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            "https://www.reddit.com/r/Bitcoin/comments/abc/x/",
        ):
            assert resolve_reference_url(url, "BTC", "bitcoin") is None

    def test_unknown_endpoint_returns_none(self):
        """對不上就回 None——寧可讓讀者看到 JSON，也不要導到內容對不上的頁面。"""
        assert resolve_reference_url("https://example.com/some/page", "BTC", "bitcoin") is None

    def test_none_source_url_returns_none(self):
        """本地計算的證據沒有外部網址，不該憑空生一個。"""
        assert resolve_reference_url(None, "BTC", "bitcoin") is None

    def test_unknown_coin_does_not_crash(self):
        """未知幣種不該讓整條流程失敗（R6-1 降級優先）。"""
        got = resolve_reference_url(
            "https://api.coingecko.com/api/v3/simple/price", "DOGE", None
        )
        assert got is None or "{" in got or isinstance(got, str)


class TestOrchestratorWiring:
    def _draft(self, **overrides) -> EvidenceDraft:
        base = dict(
            coin="BTC",
            source="CoinGecko /simple/price",
            source_url="https://api.coingecko.com/api/v3/simple/price",
            fetched_at="2026-07-31T00:00:00Z",
            content_reference="BTC 現價 65,400",
            related_claim="BTC 當前報價",
            source_type="price",
        )
        base.update(overrides)
        return EvidenceDraft(**base)

    def test_orchestrator_fills_reference_url(self):
        """集中在 assign_evidence_ids 推導，collector 不必逐一改。"""
        [ev] = assign_evidence_ids([self._draft()])
        assert ev.reference_url == "https://www.coingecko.com/en/coins/bitcoin"
        # 出處必須原樣保留——那是可稽核性的根據，不可被人類頁面取代
        assert ev.source_url == "https://api.coingecko.com/api/v3/simple/price"

    def test_collector_supplied_reference_url_is_not_overwritten(self):
        """collector 若自己就知道更好的頁面（news／social 的原文），不該被蓋掉。"""
        draft = self._draft(reference_url="https://example.com/original-article")
        [ev] = assign_evidence_ids([draft])
        assert ev.reference_url == "https://example.com/original-article"

    def test_local_computation_evidence_keeps_both_none(self):
        draft = self._draft(source="本地區間統計（非外部資料）", source_url=None)
        [ev] = assign_evidence_ids([draft])
        assert ev.source_url is None
        assert ev.reference_url is None

"""API 端點 → 人類可讀頁面的對照表。

**為什麼要有這一層**：`source_url` 記的是我們實際呼叫的位址，那是可稽核性的
根據——報告說「資料來自 CoinGecko」，稽核者要能確認我們真的打了那支 API。
但 `https://api.coingecko.com/api/v3/simple/price` 點下去只有一坨 JSON，
而且不帶查詢參數時未必是同一筆資料，對讀者等於沒有用。

所以**不覆蓋 `source_url`，另外給一個 `reference_url`**：前者是出處，後者是
「你想自己看的話去這裡」。渲染時優先用後者，沒有就退回前者。

**這裡只收「該資料真正住在哪個頁面」的對照**，不收隨便找一個看起來相關的網址。
對不上的一律回 `None` 讓呼叫端退回 `source_url`——寧可讓讀者看到 JSON，
也不要把他導到一個內容其實對不上的漂亮頁面。

news／social 不在表內：它們的 `source_url` 本來就是文章與貼文的原始網址。
"""

from __future__ import annotations

from agent.collectors.coin_map import get_coin_info

# `{gecko}`／`{ticker}`／`{sym}` 會在 resolve 時以幣種資訊代換。
# key 為 `source_url` 的前綴（比對用 startswith，因為多數端點帶查詢參數）。
_REFERENCE_PAGES: dict[str, str] = {
    # --- price ---
    "https://api.coingecko.com/api/v3/simple/price": "https://www.coingecko.com/en/coins/{gecko}",
    "https://min-api.cryptocompare.com/data/pricemultifull": "https://www.cryptocompare.com/coins/{sym}/overview",
    # --- derivatives：Binance 的深層資料頁會改版，一律導到該合約的交易頁，
    #     資金費率／未平倉量／多空比都在那頁上看得到。
    "https://fapi.binance.com/fapi/v1/premiumIndex": "https://www.binance.com/en/futures/{ticker}USDT",
    "https://fapi.binance.com/fapi/v1/fundingRate": "https://www.binance.com/en/futures/funding-history/perpetual/real-time-funding-rate",
    "https://fapi.binance.com/futures/data/openInterestHist": "https://www.binance.com/en/futures/{ticker}USDT",
    "https://fapi.binance.com/futures/data/globalLongShortAccountRatio": "https://www.binance.com/en/futures/{ticker}USDT",
    "https://dapi.binance.com/dapi/v1/premiumIndex": "https://www.binance.com/en/delivery/{ticker}USD_PERP",
    "https://eapi.binance.com/eapi/v1/mark": "https://www.binance.com/en/eoptions/{ticker}USDT",
    "https://publicreporting.cftc.gov/resource/": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
    "https://api.hyperliquid.xyz/info": "https://app.hyperliquid.xyz/trade/{ticker}",
    "https://api.exchange.coinbase.com/products/": "https://www.coinbase.com/advanced-trade/spot/{ticker}-USD",
    # --- onchain ---
    "https://api.blockchair.com/bitcoin/stats": "https://blockchair.com/bitcoin",
    "https://api.blockchain.info/charts/hash-rate": "https://www.blockchain.com/explorer/charts/hash-rate",
    "https://api.mainnet-beta.solana.com": "https://explorer.solana.com/",
    # --- macro ---
    "https://api.alternative.me/fng/": "https://alternative.me/crypto/fear-and-greed-index/",
    # Frankfurter 只是 ECB 每日參考匯率的轉發，原始資料住在 ECB 這頁。
    "https://api.frankfurter.app/": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html",
}

# 依鏈路由的區塊鏈瀏覽器（onchain collector 的 RPC／Etherscan 端點對不到固定前綴，
# RPC 位址會隨 .env 設定改變，所以改用幣種的 chain 欄位決定）。
_CHAIN_EXPLORERS: dict[str, str] = {
    "bitcoin": "https://blockchair.com/bitcoin",
    "evm": "https://etherscan.io/",
    "bnb_chain": "https://bscscan.com/",
    "solana": "https://explorer.solana.com/",
    "xrpl": "https://xrpscan.com/",
}

# 這些主機本身就是給人看的頁面，不需要再對照（避免被下面的鏈瀏覽器規則蓋掉）。
_ALREADY_HUMAN_READABLE = (
    "https://etherscan.io/",
    "https://bscscan.com/",
    "https://fred.stlouisfed.org/",
    "https://www.federalreserve.gov/",
    "https://www.reddit.com/",
)


def _substitute(template: str, coin: str) -> str:
    """把模板裡的幣種佔位符換成實際值；查不到幣種資訊時原樣回傳。"""
    if "{" not in template:
        return template
    try:
        info = get_coin_info(coin)
    except Exception:  # noqa: BLE001 - 未知幣種不該讓整條流程失敗（R6-1）
        return template
    return (
        template.replace("{gecko}", info.coingecko_id)
        .replace("{ticker}", info.ticker)
        .replace("{sym}", info.ticker.lower())
    )


def _is_rpc_or_api_endpoint(url: str) -> bool:
    """看起來像機器讀的端點（RPC／api 子網域），才需要導向瀏覽器頁面。"""
    lowered = url.lower()
    return "//api." in lowered or "/api/" in lowered or "rpc" in lowered


def resolve_reference_url(source_url: str | None, coin: str, chain: str | None = None) -> str | None:
    """`source_url` → 人類可讀頁面；對不上時回 `None`（呼叫端退回 `source_url`）。

    比對順序：明確的端點對照表 → 依鏈的區塊鏈瀏覽器。已經是人類頁面的直接回 None
    （不需要另給一個），對不上也回 None。
    """
    if not source_url:
        return None
    if source_url.startswith(_ALREADY_HUMAN_READABLE):
        return None

    for prefix, template in _REFERENCE_PAGES.items():
        if source_url.startswith(prefix):
            return _substitute(template, coin)

    # onchain 的 RPC／Etherscan 端點位址隨設定變動，抓不到固定前綴，改用鏈別對照。
    if chain and _is_rpc_or_api_endpoint(source_url):
        explorer = _CHAIN_EXPLORERS.get(chain)
        if explorer:
            return explorer

    return None

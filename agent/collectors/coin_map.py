"""幣種代號與各資料來源慣用 id／別名的對照表。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoinInfo:
    ticker: str
    name: str
    coingecko_id: str
    cryptocompare_symbol: str
    aliases: tuple[str, ...]  # 供新聞/社群關鍵字比對用（小寫）
    chain: str  # "bitcoin" | "evm" | "solana" | "xrpl" | "bnb_chain"
    subreddits: tuple[str, ...]


COIN_INFO: dict[str, CoinInfo] = {
    "BTC": CoinInfo(
        ticker="BTC",
        name="Bitcoin",
        coingecko_id="bitcoin",
        cryptocompare_symbol="BTC",
        aliases=("bitcoin", "btc"),
        chain="bitcoin",
        subreddits=("Bitcoin", "CryptoCurrency"),
    ),
    "ETH": CoinInfo(
        ticker="ETH",
        name="Ethereum",
        coingecko_id="ethereum",
        cryptocompare_symbol="ETH",
        aliases=("ethereum", "eth", "ether"),
        chain="evm",
        subreddits=("ethereum", "CryptoCurrency"),
    ),
    "SOL": CoinInfo(
        ticker="SOL",
        name="Solana",
        coingecko_id="solana",
        cryptocompare_symbol="SOL",
        aliases=("solana", "sol"),
        chain="solana",
        subreddits=("solana", "CryptoCurrency"),
    ),
    "BNB": CoinInfo(
        ticker="BNB",
        name="BNB",
        coingecko_id="binancecoin",
        cryptocompare_symbol="BNB",
        aliases=("bnb", "binance coin", "binance smart chain", "bsc"),
        chain="bnb_chain",
        subreddits=("binance", "CryptoCurrency"),
    ),
    "XRP": CoinInfo(
        ticker="XRP",
        name="XRP",
        coingecko_id="ripple",
        cryptocompare_symbol="XRP",
        aliases=("xrp", "ripple"),
        chain="xrpl",
        subreddits=("Ripple", "CryptoCurrency"),
    ),
}


def get_coin_info(coin: str) -> CoinInfo:
    info = COIN_INFO.get(coin.upper())
    if info is None:
        raise KeyError(f"不支援的幣種: {coin}")
    return info

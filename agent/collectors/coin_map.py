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


SUPPORTED_COINS: tuple[str, ...] = tuple(COIN_INFO.keys())

# 只用「不易與一般文字/單字混淆」的全名別名做大小寫不敏感比對；
# ticker 本身用大小寫敏感比對（避免 "sol"、"eth" 等短別名誤判成一般英文單字的一部分）。
_FULL_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "BTC": ("bitcoin",),
    "ETH": ("ethereum",),
    "SOL": ("solana",),
    "BNB": ("binance coin", "binancecoin", "binance smart chain"),
    "XRP": ("ripple",),
}


def detect_coins_in_text(text: str) -> list[str]:
    """掃描文字中依序出現的幣種代號，回傳依出現順序去重後的 ticker 清單。

    用於「比較分析」題型：主辦方指定的幣種只有一個，但題目文字本身
    通常會直接寫出要比較的第二個幣種（如題目模板「比較【幣種A】與
    【幣種B】」），因此用簡單的字串比對從題目文字抓出所有被提及的
    幣種，而不強求完整 NLP 實體辨識——這與 classify_question_type()
    採用的關鍵字啟發式一致，優先求穩定可預期而非完美。
    """
    text_lower = text.lower()
    positions: list[tuple[int, str]] = []
    for ticker in COIN_INFO:
        idx = text.find(ticker)
        if idx != -1:
            positions.append((idx, ticker))
        for alias in _FULL_NAME_ALIASES.get(ticker, ()):
            idx2 = text_lower.find(alias)
            if idx2 != -1:
                positions.append((idx2, ticker))

    positions.sort(key=lambda x: x[0])
    seen: set[str] = set()
    ordered: list[str] = []
    for _, ticker in positions:
        if ticker not in seen:
            seen.add(ticker)
            ordered.append(ticker)
    return ordered

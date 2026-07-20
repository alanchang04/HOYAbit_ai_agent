"""回歸測試：news.py _matches_coin() 雙軌比對邏輯（R1-1, R1-2）。"""

from agent.collectors.news import _matches_coin


# --- False-positive 回歸：一般英文單字不得誤判為幣種 ---


def test_method_does_not_match_eth():
    """'method' 含 'eth' 子字串，不應命中 ETH。"""
    assert _matches_coin("We need a new method to solve this", "ETH") is False


def test_synthetic_does_not_match_eth():
    """'synthetic' 含 'eth' 子字串，不應命中 ETH。"""
    assert _matches_coin("synthetic data generation is trending", "ETH") is False


def test_solution_does_not_match_sol():
    """'solution' 含 'sol' 子字串，不應命中 SOL。"""
    assert _matches_coin("we need to find a solution quickly", "SOL") is False


def test_console_does_not_match_sol():
    """'console' 含 'sol' 子字串，不應命中 SOL。"""
    assert _matches_coin("check the console output for errors", "SOL") is False


# --- 正常命中：ticker 大小寫敏感 ---


def test_uppercase_sol_in_text_matches_sol():
    """大寫 'SOL' 在文本中，應命中 SOL。"""
    assert _matches_coin("SOL price surges 10% overnight", "SOL") is True


def test_uppercase_eth_in_text_matches_eth():
    """大寫 'ETH' 在文本中，應命中 ETH。"""
    assert _matches_coin("ETH breaks $4000 resistance", "ETH") is True


def test_uppercase_btc_in_text_matches_btc():
    """大寫 'BTC' 在文本中，應命中 BTC。"""
    assert _matches_coin("BTC hits new all-time high", "BTC") is True


# --- 正常命中：全名別名大小寫不敏感 ---


def test_ethereum_capitalized_matches_eth():
    """'Ethereum'（首字母大寫）應命中 ETH。"""
    assert _matches_coin("Ethereum network upgrade scheduled", "ETH") is True


def test_ethereum_lowercase_matches_eth():
    """'ethereum'（全小寫）應命中 ETH。"""
    assert _matches_coin("the ethereum blockchain is evolving", "ETH") is True


def test_bitcoin_matches_btc():
    """'Bitcoin' 應命中 BTC。"""
    assert _matches_coin("Bitcoin adoption grows in Asia", "BTC") is True


def test_solana_matches_sol():
    """'Solana' 應命中 SOL。"""
    assert _matches_coin("Solana DeFi TVL reaches new high", "SOL") is True


def test_ripple_matches_xrp():
    """'Ripple' 應命中 XRP。"""
    assert _matches_coin("Ripple wins SEC lawsuit", "XRP") is True


# --- 邊界情境 ---


def test_empty_text_matches_nothing():
    """空字串不應命中任何幣種。"""
    assert _matches_coin("", "BTC") is False


def test_mixed_case_ticker_does_not_match():
    """'Eth'（非全大寫）不應命中 ETH，因 ticker 比對為大小寫敏感。"""
    assert _matches_coin("Eth is mentioned here", "ETH") is False


def test_lowercase_ticker_in_text_does_not_match():
    """'btc'（全小寫）不應命中 BTC，因 ticker 比對為大小寫敏感。"""
    assert _matches_coin("some btc related text", "BTC") is False

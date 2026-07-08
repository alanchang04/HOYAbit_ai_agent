from agent.collectors.coin_map import detect_coins_in_text


def test_detect_coins_finds_two_tickers_in_order():
    text = "請比較 ETH 與 BTC 在當前市場的風險敞口"
    assert detect_coins_in_text(text) == ["ETH", "BTC"]


def test_detect_coins_deduplicates_repeated_mentions():
    text = "BTC 近期表現如何？BTC 的鏈上活躍度呢？"
    assert detect_coins_in_text(text) == ["BTC"]


def test_detect_coins_matches_full_english_name_case_insensitive():
    text = "比較 Bitcoin 與 Solana 的市場關注度"
    assert detect_coins_in_text(text) == ["BTC", "SOL"]


def test_detect_coins_ignores_lowercase_short_alias_false_positive():
    # "sol" 若用大小寫不敏感比對會誤判進 "solve"/"solution" 這類字；
    # ticker 比對改用大小寫敏感，這裡確保不會誤觸發。
    text = "we need to solve this issue and find a solution"
    assert detect_coins_in_text(text) == []


def test_detect_coins_returns_empty_when_no_coin_mentioned():
    assert detect_coins_in_text("分析市場的總體趨勢") == []

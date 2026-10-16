from app.llm.mock import PREFIX, mock_reply

CTX = {
    "cash_balance": 8000.0,
    "total_value": 10500.0,
    "positions": [{"ticker": "AAPL", "quantity": 5, "unrealized_pnl": 12.5}],
    "watchlist": [{"ticker": "AAPL", "price": 190.0}, {"ticker": "MSFT", "price": 400.0}],
}


def test_buy_and_sell_case_insensitive_multiple():
    o = mock_reply("BUY 5 aapl then Sell 2.5 tsla", CTX)
    assert [(t.side, t.quantity, t.ticker) for t in o.trades] == [("buy", 5.0, "AAPL"), ("sell", 2.5, "TSLA")]
    assert o.message.startswith(PREFIX)


def test_watchlist_changes():
    o = mock_reply("add pypl and remove MSFT", CTX)
    assert [(c.action, c.ticker) for c in o.watchlist_changes] == [("add", "PYPL"), ("remove", "MSFT")]
    assert o.trades == []


def test_mixed():
    o = mock_reply("buy 1 NVDA and add NVDA", CTX)
    assert len(o.trades) == 1 and len(o.watchlist_changes) == 1


def test_default_summary_uses_context():
    o = mock_reply("how am I doing?", CTX)
    assert o.message.startswith(PREFIX)
    assert "$10,500.00" in o.message and "AAPL" in o.message
    assert o.trades == [] and o.watchlist_changes == []


def test_summary_without_positions():
    o = mock_reply("hello", {"cash_balance": 10000.0, "total_value": 10000.0, "positions": [], "watchlist": []})
    assert "No open positions" in o.message


def test_long_words_not_matched():
    assert mock_reply("address everything", CTX).watchlist_changes == []


def test_zero_quantity_ignored():
    assert mock_reply("buy 0 AAPL", CTX).trades == []

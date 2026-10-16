from types import SimpleNamespace

from app.llm.executor import execute_actions
from app.llm.schemas import LLMOutput, LLMTrade, LLMWatchlistChange


class HTTPErr(Exception):
    def __init__(self, detail):
        self.detail = detail


class FakePortfolio:
    def __init__(self):
        self.log = []

    async def trade(self, ticker, side, quantity):
        self.log.append(("trade", ticker, side, quantity))
        if side == "sell":
            raise HTTPErr("Insufficient shares: have 5, selling 50")
        return SimpleNamespace(price=190.12), {"portfolio": 1}

    async def watchlist_add(self, ticker):
        if ticker == "BAD":
            raise HTTPErr("Invalid ticker")
        return True

    async def watchlist_remove(self, ticker):
        return False


async def test_records_success_and_failure_independently():
    out = LLMOutput(
        message="m",
        trades=[LLMTrade(ticker="AAPL", side="buy", quantity=10), LLMTrade(ticker="TSLA", side="sell", quantity=50)],
        watchlist_changes=[
            LLMWatchlistChange(ticker="PYPL", action="add"),
            LLMWatchlistChange(ticker="BAD", action="add"),
            LLMWatchlistChange(ticker="XYZ", action="remove"),
        ],
    )
    p = FakePortfolio()
    a = await execute_actions(out, p)
    t0, t1 = a.trades
    assert (t0.status, t0.price, t0.error) == ("executed", 190.12, None)
    assert (t1.status, t1.price, t1.error) == ("failed", None, "Insufficient shares: have 5, selling 50")
    assert [w.status for w in a.watchlist_changes] == ["executed", "failed", "failed"]
    assert a.watchlist_changes[1].error == "Invalid ticker"
    assert a.watchlist_changes[2].error == "Not in watchlist"
    assert len(p.log) == 2


async def test_empty_output():
    a = await execute_actions(LLMOutput(message="hi"), FakePortfolio())
    assert a.trades == [] and a.watchlist_changes == []

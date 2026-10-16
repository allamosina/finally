from types import SimpleNamespace

import pytest

from app.db.repo import InsufficientShares, TradeError
from app.llm import service
from app.llm.executor import execute_actions
from app.llm.schemas import LLMOutput, LLMTrade, LLMWatchlistChange
from app.services.validation import InvalidInput


class FakePortfolio:
    async def view(self):
        return {
            "cash_balance": 9000.0, "total_value": 10100.0, "unrealized_pnl": 100.0,
            "positions": [{"ticker": "AAPL", "quantity": 5, "avg_cost": 180.0, "current_price": 200.0,
                           "market_value": 1000.0, "unrealized_pnl": 100.0, "pnl_pct": 11.1}],
        }

    async def trade(self, ticker, side, quantity):
        if ticker == "ZZZ9":
            raise InvalidInput("Invalid ticker 'ZZZ9': must be 1-5 letters")
        if side == "sell" and quantity > 5:
            raise InsufficientShares(5, quantity)
        return SimpleNamespace(price=190.5), await self.view()

    async def watchlist_add(self, ticker):
        return True

    async def watchlist_remove(self, ticker):
        return True


@pytest.fixture
def env(monkeypatch):
    saved = []

    async def list_chat(limit=50):
        return []

    async def add_chat(role, content, actions=None):
        saved.append((role, content, actions))

    async def list_watchlist():
        return ["AAPL", "MSFT"]

    monkeypatch.setattr(service.repo, "list_chat", list_chat)
    monkeypatch.setattr(service.repo, "add_chat", add_chat)
    monkeypatch.setattr(service.repo, "list_watchlist", list_watchlist)
    monkeypatch.setattr(service, "_portfolio", lambda: FakePortfolio())
    quotes = {"AAPL": SimpleNamespace(price=200.0)}
    monkeypatch.setattr(service, "_prices", lambda: SimpleNamespace(get=quotes.get))
    return saved


async def test_executor_real_error_types():
    out = LLMOutput(
        message="m",
        trades=[LLMTrade(ticker="AAPL", side="sell", quantity=50), LLMTrade(ticker="ZZZ9", side="buy", quantity=1)],
    )
    a = await execute_actions(out, FakePortfolio())
    assert a.trades[0].error == "Insufficient shares: have 5, selling 50"
    assert a.trades[1].error.startswith("Invalid ticker")
    assert issubclass(InsufficientShares, TradeError)


async def test_chat_mock_end_to_end(env, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    r = await service.chat("buy 5 AAPL and sell 500 AAPL, add PYPL")
    assert r.message.startswith("[mock] ")
    assert [t.status for t in r.actions.trades] == ["executed", "failed"]
    assert r.actions.trades[0].price == 190.5
    assert r.actions.watchlist_changes[0].status == "executed"
    assert [s[0] for s in env] == ["user", "assistant"]
    assert env[1][2]["trades"][1]["status"] == "failed"
    assert env[0][2] is None


async def test_chat_mock_summary_no_actions(env, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    r = await service.chat("how am I doing")
    assert "$10,100.00" in r.message and r.actions.trades == []


async def test_chat_live_uses_model(env, monkeypatch):
    monkeypatch.delenv("LLM_MOCK", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    async def fake(messages):
        seen["messages"] = messages
        return '{"message":"placing an order","trades":[{"ticker":"aapl","side":"buy","quantity":1}]}'

    monkeypatch.setattr("app.llm.client.call_model", fake)
    # get_structured_reply binds call_model at call time via default arg lookup
    r = await service.chat("buy one")
    assert r.actions.trades[0].status == "executed"
    assert seen["messages"][-1] == {"role": "user", "content": "buy one"}
    assert "AAPL" in seen["messages"][0]["content"]


async def test_unconfigured_raises(monkeypatch):
    monkeypatch.delenv("LLM_MOCK", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(service.LLMNotConfigured):
        await service.chat("hi")

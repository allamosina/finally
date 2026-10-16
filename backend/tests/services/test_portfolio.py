"""The portfolio service directly, with a real db file and a bare cache + simulator."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from app import db
from app.db import repo
from app.market import MarketConfig, PriceCache, SimulatorSource
from app.services import market, portfolio
from app.services.validation import InvalidInput


@pytest_asyncio.fixture
async def svc(tmp_path):
    await db.init_db(str(tmp_path / "finally.db"))
    cache = PriceCache()
    source = SimulatorSource(cache, MarketConfig(sim_seed=3))  # not started: prices only move when we say
    market.install(cache, source)
    await portfolio.sync_priced_set()
    yield cache
    market.clear()


async def _set_price(cache: PriceCache, ticker: str, price: float):
    await cache.apply({ticker: (price, 1, "test")})


async def test_view_pnl_math(svc):
    await _set_price(svc, "AAPL", 100.0)
    await portfolio.trade("AAPL", "buy", 10)
    await _set_price(svc, "AAPL", 110.0)
    v = await portfolio.view()
    [p] = v.positions
    assert (p.avg_cost, p.current_price, p.market_value, p.unrealized_pnl, p.pnl_pct) == (100.0, 110.0, 1100.0, 100.0, 10.0)
    assert v.cash_balance == 9000.0 and v.total_value == 10100.0 and v.unrealized_pnl == 100.0


async def test_weighted_avg_cost_and_sell_below_cost(svc):
    await _set_price(svc, "AAPL", 100.0)
    await portfolio.trade("AAPL", "buy", 10)
    await _set_price(svc, "AAPL", 200.0)
    await portfolio.trade("AAPL", "buy", 10)
    assert (await portfolio.view()).positions[0].avg_cost == 150.0
    await _set_price(svc, "AAPL", 50.0)
    _, v = await portfolio.trade("AAPL", "sell", 5)
    assert v.positions[0].avg_cost == 150.0 and v.positions[0].quantity == 15
    assert v.cash_balance == pytest.approx(10000 - 1000 - 2000 + 250)


async def test_trade_uses_cache_price(svc):
    await _set_price(svc, "MSFT", 321.5)
    t, _ = await portfolio.trade("msft", "BUY", 2)
    assert (t.ticker, t.side, t.price) == ("MSFT", "buy", 321.5)


async def test_validation_before_any_side_effect(svc):
    for args in (("AAPL1", "buy", 1), ("AAPL", "short", 1), ("AAPL", "buy", 0), ("AAPL", "buy", float("nan"))):
        with pytest.raises(InvalidInput):
            await portfolio.trade(*args)
    assert await repo.list_trades() == []


async def test_concurrent_buys_cannot_overspend(svc):
    await _set_price(svc, "AAPL", 1000.0)
    results = await asyncio.gather(*(portfolio.trade("AAPL", "buy", 6) for _ in range(2)), return_exceptions=True)
    assert sum(isinstance(r, repo.InsufficientCash) for r in results) == 1
    assert (await portfolio.view()).cash_balance == 4000.0


async def test_watchlist_add_remove_sync_priced_set(svc):
    assert await portfolio.watchlist_add("pypl") is True
    assert await portfolio.watchlist_add("PYPL") is False
    assert "PYPL" in svc.tickers()
    assert await portfolio.watchlist_remove("PYPL") is True
    assert await portfolio.watchlist_remove("PYPL") is False
    assert "PYPL" not in svc.tickers()


async def test_view_falls_back_to_avg_cost_without_quote(svc):
    await _set_price(svc, "AAPL", 100.0)
    await portfolio.trade("AAPL", "buy", 1)
    await svc.drop("AAPL")
    [p] = (await portfolio.view()).positions
    assert p.current_price == 100.0 and p.unrealized_pnl == 0.0


async def test_reset_resyncs_and_snapshots(svc):
    await portfolio.trade("PYPL", "buy", 1)
    v = await portfolio.reset()
    assert v.positions == [] and v.cash_balance == 10000.0
    assert "PYPL" not in svc.tickers()
    assert [s.total_value for s in await repo.list_snapshots()] == [10000.0]

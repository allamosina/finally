"""Regression tests for the two REVIEW.md simulator findings fixed in wave 1."""

from __future__ import annotations

import asyncio

from app.market import MarketConfig, PriceCache, SimulatorSource


async def test_drop_bumps_version_and_wakes_waiters():
    cache = PriceCache()
    await cache.apply({"AAPL": (190.0, 1, "simulator")})
    v = cache.version
    waiter = asyncio.create_task(cache.wait_for_change(v))
    await asyncio.sleep(0)
    await cache.drop("AAPL")
    assert await asyncio.wait_for(waiter, 1) == v + 1
    assert cache.get("AAPL") is None


async def test_drop_of_absent_ticker_does_not_bump_version():
    cache = PriceCache()
    v = cache.version
    await cache.drop("NOPE")
    assert cache.version == v


async def test_set_tickers_drops_primed_only_ticker():
    cache = PriceCache()
    src = SimulatorSource(cache, MarketConfig(sim_seed=1))
    await src.set_tickers({"AAPL"})
    await src.prime({"ZZZZ"})  # e.g. a buy that then failed
    assert "ZZZZ" in cache.tickers()
    await src.set_tickers({"AAPL"})  # unchanged set
    assert cache.tickers() == {"AAPL"}


async def test_set_tickers_keeps_primed_ticker_that_joins_the_set():
    cache = PriceCache()
    src = SimulatorSource(cache, MarketConfig(sim_seed=1))
    await src.set_tickers({"AAPL"})
    quote = (await src.prime({"ZZZZ"}))["ZZZZ"]
    await src.set_tickers({"AAPL", "ZZZZ"})  # e.g. the buy succeeded
    assert cache.get("ZZZZ") is quote  # not re-primed, history preserved

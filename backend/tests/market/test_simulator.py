import asyncio
import math
import random

import pytest

from app.market import MarketDataSource, MarketSimulator, PriceCache
from app.market.simulator import DEFAULT_PROFILES, TickerProfile


def make(seed=1, **kw):
    cache = PriceCache()
    return cache, MarketSimulator(cache, rng=random.Random(seed), **kw)


def test_implements_interface():
    assert issubclass(MarketSimulator, MarketDataSource)


async def test_start_seeds_cache_with_realistic_prices():
    cache, sim = make()
    await sim.start(DEFAULT_PROFILES)
    try:
        assert cache.get_price("AAPL") == 190.0
        assert len(cache) == 10
    finally:
        await sim.stop()


async def test_background_task_updates_prices_and_stop_is_idempotent():
    cache, sim = make(interval=0.01)
    await sim.start(["AAPL"])
    v = cache.version
    await asyncio.sleep(0.1)
    assert cache.version > v
    await sim.stop()
    await sim.stop()
    v = cache.version
    await asyncio.sleep(0.05)
    assert cache.version == v


def test_prices_stay_positive_and_valid():
    cache, sim = make(event_probability=0.05)
    sim._register("AAPL")
    sim._register("ZZZZ")
    for _ in range(2000):
        sim.step()
    for u in cache.get_all().values():
        assert u.price > 0 and math.isfinite(u.price)


def test_gbm_math_zero_shock_is_deterministic_drift():
    _, sim = make()
    p = TickerProfile(100.0, 0.10, 0.20, "tech")
    expected = 100 * math.exp((0.10 - 0.5 * 0.20**2) * sim._dt)
    assert sim._gbm(100.0, p, 0.0) == pytest.approx(expected)
    # positive shock raises, negative lowers
    assert sim._gbm(100.0, p, 1.0) > sim._gbm(100.0, p, 0.0) > sim._gbm(100.0, p, -1.0)


def test_log_return_volatility_matches_profile():
    _, sim = make(seed=7)
    p = TickerProfile(100.0, 0.0, 0.30, "tech")
    rng = random.Random(3)
    rets = [math.log(sim._gbm(100.0, p, rng.gauss(0, 1)) / 100.0) for _ in range(20000)]
    mean = sum(rets) / len(rets)
    std = math.sqrt(sum((r - mean) ** 2 for r in rets) / len(rets))
    assert std == pytest.approx(0.30 * math.sqrt(sim._dt), rel=0.05)


def test_events_cause_large_moves():
    cache, sim = make(event_probability=1.0)
    sim._register("AAPL")
    before = cache.get_price("AAPL")
    sim.step()
    move = abs(cache.get_price("AAPL") / before - 1)
    assert 0.019 <= move <= 0.051


def test_tech_stocks_more_correlated_than_cross_sector():
    cache, sim = make(seed=11)
    for t in ("AAPL", "MSFT", "JPM"):
        sim._register(t)
    series = {t: [] for t in ("AAPL", "MSFT", "JPM")}
    last = {t: cache.get_price(t) for t in series}
    sim._prices = {t: float(p) for t, p in last.items()}
    for _ in range(3000):
        sim.step()
        for t in series:
            p = sim._prices[t]
            series[t].append(math.log(p / last[t]))
            last[t] = p

    def corr(a, b):
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        return cov / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))

    assert corr(series["AAPL"], series["MSFT"]) > corr(series["AAPL"], series["JPM"])
    assert corr(series["AAPL"], series["MSFT"]) > 0.2


async def test_add_remove_ticker_and_unknown_ticker():
    cache, sim = make()
    await sim.start(["AAPL"])
    await sim.add_ticker("pypl")
    assert sorted(sim.get_tickers()) == ["AAPL", "PYPL"]
    assert cache.get_price("PYPL") is not None
    await sim.add_ticker("PYPL")  # duplicate ignored
    assert len(sim.get_tickers()) == 2
    await sim.remove_ticker("PYPL")
    assert "PYPL" not in sim.get_tickers() and "PYPL" not in cache
    await sim.stop()

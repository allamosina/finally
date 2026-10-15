"""Market simulator: correlated geometric Brownian motion with random events."""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Iterable
from dataclasses import dataclass

from .cache import PriceCache
from .interface import MarketDataSource

TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600


@dataclass(frozen=True)
class TickerProfile:
    seed_price: float
    drift: float  # annualized
    volatility: float  # annualized
    sector: str


# Weight of the shared market factor and of the sector factor in each ticker's shock.
MARKET_WEIGHT = 0.3
SECTOR_WEIGHTS = {"tech": 0.6, "finance": 0.5, "default": 0.3}

DEFAULT_PROFILES: dict[str, TickerProfile] = {
    "AAPL": TickerProfile(190.0, 0.08, 0.25, "tech"),
    "GOOGL": TickerProfile(175.0, 0.08, 0.28, "tech"),
    "MSFT": TickerProfile(420.0, 0.09, 0.24, "tech"),
    "AMZN": TickerProfile(185.0, 0.09, 0.30, "tech"),
    "TSLA": TickerProfile(250.0, 0.10, 0.55, "tech"),
    "NVDA": TickerProfile(900.0, 0.15, 0.50, "tech"),
    "META": TickerProfile(500.0, 0.10, 0.35, "tech"),
    "JPM": TickerProfile(200.0, 0.06, 0.20, "finance"),
    "V": TickerProfile(280.0, 0.07, 0.18, "finance"),
    "NFLX": TickerProfile(620.0, 0.10, 0.38, "tech"),
}


def profile_for(ticker: str, rng: random.Random) -> TickerProfile:
    """Known profile, or a random plausible one for unknown tickers."""
    known = DEFAULT_PROFILES.get(ticker.upper())
    if known:
        return known
    return TickerProfile(
        seed_price=round(rng.uniform(20, 400), 2),
        drift=0.07,
        volatility=round(rng.uniform(0.2, 0.45), 3),
        sector="default",
    )


class MarketSimulator(MarketDataSource):
    def __init__(
        self,
        cache: PriceCache,
        interval: float = 0.5,
        event_probability: float = 0.002,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(cache)
        self.interval = interval
        self.event_probability = event_probability  # per ticker per step
        self.rng = rng or random.Random()
        self._profiles: dict[str, TickerProfile] = {}
        self._prices: dict[str, float] = {}
        self._task: asyncio.Task | None = None
        self._dt = interval / TRADING_SECONDS_PER_YEAR

    # --- lifecycle ---
    async def start(self, tickers: Iterable[str]) -> None:
        for t in tickers:
            self._register(t)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def add_ticker(self, ticker: str) -> None:
        self._register(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        t = ticker.upper()
        self._profiles.pop(t, None)
        self._prices.pop(t, None)
        self.cache.remove(t)

    def get_tickers(self) -> list[str]:
        return list(self._profiles)

    # --- internals ---
    def _register(self, ticker: str) -> None:
        t = ticker.upper()
        if t in self._profiles:
            return
        profile = profile_for(t, self.rng)
        self._profiles[t] = profile
        self._prices[t] = profile.seed_price
        self.cache.update(t, profile.seed_price)

    async def _run(self) -> None:
        while True:
            self.step()
            await asyncio.sleep(self.interval)

    def step(self) -> None:
        """Advance every ticker one time step and write to the cache."""
        market = self.rng.gauss(0, 1)
        sectors = {s: self.rng.gauss(0, 1) for s in {p.sector for p in self._profiles.values()}}
        for ticker, profile in self._profiles.items():
            w_s = SECTOR_WEIGHTS.get(profile.sector, SECTOR_WEIGHTS["default"])
            idio = math.sqrt(max(0.0, 1 - MARKET_WEIGHT**2 - w_s**2))
            z = MARKET_WEIGHT * market + w_s * sectors[profile.sector] + idio * self.rng.gauss(0, 1)
            new_price = self._gbm(self._prices[ticker], profile, z)
            if self.rng.random() < self.event_probability:
                new_price *= 1 + self.rng.uniform(0.02, 0.05) * self.rng.choice((-1, 1))
            new_price = max(new_price, 0.01)
            self._prices[ticker] = new_price
            self.cache.update(ticker, new_price)

    def _gbm(self, price: float, p: TickerProfile, z: float) -> float:
        """One GBM step: S * exp((mu - sigma^2/2) dt + sigma sqrt(dt) z)."""
        drift = (p.drift - 0.5 * p.volatility**2) * self._dt
        shock = p.volatility * math.sqrt(self._dt) * z
        return price * math.exp(drift + shock)

"""The built-in GBM price simulator: the default MarketDataSource.

See planning/MARKET_SIMULATOR.md §6.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from dataclasses import dataclass

from .base import MarketDataSource
from .cache import PriceCache
from .config import MarketConfig
from .gbm import gbm_step, rng_for
from .seeds import spec_for

log = logging.getLogger(__name__)
PRICE_FLOOR = 0.01


@dataclass
class _SimState:
    price: float
    seed_price: float
    mu: float
    sigma: float
    rng: random.Random


class SimulatorSource(MarketDataSource):
    name = "simulator"

    def __init__(self, cache: PriceCache, cfg: MarketConfig, kappa: float = 1e-4):
        super().__init__(cache)
        self._cfg = cfg
        self._kappa = kappa  # mean reversion toward the seed price; 0 disables
        self._state: dict[str, _SimState] = {}
        self._tick_count = 0
        self._last_tick_ms = 0

    # ---- MarketDataSource hooks ------------------------------------------
    async def _fetch_now(self, tickers: set[str]) -> None:
        """Seed any unseen tickers and write their current price immediately."""
        now_ms = int(time.time() * 1000)
        ticks: dict[str, tuple[float, int, str]] = {}
        opens: dict[str, float] = {}
        for t in tickers:
            st = self._state.get(t) or self._seed(t)
            ticks[t] = (round(st.price, 4), now_ms, "simulator")
            opens[t] = st.seed_price
        await self.cache.apply(ticks, session_open=opens)

    async def _run(self) -> None:
        interval = self._cfg.sim_tick_ms / 1000.0
        next_at = time.monotonic()
        while True:
            next_at += interval
            try:
                await self._tick()
            except Exception:  # never let the loop die
                log.exception("simulator tick failed")
            await asyncio.sleep(max(0.0, next_at - time.monotonic()))  # drift-free cadence

    # ---- internals --------------------------------------------------------
    def _seed(self, ticker: str) -> _SimState:
        spec = spec_for(ticker)
        st = _SimState(
            spec.price, spec.price, spec.mu_tick, spec.sigma_tick, rng_for(ticker, self._cfg.sim_seed)
        )
        self._state[ticker] = st
        return st

    async def _tick(self) -> None:
        if not self._tickers:
            return
        now_ms = int(time.time() * 1000)
        ticks: dict[str, tuple[float, int, str]] = {}
        for t in sorted(self._tickers):  # sorted: deterministic order for tests
            st = self._state.get(t) or self._seed(t)
            mu_eff = st.mu - self._kappa * math.log(st.price / st.seed_price)
            st.price = max(PRICE_FLOOR, gbm_step(st.price, mu_eff, st.sigma, st.rng.gauss(0.0, 1.0)))
            ticks[t] = (round(st.price, 4), now_ms, "simulator")
        self._tick_count += 1
        self._last_tick_ms = now_ms
        await self.cache.apply(ticks)

    async def set_tickers(self, tickers: set[str]) -> None:
        await super().set_tickers(tickers)
        for t in list(self._state):  # forget state for dropped tickers
            if t not in self._tickers:
                del self._state[t]

    def health(self) -> dict:
        return {
            **super().health(),
            "ticks": self._tick_count,
            "tick_ms": self._cfg.sim_tick_ms,
            "last_tick_ms": self._last_tick_ms,
            "seeded": self._cfg.sim_seed is not None,
        }

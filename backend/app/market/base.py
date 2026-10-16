"""Abstract market data source.

See planning/MARKET_INTERFACE.md §5.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from .cache import PriceCache
from .types import Quote


class MarketDataSource(ABC):
    """Produces price ticks for a mutable set of tickers into a PriceCache."""

    name: str = "abstract"  # "simulator" | "massive:snapshot" | "massive:eod"

    def __init__(self, cache: PriceCache):
        self.cache = cache
        self._tickers: set[str] = set()
        self._task: asyncio.Task | None = None

    # ---- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        """Begin producing ticks. Idempotent. Must return promptly (spawn a task)."""
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"market:{self.name}")

    async def stop(self) -> None:
        """Cancel the background task and release resources. Idempotent."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    # ---- ticker set -------------------------------------------------------
    async def set_tickers(self, tickers: set[str]) -> None:
        """Replace the priced set. Added tickers are primed before this returns;
        removed tickers are dropped from the cache."""
        added, removed = tickers - self._tickers, self._tickers - tickers
        self._tickers = set(tickers)
        for t in removed:
            self.cache.drop(t)
        if added:
            await self.prime(added)

    async def prime(self, tickers: set[str], timeout: float = 5.0) -> dict[str, Quote]:
        """Ensure each ticker has a price in the cache, fetching if needed. Returns what is
        now cached. Missing keys mean 'no price available'. This is what the trade service
        calls before pricing a buy for a symbol in neither watchlist nor positions."""
        missing = {t for t in tickers if self.cache.get(t) is None}
        if missing:
            await asyncio.wait_for(self._fetch_now(missing), timeout)
        return {t: q for t in tickers if (q := self.cache.get(t))}

    # ---- implementation hooks --------------------------------------------
    @abstractmethod
    async def _run(self) -> None:
        """The long-running loop. Must handle CancelledError and its own errors."""

    @abstractmethod
    async def _fetch_now(self, tickers: set[str]) -> None:
        """Produce a price for each ticker immediately and write it to the cache."""

    # ---- diagnostics ------------------------------------------------------
    def health(self) -> dict:
        """Merged into GET /api/health. At minimum {'name', 'tickers', 'last_tick_ms'}."""
        return {"name": self.name, "tickers": sorted(self._tickers)}

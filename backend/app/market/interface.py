"""Abstract market data source interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from .cache import PriceCache


class MarketDataSource(ABC):
    """A background producer that keeps a PriceCache up to date.

    Implementations: MarketSimulator (default) and MassiveClient (real data).
    Downstream code only depends on this interface and the cache.
    """

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @abstractmethod
    async def start(self, tickers: Iterable[str]) -> None:
        """Begin producing prices for the given tickers (starts background task)."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task. Safe to call multiple times."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start tracking a ticker."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking a ticker and drop it from the cache."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Currently tracked tickers."""

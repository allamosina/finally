"""In-memory price cache shared by the data source and SSE streams."""

from __future__ import annotations

import time

from .models import PriceUpdate


class PriceCache:
    """Holds the latest PriceUpdate per ticker. Written by one producer task."""

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._version = 0

    @property
    def version(self) -> int:
        """Increments on every write; lets streams detect changes cheaply."""
        return self._version

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        ticker = ticker.upper()
        prev = self._prices.get(ticker)
        price = round(price, 2)
        update = PriceUpdate(
            ticker=ticker,
            price=price,
            previous_price=prev.price if prev else price,
            timestamp=timestamp if timestamp is not None else time.time(),
        )
        self._prices[ticker] = update
        self._version += 1
        return update

    def get(self, ticker: str) -> PriceUpdate | None:
        return self._prices.get(ticker.upper())

    def get_price(self, ticker: str) -> float | None:
        update = self.get(ticker)
        return update.price if update else None

    def get_all(self) -> dict[str, PriceUpdate]:
        return dict(self._prices)

    def remove(self, ticker: str) -> None:
        if self._prices.pop(ticker.upper(), None) is not None:
            self._version += 1

    def __contains__(self, ticker: str) -> bool:
        return ticker.upper() in self._prices

    def __len__(self) -> int:
        return len(self._prices)

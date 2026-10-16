"""Data types shared by every market data source and every consumer.

See planning/MARKET_INTERFACE.md §3.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Tick:
    """One observed price for one ticker."""

    ts_ms: int  # Unix milliseconds, UTC
    price: float


@dataclass
class Quote:
    """Everything the cache knows about one ticker. Mutable; owned by PriceCache."""

    ticker: str
    price: float
    prev_price: float  # previous tick's price (for direction/flash)
    session_open: float  # reference for change_pct (seed at start | previous close)
    ts_ms: int  # when `price` was observed
    source: str  # "simulator" | "last_trade" | "last_minute" | "session_close" | "eod_close"
    history: deque[Tick] = field(default_factory=lambda: deque(maxlen=600))

    @property
    def direction(self) -> str:
        if self.price > self.prev_price:
            return "up"
        if self.price < self.prev_price:
            return "down"
        return "flat"

    @property
    def change_pct(self) -> float:
        if not self.session_open:
            return 0.0
        return (self.price / self.session_open - 1.0) * 100.0


@dataclass(frozen=True)
class PriceSnapshot:
    """What one SSE event carries: all priced tickers at one instant."""

    ts_ms: int
    quotes: tuple[Quote, ...]

"""Shared data types for market data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Latest price for a ticker, with the previous price for change direction."""

    ticker: str
    price: float
    previous_price: float
    timestamp: float  # unix seconds

    @property
    def direction(self) -> str:
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def change(self) -> float:
        return self.price - self.previous_price

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "direction": self.direction,
        }

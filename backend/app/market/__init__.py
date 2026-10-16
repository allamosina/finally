"""Market data: one abstract source, a shared price cache, and the simulator.

This is the only module the rest of the backend needs to import. See
planning/MARKET_INTERFACE.md for the contract.
"""

from __future__ import annotations

import logging

from .base import MarketDataSource
from .cache import PriceCache
from .config import MarketConfig
from .simulator import SimulatorSource
from .types import PriceSnapshot, Quote, Tick

log = logging.getLogger(__name__)

__all__ = [
    "MarketConfig",
    "MarketDataSource",
    "PriceCache",
    "PriceSnapshot",
    "Quote",
    "SimulatorSource",
    "Tick",
    "build_source",
]


def build_source(cache: PriceCache, cfg: MarketConfig) -> MarketDataSource:
    """Core build: always the simulator (PLAN.md §5, §6). The Massive source is a stretch
    goal; a set MASSIVE_API_KEY is noted and ignored rather than failing startup."""
    if cfg.massive_api_key:
        log.warning("MASSIVE_API_KEY is set but the Massive source is not implemented; using the simulator")
    return SimulatorSource(cache, cfg)

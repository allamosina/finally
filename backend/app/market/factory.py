"""Select the market data source from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import MassiveClient
from .simulator import MarketSimulator


def create_market_source(cache: PriceCache, env: Mapping[str, str] | None = None) -> MarketDataSource:
    env = os.environ if env is None else env
    key = (env.get("MASSIVE_API_KEY") or "").strip()
    if key:
        interval = float(env.get("MASSIVE_POLL_INTERVAL") or 15)
        return MassiveClient(cache, api_key=key, poll_interval=interval)
    return MarketSimulator(cache)

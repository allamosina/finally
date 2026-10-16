"""Process-wide handle on the price cache and the market data source.

`app.main`'s lifespan installs them with `install()`; services and the LLM module read
them with `cache()` / `source()` instead of reaching into `request.app.state`, so code
outside a request (the snapshot task, the LLM executor) has the same access.
"""

from __future__ import annotations

from app.market import MarketDataSource, PriceCache

_cache: PriceCache | None = None
_source: MarketDataSource | None = None


def install(cache: PriceCache, source: MarketDataSource) -> None:
    global _cache, _source
    _cache, _source = cache, source


def clear() -> None:
    global _cache, _source
    _cache = _source = None


def cache() -> PriceCache:
    if _cache is None:
        raise RuntimeError("market data not started (app lifespan has not run)")
    return _cache


def source() -> MarketDataSource:
    if _source is None:
        raise RuntimeError("market data not started (app lifespan has not run)")
    return _source

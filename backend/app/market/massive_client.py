"""Massive (Polygon.io) REST poller. Implements MarketDataSource."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

import httpx

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygon.io"
SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"


def parse_snapshot(payload: dict) -> dict[str, tuple[float, float | None]]:
    """Parse a multi-ticker snapshot response into {ticker: (price, timestamp_s or None)}.

    Price prefers the last trade, then the current minute close, then the day close.
    Entries without a usable price are skipped.
    """
    out: dict[str, tuple[float, float | None]] = {}
    for item in payload.get("tickers") or []:
        ticker = item.get("ticker")
        if not ticker:
            continue
        last_trade = item.get("lastTrade") or {}
        price = last_trade.get("p")
        ts = last_trade.get("t")  # nanoseconds
        if not price:
            price = (item.get("min") or {}).get("c") or (item.get("day") or {}).get("c")
            ts = None
        if not price or price <= 0:
            continue
        out[ticker.upper()] = (float(price), ts / 1e9 if ts else None)
    return out


class MassiveClient(MarketDataSource):
    def __init__(
        self,
        cache: PriceCache,
        api_key: str,
        poll_interval: float = 15.0,
        base_url: str = BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(cache)
        self.api_key = api_key
        self.poll_interval = poll_interval
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=10.0)
        self._tickers: set[str] = set()
        self._task: asyncio.Task | None = None

    async def start(self, tickers: Iterable[str]) -> None:
        self._tickers.update(t.upper() for t in tickers)
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
        await self._client.aclose()

    async def add_ticker(self, ticker: str) -> None:
        self._tickers.add(ticker.upper())

    async def remove_ticker(self, ticker: str) -> None:
        t = ticker.upper()
        self._tickers.discard(t)
        self.cache.remove(t)

    def get_tickers(self) -> list[str]:
        return sorted(self._tickers)

    async def poll_once(self) -> int:
        """Fetch one snapshot for all tickers; returns number of cache updates."""
        if not self._tickers:
            return 0
        resp = await self._client.get(
            SNAPSHOT_PATH,
            params={"tickers": ",".join(sorted(self._tickers)), "apiKey": self.api_key},
        )
        resp.raise_for_status()
        updated = 0
        for ticker, (price, ts) in parse_snapshot(resp.json()).items():
            if ticker in self._tickers:
                self.cache.update(ticker, price, ts)
                updated += 1
        return updated

    async def _run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep polling through transient failures
                logger.warning("Massive poll failed: %s", type(exc).__name__)
            await asyncio.sleep(self.poll_interval)

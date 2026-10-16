"""In-memory price cache: sources write, everyone else reads.

See planning/MARKET_INTERFACE.md §4.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque

from .types import PriceSnapshot, Quote, Tick


class PriceCache:
    def __init__(self, history_len: int = 600):
        self._quotes: dict[str, Quote] = {}
        self._history_len = history_len
        self._version = 0
        self._changed = asyncio.Condition()

    # ---- write side (sources only) ---------------------------------------
    async def apply(
        self,
        ticks: dict[str, tuple[float, int, str]],
        session_open: dict[str, float] | None = None,
    ) -> None:
        """Atomically apply one batch: {ticker: (price, ts_ms, source)}. Wakes SSE waiters once."""
        async with self._changed:
            for ticker, (price, ts_ms, source) in ticks.items():
                q = self._quotes.get(ticker)
                if q is None:
                    so = (session_open or {}).get(ticker, price)
                    q = Quote(ticker, price, price, so, ts_ms, source, deque(maxlen=self._history_len))
                    self._quotes[ticker] = q
                else:
                    q.prev_price, q.price, q.ts_ms, q.source = q.price, price, ts_ms, source
                q.history.append(Tick(ts_ms, price))
            self._version += 1
            self._changed.notify_all()

    def drop(self, ticker: str) -> None:
        self._quotes.pop(ticker, None)

    # ---- read side -------------------------------------------------------
    @property
    def version(self) -> int:
        return self._version

    def get(self, ticker: str) -> Quote | None:
        return self._quotes.get(ticker)

    def snapshot(self) -> PriceSnapshot:
        return PriceSnapshot(int(time.time() * 1000), tuple(self._quotes.values()))

    def history(self, ticker: str) -> list[Tick]:
        q = self._quotes.get(ticker)
        return list(q.history) if q else []

    def tickers(self) -> set[str]:
        return set(self._quotes)

    async def wait_for_change(self, last_seen: int) -> int:
        """Block until version > last_seen. SSE handlers use this instead of polling."""
        async with self._changed:
            await self._changed.wait_for(lambda: self._version > last_seen)
            return self._version

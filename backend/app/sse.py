"""Server-Sent Events for GET /api/stream/prices (PLAN §6, MARKET_INTERFACE.md §9).

One `prices` event per cache change carrying every priced ticker. The first event on a
connection is a full snapshot (sent immediately if the cache has any quotes), so a
reconnect needs no extra state. A `: ping` comment goes out after `ping_interval`
seconds without a change.

While the cache is empty (nothing in watchlist or positions) the simulator writes nothing,
so the stream sends `{"prices": []}` every `empty_heartbeat` seconds instead. `EventSource`
cannot see comments, and the frontend treats ~3 s without an event as a stale connection.
Non-empty snapshots are never re-sent without a change, so no spurious price flashes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from app.market import PriceCache, PriceSnapshot, Quote

RETRY_MS = 2000
PING_INTERVAL_S = 15.0
EMPTY_HEARTBEAT_S = 1.0


def iso_z(ts_ms: int) -> str:
    """Unix milliseconds -> ISO-8601 UTC with millisecond precision and a Z suffix."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts_ms % 1000:03d}Z"


def quote_row(q: Quote) -> dict:
    """One ticker as the SSE stream and GET /api/watchlist present it."""
    return {
        "ticker": q.ticker,
        "price": round(q.price, 4),
        "prev_price": round(q.prev_price, 4),
        "session_open": round(q.session_open, 4),
        "change_pct": round(q.change_pct, 4),
        "direction": q.direction,
    }


def to_sse_payload(snap: PriceSnapshot) -> dict:
    """The exact `data:` object of one `prices` event (PLAN §6)."""
    return {
        "ts": iso_z(snap.ts_ms),
        "prices": [quote_row(q) for q in sorted(snap.quotes, key=lambda q: q.ticker)],
    }


def format_event(snap: PriceSnapshot) -> str:
    return f"event: prices\ndata: {json.dumps(to_sse_payload(snap), separators=(',', ':'))}\n\n"


async def event_stream(
    cache: PriceCache,
    ping_interval: float = PING_INTERVAL_S,
    empty_heartbeat: float = EMPTY_HEARTBEAT_S,
) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    yield f"retry: {RETRY_MS}\n\n"
    version = cache.version
    yield format_event(cache.snapshot())  # full snapshot on connect (possibly empty)
    last_ping = loop.time()
    while True:
        empty = not cache.tickers()
        timeout = min(empty_heartbeat, ping_interval) if empty else ping_interval
        try:
            version = await asyncio.wait_for(cache.wait_for_change(version), timeout=timeout)
            yield format_event(cache.snapshot())
            continue
        except asyncio.TimeoutError:
            pass
        if not cache.tickers():
            yield format_event(cache.snapshot())  # {"prices": []} heartbeat
        if loop.time() - last_ping >= ping_interval:
            last_ping = loop.time()
            yield ": ping\n\n"

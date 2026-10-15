"""SSE endpoint streaming prices from the shared cache."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache


async def price_events(
    cache: PriceCache,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
    interval: float = 0.5,
) -> AsyncIterator[str]:
    """Yield SSE frames, one per ticker, whenever the cache changes."""
    yield "retry: 1000\n\n"
    last_version = -1
    while True:
        if is_disconnected is not None and await is_disconnected():
            return
        if cache.version != last_version:
            last_version = cache.version
            for update in cache.get_all().values():
                yield "data: " + json.dumps(update.to_dict()) + "\n\n"
        await asyncio.sleep(interval)


def create_stream_router(cache: PriceCache, interval: float = 0.5) -> APIRouter:
    router = APIRouter()

    @router.get("/api/stream/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        return StreamingResponse(
            price_events(cache, request.is_disconnected, interval),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router

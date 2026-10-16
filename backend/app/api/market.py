"""Market data routes: the SSE price stream and per-ticker history (PLAN §6, §8)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app import sse
from app.services import market
from app.services.validation import normalize_ticker

router = APIRouter(prefix="/api", tags=["market"])


@router.get("/stream/prices")
async def stream_prices(request: Request) -> StreamingResponse:
    ping = getattr(request.app.state, "sse_ping_interval", sse.PING_INTERVAL_S)
    return StreamingResponse(
        sse.event_stream(market.cache(), ping_interval=ping),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/prices/{ticker}/history")
async def price_history(ticker: str) -> list[dict]:
    """Ring buffer for chart seeding, oldest first. An unpriced ticker returns [] (200)."""
    symbol = normalize_ticker(ticker)
    return [{"ts": sse.iso_z(t.ts_ms), "price": round(t.price, 4)} for t in market.cache().history(symbol)]

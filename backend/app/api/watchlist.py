"""Watchlist routes (PLAN §8). GET returns a bare array of
`{ticker, price, prev_price, session_open, change_pct, direction}`; the price fields are
null for a ticker with no price yet (normally never, since the watchlist is primed)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db import repo
from app.services import market, portfolio
from app.services.validation import normalize_ticker
from app.sse import quote_row

router = APIRouter(prefix="/api", tags=["watchlist"])
_NO_PRICE = {"price": None, "prev_price": None, "session_open": None, "change_pct": None, "direction": None}


class WatchlistRequest(BaseModel):
    ticker: str


def _item(ticker: str) -> dict:
    q = market.cache().get(ticker)
    return quote_row(q) if q else {"ticker": ticker, **_NO_PRICE}


@router.get("/watchlist")
async def get_watchlist() -> list[dict]:
    return [_item(t) for t in await repo.list_watchlist()]


@router.post("/watchlist")
async def add_to_watchlist(body: WatchlistRequest) -> JSONResponse:
    """201 with the item when added; 200 with the item when it was already present."""
    symbol = normalize_ticker(body.ticker)
    added = await portfolio.watchlist_add(symbol)
    return JSONResponse(_item(symbol), status_code=201 if added else 200)


@router.delete("/watchlist/{ticker}")
async def remove_from_watchlist(ticker: str) -> dict:
    symbol = normalize_ticker(ticker)
    if not await portfolio.watchlist_remove(symbol):
        raise HTTPException(status_code=404, detail=f"{symbol} is not in the watchlist")
    return {"ticker": symbol, "removed": True}

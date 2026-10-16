"""Portfolio routes (PLAN §8)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.db import repo
from app.services import portfolio
from app.services.validation import InvalidInput

router = APIRouter(prefix="/api", tags=["portfolio"])


class TradeRequest(BaseModel):
    ticker: str
    quantity: float
    side: str


@router.get("/portfolio")
async def get_portfolio() -> dict:
    return (await portfolio.view()).to_dict()


@router.post("/portfolio/trade")
async def post_trade(body: TradeRequest) -> dict:
    trade, view = await portfolio.trade(body.ticker, body.side, body.quantity)
    return {"trade": portfolio.trade_dict(trade), "portfolio": view.to_dict()}


def _normalize_since(raw: str) -> str:
    """Accept any ISO-8601 instant; reformat to the stored `...T..:..:..mmmZ` form so the
    repo's string comparison is exact. A naive timestamp is taken as UTC."""
    try:
        dt = datetime.fromisoformat(raw.strip().replace("z", "Z"))
    except ValueError:
        raise InvalidInput(f"Invalid 'since' timestamp {raw!r}: expected ISO-8601") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@router.get("/portfolio/history")
async def get_history(limit: int = Query(500, ge=1, le=10_000), since: str | None = None) -> list[dict]:
    rows = await repo.list_snapshots(limit=limit, since=_normalize_since(since) if since else None)
    return [{"recorded_at": s.recorded_at, "total_value": round(s.total_value, 4)} for s in rows]


@router.post("/reset")
async def post_reset() -> dict:
    view = await portfolio.reset()
    return {"status": "ok", "portfolio": view.to_dict()}

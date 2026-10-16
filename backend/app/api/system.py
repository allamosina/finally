"""System routes: GET /api/health (PLAN §8)."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import db, llm
from app.services import market

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["system"])


async def _db_status() -> str:
    try:
        async with db.connect() as conn:
            await conn.execute("SELECT 1 FROM users_profile LIMIT 1")
        return "ok"
    except Exception:  # noqa: BLE001 - health must report, never raise
        log.exception("health: database check failed")
        return "error"


@router.get("/health")
async def health() -> JSONResponse:
    source = market.source()
    db_state = await _db_status()
    body = {
        "status": "ok" if db_state == "ok" else "error",
        "market_data": source.name,
        "llm": llm.status(),
        "db": db_state,
        "market": source.health(),
    }
    return JSONResponse(body, status_code=200 if db_state == "ok" else 503)

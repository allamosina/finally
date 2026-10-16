"""FinAlly FastAPI application: lifespan wiring, routers, static frontend.

Run locally from backend/:  uv run uvicorn app.main:app --port 8000
In Docker:                  uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1

Exactly one worker: the price cache is process-local (MARKET_INTERFACE.md §4).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import db
from app.api import chat as chat_routes
from app.api import market as market_routes
from app.api import portfolio as portfolio_routes
from app.api import system as system_routes
from app.api import watchlist as watchlist_routes
from app.api.spa import mount_frontend
from app.db import repo
from app.market import MarketConfig, PriceCache, build_source
from app.services import market, portfolio, snapshots
from app.services.portfolio import PriceUnavailable
from app.services.validation import InvalidInput

log = logging.getLogger("finally")

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_local_env() -> None:
    """Local `uv run` development only (PLAN §5). In Docker the variables arrive via
    `--env-file` and no .env is in the image; override=False so real env always wins.
    FINALLY_SKIP_DOTENV=1 disables it (the test suite sets this)."""
    if os.environ.get("FINALLY_SKIP_DOTENV") == "1":
        return
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()  # FINALLY_DB_PATH or <repo root>/db/finally.db
    cache = PriceCache()
    source = build_source(cache, MarketConfig.from_env())
    market.install(cache, source)
    app.state.cache, app.state.source = cache, source
    await source.set_tickers(await repo.priced_set())  # watchlist ∪ positions, primed
    await source.start()
    await portfolio.record_snapshot()  # first P&L point exists before any request
    snapshot_task = snapshots.start()
    log.info("market data: %s, %d tickers", source.name, len(source.health()["tickers"]))
    try:
        yield
    finally:
        await snapshots.stop(snapshot_task)
        await source.stop()
        market.clear()


def create_app(static_dir: str | Path | None = None) -> FastAPI:
    load_local_env()
    # litellm (imported lazily by app.llm) downloads a model-cost map on import unless told
    # not to, and the container may have no outbound network. Real env or .env can override.
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    app = FastAPI(title="FinAlly", lifespan=lifespan)

    @app.exception_handler(InvalidInput)
    async def _invalid_input(_: Request, exc: InvalidInput) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(repo.TradeError)
    async def _trade_error(_: Request, exc: repo.TradeError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(PriceUnavailable)
    async def _price_unavailable(_: Request, exc: PriceUnavailable) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    app.include_router(market_routes.router)
    app.include_router(system_routes.router)
    app.include_router(portfolio_routes.router)
    app.include_router(watchlist_routes.router)
    app.include_router(chat_routes.router)
    # The SPA catch-all must be registered after every API router.
    mount_frontend(app, static_dir if static_dir is not None else os.environ.get("STATIC_DIR", "static"))
    return app


app = create_app()

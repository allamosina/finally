"""Background task: record total portfolio value every 30 s (PLAN §7).

Trades record their own snapshot inside the trade transaction; this task fills the time
between trades so the P&L chart moves with prices. `SNAPSHOT_INTERVAL_S` overrides the
interval (tests use a small value). The app lifespan records the first snapshot
synchronously before starting this loop, so the P&L chart has a point from the first request.
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.services import portfolio

log = logging.getLogger(__name__)
DEFAULT_INTERVAL_S = 30.0


def interval_from_env() -> float:
    return float(os.environ.get("SNAPSHOT_INTERVAL_S") or DEFAULT_INTERVAL_S)


async def run(interval: float = DEFAULT_INTERVAL_S) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await portfolio.record_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception:  # never let the loop die
            log.exception("portfolio snapshot failed")


def start(interval: float | None = None) -> asyncio.Task:
    return asyncio.create_task(run(interval if interval is not None else interval_from_env()), name="snapshots")


async def stop(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

"""`chat()`: PLAN §9 steps 1-8 end to end."""

from __future__ import annotations

import dataclasses
from typing import Any

from app.db import repo

from .client import get_structured_reply
from .config import HISTORY_LIMIT, is_mock, status
from .executor import execute_actions
from .mock import mock_reply
from .prompt import build_messages
from .schemas import ChatResponse

POSITION_KEYS = ("ticker", "quantity", "avg_cost", "current_price", "unrealized_pnl", "pnl_pct")


class LLMNotConfigured(RuntimeError):
    """Raised by chat() when neither LLM_MOCK=true nor an API key is set (route returns 503)."""


def _portfolio() -> Any:
    from app.services import portfolio  # lazy: tests monkeypatch this function

    return portfolio


def _prices() -> Any:
    from app.services import market

    return market.cache()


def _as_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return dict(vars(obj))


async def build_context() -> dict[str, Any]:
    """Cash, positions (exact quantities, P&L), watchlist with live prices, total value."""
    view = _as_dict(await _portfolio().view())
    positions = [
        {k: _as_dict(p).get(k) for k in POSITION_KEYS} for p in view.get("positions", [])
    ]
    cache = _prices()
    watchlist = []
    for ticker in await repo.list_watchlist():
        q = cache.get(ticker)
        watchlist.append({"ticker": ticker, "price": None if q is None else q.price})
    return {
        "cash_balance": view.get("cash_balance"),
        "total_value": view.get("total_value"),
        "unrealized_pnl": view.get("unrealized_pnl"),
        "positions": positions,
        "watchlist": watchlist,
    }


async def chat(message: str) -> ChatResponse:
    if status() == "unconfigured":
        raise LLMNotConfigured("LLM not configured")

    ctx = await build_context()
    rows = await repo.list_chat(HISTORY_LIMIT)
    history = [_as_dict(r) for r in rows]

    if is_mock():
        output = mock_reply(message, ctx)
    else:
        output = await get_structured_reply(build_messages(ctx, history, message))

    actions = await execute_actions(output, _portfolio())

    await repo.add_chat("user", message, None)
    await repo.add_chat("assistant", output.message, actions.model_dump())
    return ChatResponse(message=output.message, actions=actions)

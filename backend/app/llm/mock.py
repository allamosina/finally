"""Deterministic mock LLM (LLM_MOCK=true). Never touches the network."""

from __future__ import annotations

import re
from typing import Any

from .schemas import LLMOutput, LLMTrade, LLMWatchlistChange

PREFIX = "[mock] "

_TRADE = re.compile(r"\b(buy|sell)\s+(\d+(?:\.\d+)?|\.\d+)\s+([A-Za-z]{1,5})\b", re.IGNORECASE)
_WATCH = re.compile(r"\b(add|remove)\s+([A-Za-z]{1,5})\b", re.IGNORECASE)


def _money(x: float) -> str:
    return f"${x:,.2f}"


def summarize(ctx: dict[str, Any]) -> str:
    """Canned portfolio summary from the real context (shape: see executor/context docs)."""
    positions = ctx.get("positions") or []
    watch = [w.get("ticker") if isinstance(w, dict) else w for w in ctx.get("watchlist") or []]
    parts = [
        f"Portfolio value {_money(ctx.get('total_value', 0.0))}, cash {_money(ctx.get('cash_balance', 0.0))}."
    ]
    if positions:
        rows = ", ".join(
            f"{p['ticker']} {p['quantity']:g} sh ({_money(p.get('unrealized_pnl', 0.0))})" for p in positions
        )
        parts.append(f"Positions: {rows}.")
    else:
        parts.append("No open positions.")
    if watch:
        parts.append("Watching: " + ", ".join(watch) + ".")
    return " ".join(parts)


def mock_reply(user_message: str, ctx: dict[str, Any]) -> LLMOutput:
    trades = [
        LLMTrade(ticker=m.group(3), side=m.group(1).lower(), quantity=float(m.group(2)))
        for m in _TRADE.finditer(user_message)
        # a zero quantity is not a valid LLM trade; let it fall through to the summary
        if float(m.group(2)) > 0
    ]
    changes = [
        LLMWatchlistChange(ticker=m.group(2), action=m.group(1).lower())
        for m in _WATCH.finditer(user_message)
    ]
    if trades or changes:
        bits = [f"{t.side} {t.quantity:g} {t.ticker}" for t in trades]
        bits += [f"{c.action} {c.ticker}" for c in changes]
        message = "Placing: " + "; ".join(bits) + "."
    else:
        message = summarize(ctx)
    return LLMOutput(message=PREFIX + message, trades=trades, watchlist_changes=changes)

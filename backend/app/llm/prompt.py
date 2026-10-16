"""System prompt and message construction."""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant inside a simulated trading workstation. \
The user trades a virtual portfolio with fake money using market orders only.

Your job:
- Analyze portfolio composition, risk concentration and P&L using the portfolio context provided.
- Suggest trades with brief reasoning.
- Execute trades when the user asks or clearly agrees, by listing them in `trades`. Compute exact \
quantities from the context (for example "sell all AAPL" means the exact held quantity). Quantities \
may be fractional.
- Manage the watchlist proactively through `watchlist_changes` (action "add" or "remove").
- Be concise and data-driven.

Hard rules:
- Always respond with valid JSON matching the required schema: `message` (string), `trades` (array), \
`watchlist_changes` (array). Use empty arrays when there is nothing to do.
- NEVER claim that a trade or watchlist change succeeded. Orders are validated after your reply and may \
fail (insufficient cash, insufficient shares, bad ticker). Phrase actions as "placing an order for ..." \
or "adding X to your watchlist now". Earlier assistant turns show an `actions` record with the real \
status of each action; use it to acknowledge failures honestly.
- Only include a trade when the user wants one. Do not trade on your own initiative.
- Tickers are 1 to 5 letters, uppercase."""


def format_context(ctx: dict[str, Any]) -> str:
    """Render the portfolio context as compact JSON for the model."""
    return "Current portfolio context (live):\n" + json.dumps(ctx, separators=(",", ":"), default=str)


def format_history_row(row: dict[str, Any]) -> dict[str, str]:
    """Turn a stored chat row into a model message, surfacing action outcomes."""
    content = row.get("content") or ""
    actions = row.get("actions")
    if row.get("role") == "assistant" and actions:
        content += "\n[actions: " + json.dumps(actions, separators=(",", ":"), default=str) + "]"
    return {"role": row["role"], "content": content}


def build_messages(
    context: dict[str, Any], history: list[dict[str, Any]], user_message: str
) -> list[dict[str, str]]:
    """System message + context, then history (oldest first), then the new user message."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + format_context(context)},
        *(format_history_row(r) for r in history),
        {"role": "user", "content": user_message},
    ]

"""Input validation shared by every route and by the LLM action executor (PLAN §6, §8).

Raises `InvalidInput`; `app.main` maps it to `422 {"detail": "..."}`.
"""

from __future__ import annotations

import math
import re

TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
QTY_DECIMALS = 4


class InvalidInput(ValueError):
    """Malformed input (HTTP 422). `str(exc)` is the human-readable detail."""


def normalize_ticker(raw: object) -> str:
    """Uppercase and validate a ticker against ^[A-Z]{1,5}$."""
    if not isinstance(raw, str):
        raise InvalidInput("Ticker must be a string")
    ticker = raw.strip().upper()
    if not TICKER_RE.fullmatch(ticker):
        raise InvalidInput(f"Invalid ticker {raw.strip()!r}: must be 1-5 letters")
    return ticker


def normalize_quantity(raw: object) -> float:
    """A finite number > 0, rounded to 4 decimals (fractional shares allowed)."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise InvalidInput("Quantity must be a number")
    qty = float(raw)
    if not math.isfinite(qty):
        raise InvalidInput("Quantity must be finite")
    qty = round(qty, QTY_DECIMALS)
    if qty <= 0:
        raise InvalidInput("Quantity must be greater than 0")
    return qty

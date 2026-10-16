"""Action executor: runs LLM-requested trades and watchlist changes through the real services.

Interface:
    await execute_actions(output: LLMOutput, portfolio=None) -> Actions

`portfolio` is any object exposing the services.portfolio seam (TEAM.md §2.2):
    async trade(ticker, side, quantity) -> (Trade, PortfolioView)
    async watchlist_add(ticker) / watchlist_remove(ticker)
Defaults to `app.services.portfolio`, imported lazily. Each action is attempted independently;
a failure is recorded (status="failed", error=<message>) and never aborts the rest.
"""

from __future__ import annotations

from typing import Any

from .schemas import Actions, LLMOutput, TradeAction, WatchlistAction


def error_text(exc: Exception) -> str:
    """Human-readable message from an HTTPException-like or ordinary exception."""
    detail = getattr(exc, "detail", None)
    if detail:
        return str(detail)
    return str(exc) or exc.__class__.__name__


def _price_of(trade: Any) -> float | None:
    price = trade.get("price") if isinstance(trade, dict) else getattr(trade, "price", None)
    return None if price is None else float(price)


async def execute_actions(output: LLMOutput, portfolio: Any = None) -> Actions:
    if portfolio is None:
        from app.services import portfolio  # type: ignore[no-redef]

    actions = Actions()

    for t in output.trades:
        try:
            result = await portfolio.trade(t.ticker, t.side, t.quantity)
            trade = result[0] if isinstance(result, tuple) else result
            actions.trades.append(
                TradeAction(
                    ticker=t.ticker, side=t.side, quantity=t.quantity,
                    price=_price_of(trade), status="executed",
                )
            )
        except Exception as e:  # noqa: BLE001 - every failure is reported inline to the user
            actions.trades.append(
                TradeAction(
                    ticker=t.ticker, side=t.side, quantity=t.quantity,
                    price=None, status="failed", error=error_text(e),
                )
            )

    for c in output.watchlist_changes:
        fn = portfolio.watchlist_add if c.action == "add" else portfolio.watchlist_remove
        try:
            res = await fn(c.ticker)
            if res is False:
                err = "Already in watchlist" if c.action == "add" else "Not in watchlist"
                actions.watchlist_changes.append(
                    WatchlistAction(ticker=c.ticker, action=c.action, status="failed", error=err)
                )
            else:
                actions.watchlist_changes.append(
                    WatchlistAction(ticker=c.ticker, action=c.action, status="executed")
                )
        except Exception as e:  # noqa: BLE001
            actions.watchlist_changes.append(
                WatchlistAction(ticker=c.ticker, action=c.action, status="failed", error=error_text(e))
            )

    return actions

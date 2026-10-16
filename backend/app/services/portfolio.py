"""Portfolio service: the only trade path (TEAM.md §2.2).

Both `POST /api/portfolio/trade` and the LLM action executor call `trade()`, so there is
one validation and one error vocabulary:

- `InvalidInput`     -> 422  (bad ticker, side or quantity)
- `PriceUnavailable` -> 503  (no price could be obtained for the ticker)
- `repo.TradeError`  -> 400  (InsufficientCash / InsufficientShares, PLAN §8 wording)

`str(exc)` is always the human-readable detail. Every mutation re-syncs the market
source to `watchlist ∪ positions` afterwards (PLAN §6).
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass

from app.db import repo
from app.services import market
from app.services.validation import InvalidInput, normalize_quantity, normalize_ticker

PRIME_TIMEOUT_S = 5.0


class PriceUnavailable(Exception):
    """No price for the ticker (HTTP 503)."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        super().__init__(f"Price unavailable for {ticker}")


@dataclass(frozen=True)
class PositionView:
    ticker: str
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    pnl_pct: float


@dataclass(frozen=True)
class PortfolioView:
    cash_balance: float
    total_value: float
    unrealized_pnl: float
    positions: list[PositionView]

    def to_dict(self) -> dict:
        return asdict(self)


def trade_dict(t: repo.Trade) -> dict:
    return asdict(t)


# One trade at a time: prime -> price -> transaction -> re-sync must not interleave.
# Created per event loop so test suites that run many loops stay safe.
_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None


def _trade_lock() -> asyncio.Lock:
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock, _lock_loop = asyncio.Lock(), loop
    return _lock


def _r(x: float, nd: int = 4) -> float:
    return round(x, nd) + 0.0  # + 0.0 turns -0.0 into 0.0


async def _value(overrides: dict[str, float] | None = None) -> PortfolioView:
    profile = await repo.get_profile()
    positions = await repo.list_positions()
    cache = market.cache()
    rows: list[PositionView] = []
    for p in positions:
        q = cache.get(p.ticker)
        price = (overrides or {}).get(p.ticker) or (q.price if q else p.avg_cost)
        mv = p.quantity * price
        pnl = mv - p.quantity * p.avg_cost
        pct = (price / p.avg_cost - 1.0) * 100.0 if p.avg_cost else 0.0
        rows.append(PositionView(p.ticker, p.quantity, _r(p.avg_cost), _r(price), _r(mv), _r(pnl), _r(pct)))
    invested = sum(r.market_value for r in rows)
    return PortfolioView(
        cash_balance=_r(profile.cash_balance),
        total_value=_r(profile.cash_balance + invested),
        unrealized_pnl=_r(sum(r.unrealized_pnl for r in rows)),
        positions=rows,
    )


async def view() -> PortfolioView:
    """The GET /api/portfolio object, positions priced from the live cache."""
    return await _value()


async def sync_priced_set() -> None:
    await market.source().set_tickers(await repo.priced_set())


async def trade(ticker: str, side: str, quantity: float) -> tuple[repo.Trade, PortfolioView]:
    symbol = normalize_ticker(ticker)
    side_n = side.strip().lower() if isinstance(side, str) else side
    if side_n not in ("buy", "sell"):
        raise InvalidInput(f"Invalid side {side!r}: must be 'buy' or 'sell'")
    qty = normalize_quantity(quantity)

    async with _trade_lock():
        try:
            try:
                quotes = await market.source().prime({symbol}, timeout=PRIME_TIMEOUT_S)
            except asyncio.TimeoutError:
                quotes = {}
            quote = quotes.get(symbol)
            if quote is None:
                raise PriceUnavailable(symbol)
            price = quote.price
            # A market order at the current price leaves total value unchanged, so the
            # post-trade snapshot is the pre-trade valuation at this same price.
            before = await _value({symbol: price})
            executed = await repo.execute_trade(symbol, side_n, qty, price, before.total_value)
        finally:
            await sync_priced_set()  # keeps a bought ticker; ages out one primed for a failed trade
    return executed, await view()


async def watchlist_add(ticker: str) -> bool:
    """True if added, False if it was already there."""
    symbol = normalize_ticker(ticker)
    added = await repo.add_watchlist(symbol)
    await sync_priced_set()
    return added


async def watchlist_remove(ticker: str) -> bool:
    """True if removed, False if it was not in the watchlist. A held ticker keeps streaming."""
    symbol = normalize_ticker(ticker)
    removed = await repo.remove_watchlist(symbol)
    await sync_priced_set()
    return removed


async def record_snapshot() -> float:
    total = (await view()).total_value
    await repo.record_snapshot(total)
    return total


async def reset() -> PortfolioView:
    """PLAN §7 reset, plus re-sync the priced set to the default watchlist and record a
    first snapshot so the P&L chart has a starting point."""
    async with _trade_lock():
        await repo.reset()
        await sync_priced_set()
        await record_snapshot()
    return await view()

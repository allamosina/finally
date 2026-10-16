"""Repository functions and the trade transaction (PLAN sections 7 and 8).

All functions take `user_id` (default "default"), open a short-lived
connection, and use ISO-8601 UTC timestamps with a Z suffix.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import aiosqlite

from . import DEFAULT_USER, BUSY_TIMEOUT_S, get_db_path, load_seed

TOLERANCE = 1e-6
QTY_DECIMALS = 4


# --------------------------------------------------------------------------- types


@dataclass(frozen=True)
class Profile:
    id: str
    cash_balance: float
    created_at: str


@dataclass(frozen=True)
class Position:
    ticker: str
    quantity: float
    avg_cost: float
    updated_at: str


@dataclass(frozen=True)
class Trade:
    id: str
    ticker: str
    side: str
    quantity: float
    price: float
    executed_at: str


@dataclass(frozen=True)
class Snapshot:
    recorded_at: str
    total_value: float


@dataclass(frozen=True)
class ChatMessage:
    id: str
    role: str
    content: str
    actions: dict | None
    created_at: str


class TradeError(Exception):
    """Business-rule rejection (HTTP 400). `str(exc)` is the PLAN section 8 detail."""


class InsufficientCash(TradeError):
    def __init__(self, need: float, have: float):
        self.need = need
        self.have = have
        super().__init__(f"Insufficient cash: need ${need:,.2f}, have ${have:,.2f}")


class InsufficientShares(TradeError):
    def __init__(self, have: float, selling: float):
        self.have = have
        self.selling = selling
        super().__init__(f"Insufficient shares: have {_fmt_qty(have)}, selling {_fmt_qty(selling)}")


# ------------------------------------------------------------------------- helpers


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _fmt_qty(x: float) -> str:
    """5.0 -> '5', 2.5 -> '2.5', 0.1235 -> '0.1235'."""
    s = f"{x:.{QTY_DECIMALS}f}".rstrip("0").rstrip(".")
    return s or "0"


def _norm(ticker: str) -> str:
    return ticker.strip().upper()


@asynccontextmanager
async def _session() -> AsyncIterator[aiosqlite.Connection]:
    """Short-lived connection with Row access. Transactions are explicit."""
    async with aiosqlite.connect(get_db_path(), timeout=BUSY_TIMEOUT_S, isolation_level=None) as db:
        db.row_factory = sqlite3.Row
        await db.execute("PRAGMA busy_timeout=10000")
        yield db


@asynccontextmanager
async def _write_tx() -> AsyncIterator[aiosqlite.Connection]:
    """BEGIN IMMEDIATE ... COMMIT, rolled back on any exception."""
    async with _session() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            yield db
        except BaseException:
            await db.execute("ROLLBACK")
            raise
        else:
            await db.execute("COMMIT")


# ------------------------------------------------------------------------ seeding


async def seed_if_empty() -> None:
    """Create the default profile and watchlist if no profile exists yet.

    Watchlist is only seeded together with a brand-new profile, so a user who
    deliberately emptied the watchlist does not get it back on restart.
    """
    seed = load_seed()
    async with _write_tx() as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
            (seed["user_id"], seed["cash_balance"], now_iso()),
        )
        if cur.rowcount == 1:
            await _insert_default_watchlist(db, seed)


async def _insert_default_watchlist(db: aiosqlite.Connection, seed: dict) -> None:
    ts = now_iso()
    await db.executemany(
        "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
        [(str(uuid.uuid4()), seed["user_id"], t, ts) for t in seed["watchlist"]],
    )


# ------------------------------------------------------------------------ profile


async def get_profile(user_id: str = DEFAULT_USER) -> Profile:
    async with _session() as db:
        cur = await db.execute(
            "SELECT id, cash_balance, created_at FROM users_profile WHERE id = ?", (user_id,)
        )
        row = await cur.fetchone()
    if row is None:
        raise LookupError(f"No profile for user {user_id!r}")
    return Profile(row["id"], row["cash_balance"], row["created_at"])


# ---------------------------------------------------------------------- watchlist


async def list_watchlist(user_id: str = DEFAULT_USER) -> list[str]:
    async with _session() as db:
        cur = await db.execute(
            "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at, rowid", (user_id,)
        )
        return [r["ticker"] for r in await cur.fetchall()]


async def add_watchlist(ticker: str, user_id: str = DEFAULT_USER) -> bool:
    """True if added, False if already present."""
    async with _write_tx() as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, _norm(ticker), now_iso()),
        )
        return cur.rowcount == 1


async def remove_watchlist(ticker: str, user_id: str = DEFAULT_USER) -> bool:
    """True if removed, False if absent (route maps False to 404)."""
    async with _write_tx() as db:
        cur = await db.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (user_id, _norm(ticker))
        )
        return cur.rowcount == 1


# ----------------------------------------------------------------------- positions


async def list_positions(user_id: str = DEFAULT_USER) -> list[Position]:
    async with _session() as db:
        cur = await db.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions "
            "WHERE user_id = ? ORDER BY ticker",
            (user_id,),
        )
        return [
            Position(r["ticker"], r["quantity"], r["avg_cost"], r["updated_at"])
            for r in await cur.fetchall()
        ]


async def priced_set(user_id: str = DEFAULT_USER) -> set[str]:
    """watchlist union positions: every ticker that must keep streaming."""
    async with _session() as db:
        cur = await db.execute(
            "SELECT ticker FROM watchlist WHERE user_id = ? "
            "UNION SELECT ticker FROM positions WHERE user_id = ?",
            (user_id, user_id),
        )
        return {r["ticker"] for r in await cur.fetchall()}


# -------------------------------------------------------------------------- trades


async def execute_trade(
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    total_value_after: float,
    user_id: str = DEFAULT_USER,
) -> Trade:
    """Validate and apply one market order in a single transaction.

    Buy: needs `quantity * price <= cash + 1e-6`; weighted-average cost.
    Sell: needs `quantity <= held + 1e-6`; avg_cost unchanged; the position row
    is deleted when the remainder is zero within tolerance.
    Appends a trades row and a portfolio_snapshots row (`total_value_after`).
    Raises InsufficientCash / InsufficientShares (nothing is written).
    """
    side = side.lower()
    if side not in ("buy", "sell"):
        raise ValueError(f"Invalid side: {side!r}")
    ticker = _norm(ticker)
    quantity = round(float(quantity), QTY_DECIMALS)
    if not quantity > 0 or quantity == float("inf"):
        raise ValueError("quantity must be a finite number > 0")
    if not price > 0 or price == float("inf"):
        raise ValueError("price must be a finite number > 0")

    ts = now_iso()
    async with _write_tx() as db:
        cur = await db.execute(
            "SELECT cash_balance FROM users_profile WHERE id = ?", (user_id,)
        )
        prof = await cur.fetchone()
        if prof is None:
            raise LookupError(f"No profile for user {user_id!r}")
        cash = prof["cash_balance"]

        cur = await db.execute(
            "SELECT quantity, avg_cost FROM positions WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        )
        pos = await cur.fetchone()
        held = pos["quantity"] if pos else 0.0
        avg = pos["avg_cost"] if pos else 0.0
        value = quantity * price

        if side == "buy":
            if value > cash + TOLERANCE:
                raise InsufficientCash(value, cash)
            new_cash = cash - value
            new_qty = held + quantity
            new_avg = (held * avg + value) / new_qty
            await db.execute(
                "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (user_id, ticker) DO UPDATE SET "
                "quantity = excluded.quantity, avg_cost = excluded.avg_cost, "
                "updated_at = excluded.updated_at",
                (str(uuid.uuid4()), user_id, ticker, round(new_qty, QTY_DECIMALS), new_avg, ts),
            )
        else:
            if quantity > held + TOLERANCE:
                raise InsufficientShares(held, quantity)
            new_cash = cash + value
            remaining = held - quantity
            if remaining <= TOLERANCE:
                await db.execute(
                    "DELETE FROM positions WHERE user_id = ? AND ticker = ?", (user_id, ticker)
                )
            else:
                await db.execute(
                    "UPDATE positions SET quantity = ?, updated_at = ? "
                    "WHERE user_id = ? AND ticker = ?",
                    (round(remaining, QTY_DECIMALS), ts, user_id, ticker),
                )

        await db.execute(
            "UPDATE users_profile SET cash_balance = ? WHERE id = ?", (new_cash, user_id)
        )
        trade_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (trade_id, user_id, ticker, side, quantity, price, ts),
        )
        await db.execute(
            "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, total_value_after, ts),
        )
    return Trade(trade_id, ticker, side, quantity, price, ts)


async def list_trades(limit: int = 100, user_id: str = DEFAULT_USER) -> list[Trade]:
    """Newest first. Not in the seam; handy for tests and debugging."""
    async with _session() as db:
        cur = await db.execute(
            "SELECT id, ticker, side, quantity, price, executed_at FROM trades "
            "WHERE user_id = ? ORDER BY executed_at DESC, rowid DESC LIMIT ?",
            (user_id, limit),
        )
        return [Trade(*tuple(r)) for r in await cur.fetchall()]


# ---------------------------------------------------------------------- snapshots


async def record_snapshot(total_value: float, user_id: str = DEFAULT_USER) -> None:
    async with _write_tx() as db:
        await db.execute(
            "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, total_value, now_iso()),
        )


async def list_snapshots(
    limit: int = 500, since: str | None = None, user_id: str = DEFAULT_USER
) -> list[Snapshot]:
    """The newest `limit` snapshots at or after `since`, oldest first (chart order)."""
    sql = "SELECT recorded_at, total_value FROM portfolio_snapshots WHERE user_id = ?"
    params: list[Any] = [user_id]
    if since is not None:
        sql += " AND recorded_at >= ?"
        params.append(since)
    sql += " ORDER BY recorded_at DESC, rowid DESC LIMIT ?"
    params.append(limit)
    async with _session() as db:
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
    return [Snapshot(r["recorded_at"], r["total_value"]) for r in reversed(rows)]


# --------------------------------------------------------------------------- chat


async def list_chat(limit: int = 50, user_id: str = DEFAULT_USER) -> list[ChatMessage]:
    """The most recent `limit` messages, oldest first."""
    async with _session() as db:
        cur = await db.execute(
            "SELECT id, role, content, actions, created_at FROM chat_messages "
            "WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cur.fetchall()
    return [
        ChatMessage(
            r["id"],
            r["role"],
            r["content"],
            json.loads(r["actions"]) if r["actions"] else None,
            r["created_at"],
        )
        for r in reversed(rows)
    ]


async def add_chat(
    role: str, content: str, actions: dict | None = None, user_id: str = DEFAULT_USER
) -> ChatMessage:
    if role not in ("user", "assistant"):
        raise ValueError(f"Invalid role: {role!r}")
    msg_id = str(uuid.uuid4())
    ts = now_iso()
    async with _write_tx() as db:
        await db.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, user_id, role, content, json.dumps(actions) if actions is not None else None, ts),
        )
    return ChatMessage(msg_id, role, content, actions, ts)


# -------------------------------------------------------------------------- reset


async def reset(user_id: str = DEFAULT_USER) -> None:
    """Restore seed state: no positions/trades/snapshots/chat, $10,000, default watchlist."""
    seed = load_seed()
    async with _write_tx() as db:
        for table in ("positions", "trades", "portfolio_snapshots", "chat_messages", "watchlist"):
            await db.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        await db.execute(
            "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET cash_balance = excluded.cash_balance",
            (user_id, seed["cash_balance"], now_iso()),
        )
        await _insert_default_watchlist(db, {**seed, "user_id": user_id})

"""SQLite access layer (PLAN section 7, TEAM.md section 2.1).

`init_db(path)` creates the file, enables WAL, applies the schema and seeds
default data on first run. `connect()` returns a short-lived connection; every
repository operation opens and closes its own.

Does not depend on the market package: the caller supplies prices.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import aiosqlite

# backend/app/db/__init__.py -> parents: [0]=app/db [1]=app [2]=backend [3]=repo root
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_SQL_DIR = _BACKEND_DIR / "db"  # schema.sql and seed.json live here
SCHEMA_PATH = _SQL_DIR / "schema.sql"
SEED_PATH = _SQL_DIR / "seed.json"

DEFAULT_USER = "default"
BUSY_TIMEOUT_S = 10.0

_db_path: str | None = None


def default_db_path() -> str:
    """`FINALLY_DB_PATH` if set, else `<repo root>/db/finally.db`."""
    env = os.environ.get("FINALLY_DB_PATH")
    if env:
        return env
    return str(_BACKEND_DIR.parent / "db" / "finally.db")


def get_db_path() -> str:
    return _db_path if _db_path is not None else default_db_path()


def load_seed() -> dict:
    return json.loads(SEED_PATH.read_text())


def connect() -> aiosqlite.Connection:
    """A new, not-yet-awaited connection: use `async with connect() as db`.

    Short-lived by design. Rows are plain tuples; use `repo` for typed access.
    """
    return aiosqlite.connect(get_db_path(), timeout=BUSY_TIMEOUT_S)


async def init_db(path: str | None = None) -> None:
    """Create the database file, WAL mode, schema and seed data. Idempotent."""
    global _db_path
    from . import repo  # local import: repo imports this module

    _db_path = str(path) if path is not None else default_db_path()
    Path(_db_path).parent.mkdir(parents=True, exist_ok=True)

    async with connect() as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.executescript(SCHEMA_PATH.read_text())
        await db.commit()

    await repo.seed_if_empty()

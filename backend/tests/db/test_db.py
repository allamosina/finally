import asyncio
import re
import sqlite3

import pytest

from app import db
from app.db import repo
from app.db.repo import InsufficientCash, InsufficientShares

DEFAULTS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


async def buy(t, q, p, tv=0.0):
    return await repo.execute_trade(t, "buy", q, p, tv)


async def sell(t, q, p, tv=0.0):
    return await repo.execute_trade(t, "sell", q, p, tv)


# ------------------------------------------------------------------ init / seed


async def test_init_creates_wal_schema_and_seed(database):
    con = sqlite3.connect(database)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users_profile", "watchlist", "positions", "trades",
            "portfolio_snapshots", "chat_messages"} <= tables
    for t in ("watchlist", "positions", "trades", "portfolio_snapshots", "chat_messages"):
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
        assert "user_id" in cols
    con.close()
    p = await repo.get_profile()
    assert p.id == "default" and p.cash_balance == 10000.0 and TS_RE.match(p.created_at)
    assert await repo.list_watchlist() == DEFAULTS


async def test_init_idempotent_keeps_data(database):
    await repo.remove_watchlist("AAPL")
    await buy("TSLA", 1, 100)
    await db.init_db(database)
    assert "AAPL" not in await repo.list_watchlist()
    assert (await repo.get_profile()).cash_balance == pytest.approx(9900)
    assert len(await repo.list_positions()) == 1


async def test_init_creates_missing_parent_dir(tmp_path):
    path = tmp_path / "nested" / "dir" / "x.db"
    await db.init_db(str(path))
    assert path.exists()
    assert await repo.list_watchlist() == DEFAULTS


async def test_emptied_watchlist_not_reseeded_on_restart(database):
    for t in DEFAULTS:
        await repo.remove_watchlist(t)
    await db.init_db(database)
    assert await repo.list_watchlist() == []


async def test_default_path_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "e.db"))
    assert db.default_db_path() == str(tmp_path / "e.db")
    monkeypatch.delenv("FINALLY_DB_PATH")
    assert db.default_db_path().endswith("db/finally.db")


async def test_connect_returns_usable_connection(database):
    async with db.connect() as con:
        cur = await con.execute("SELECT COUNT(*) FROM watchlist")
        assert (await cur.fetchone())[0] == 10


# --------------------------------------------------------------------- watchlist


async def test_watchlist_add_remove(database):
    assert await repo.add_watchlist("pypl") is True
    assert await repo.add_watchlist("PYPL") is False
    assert (await repo.list_watchlist())[-1] == "PYPL"
    assert await repo.remove_watchlist("pypl") is True
    assert await repo.remove_watchlist("PYPL") is False


async def test_priced_set_is_union(database):
    await buy("ZZZ", 1, 10)
    await repo.remove_watchlist("AAPL")
    s = await repo.priced_set()
    assert "ZZZ" in s and "MSFT" in s and "AAPL" not in s
    await buy("AAPL", 1, 10)  # held but not watched: still priced
    assert "AAPL" in await repo.priced_set()


# ------------------------------------------------------------------------ trades


async def test_buy_creates_position_and_updates_cash(database):
    t = await buy("aapl", 10, 190.0, 10000.0)
    assert (t.ticker, t.side, t.quantity, t.price) == ("AAPL", "buy", 10, 190.0)
    assert TS_RE.match(t.executed_at)
    pos = await repo.list_positions()
    assert len(pos) == 1 and pos[0].quantity == 10 and pos[0].avg_cost == 190.0
    assert (await repo.get_profile()).cash_balance == pytest.approx(8100.0)
    assert len(await repo.list_trades()) == 1
    snaps = await repo.list_snapshots()
    assert len(snaps) == 1 and snaps[0].total_value == 10000.0


async def test_weighted_average_cost(database):
    await buy("AAPL", 10, 100.0)
    await buy("AAPL", 30, 200.0)
    (p,) = await repo.list_positions()
    assert p.quantity == 40
    assert p.avg_cost == pytest.approx((10 * 100 + 30 * 200) / 40)  # 175


async def test_fractional_quantity(database):
    await buy("AAPL", 0.5, 100.0)
    await buy("AAPL", 0.25, 100.0)
    (p,) = await repo.list_positions()
    assert p.quantity == 0.75


async def test_partial_sell_keeps_avg_cost_and_credits_cash(database):
    await buy("AAPL", 10, 100.0)
    await sell("AAPL", 4, 150.0)
    (p,) = await repo.list_positions()
    assert p.quantity == 6 and p.avg_cost == 100.0
    assert (await repo.get_profile()).cash_balance == pytest.approx(10000 - 1000 + 600)


async def test_sell_below_avg_cost_reduces_cash_correctly(database):
    await buy("AAPL", 10, 100.0)
    await sell("AAPL", 10, 80.0)  # loss realised in cash
    assert (await repo.get_profile()).cash_balance == pytest.approx(9800.0)


async def test_full_sell_deletes_position(database):
    await buy("AAPL", 10, 100.0)
    await sell("AAPL", 10, 100.0)
    assert await repo.list_positions() == []
    assert (await repo.get_profile()).cash_balance == pytest.approx(10000.0)


async def test_rebuy_after_full_sell_resets_avg_cost(database):
    await buy("AAPL", 10, 100.0)
    await sell("AAPL", 10, 100.0)
    await buy("AAPL", 5, 300.0)
    (p,) = await repo.list_positions()
    assert p.quantity == 5 and p.avg_cost == 300.0


async def test_insufficient_cash_message_and_no_side_effects(database):
    await buy("MSFT", 1, 8500.0)  # cash now 1500
    before_trades = len(await repo.list_trades())
    before_snaps = len(await repo.list_snapshots())
    with pytest.raises(InsufficientCash) as ei:
        await buy("AAPL", 10, 190.12)
    assert str(ei.value) == "Insufficient cash: need $1,901.20, have $1,500.00"
    assert (await repo.get_profile()).cash_balance == pytest.approx(1500.0)
    assert [p.ticker for p in await repo.list_positions()] == ["MSFT"]
    assert len(await repo.list_trades()) == before_trades
    assert len(await repo.list_snapshots()) == before_snaps


async def test_insufficient_shares_message(database):
    await buy("AAPL", 5, 10.0)
    with pytest.raises(InsufficientShares) as ei:
        await sell("AAPL", 10, 10.0)
    assert str(ei.value) == "Insufficient shares: have 5, selling 10"


async def test_insufficient_shares_when_none_held(database):
    with pytest.raises(InsufficientShares) as ei:
        await sell("AAPL", 2.5, 10.0)
    assert str(ei.value) == "Insufficient shares: have 0, selling 2.5"


async def test_buy_exact_cash_allowed(database):
    await buy("AAPL", 100, 100.0)
    assert (await repo.get_profile()).cash_balance == pytest.approx(0.0)


async def test_buy_within_tolerance_allowed(database):
    # needs 10000.0000005, has 10000: within 1e-6
    await buy("AAPL", 1, 10000.0000005)


async def test_buy_beyond_tolerance_rejected(database):
    with pytest.raises(InsufficientCash):
        await buy("AAPL", 1, 10000.00001)


async def test_sell_within_tolerance_removes_row(database):
    await buy("AAPL", 1, 10.0)
    # Bypass the 4-decimal rounding to exercise tolerance on the stored remainder.
    con = sqlite3.connect(database)
    con.execute("UPDATE positions SET quantity = 1.0000004")
    con.commit()
    con.close()
    await sell("AAPL", 1, 10.0)  # held + 1e-6 >= 1; remainder 4e-7 <= tol
    assert await repo.list_positions() == []


async def test_sell_beyond_tolerance_rejected(database):
    await buy("AAPL", 1, 10.0)
    con = sqlite3.connect(database)
    con.execute("UPDATE positions SET quantity = 0.99999")
    con.commit()
    con.close()
    with pytest.raises(InsufficientShares):
        await sell("AAPL", 1, 10.0)


@pytest.mark.parametrize("q", [0, -1, float("nan"), float("inf")])
async def test_invalid_quantity_rejected(database, q):
    with pytest.raises(ValueError):
        await buy("AAPL", q, 10.0)


async def test_invalid_side_rejected(database):
    with pytest.raises(ValueError):
        await repo.execute_trade("AAPL", "hold", 1, 10.0, 0)


async def test_quantity_rounded_to_4_decimals(database):
    t = await buy("AAPL", 1.123456, 10.0)
    assert t.quantity == 1.1235
    assert (await repo.list_positions())[0].quantity == 1.1235


async def test_concurrent_buys_never_overspend(database):
    async def attempt():
        try:
            await buy("AAPL", 60, 100.0)  # 6000 each; only one fits
            return True
        except InsufficientCash:
            return False

    results = await asyncio.gather(*[attempt() for _ in range(5)])
    assert sum(results) == 1
    assert (await repo.get_profile()).cash_balance == pytest.approx(4000.0)
    assert (await repo.list_positions())[0].quantity == 60


# --------------------------------------------------------------------- snapshots


async def test_snapshots_order_limit_since(database):
    for v in (1.0, 2.0, 3.0, 4.0):
        await repo.record_snapshot(v)
        await asyncio.sleep(0.003)
    snaps = await repo.list_snapshots()
    assert [s.total_value for s in snaps] == [1.0, 2.0, 3.0, 4.0]
    assert all(TS_RE.match(s.recorded_at) for s in snaps)
    assert [s.total_value for s in await repo.list_snapshots(limit=2)] == [3.0, 4.0]
    since = snaps[2].recorded_at
    assert [s.total_value for s in await repo.list_snapshots(since=since)] == [3.0, 4.0]
    assert await repo.list_snapshots(since="2999-01-01T00:00:00.000Z") == []


# -------------------------------------------------------------------------- chat


async def test_chat_roundtrip_and_order(database):
    actions = {"trades": [{"ticker": "AAPL", "status": "failed", "error": "x"}],
               "watchlist_changes": []}
    m1 = await repo.add_chat("user", "hi", None)
    m2 = await repo.add_chat("assistant", "hello", actions)
    msgs = await repo.list_chat()
    assert [m.id for m in msgs] == [m1.id, m2.id]
    assert msgs[0].actions is None
    assert msgs[1].actions == actions and TS_RE.match(msgs[1].created_at)


async def test_chat_limit_returns_latest_oldest_first(database):
    for i in range(5):
        await repo.add_chat("user", f"m{i}", None)
    assert [m.content for m in await repo.list_chat(limit=3)] == ["m2", "m3", "m4"]


async def test_chat_invalid_role(database):
    with pytest.raises(ValueError):
        await repo.add_chat("system", "x", None)


# ------------------------------------------------------------------------- reset


async def test_reset_restores_seed(database):
    await buy("AAPL", 10, 100.0)
    await repo.add_watchlist("PYPL")
    await repo.remove_watchlist("MSFT")
    await repo.add_chat("user", "hi", None)
    await repo.record_snapshot(5.0)
    await repo.reset()
    assert await repo.list_positions() == []
    assert await repo.list_trades() == []
    assert await repo.list_snapshots() == []
    assert await repo.list_chat() == []
    assert (await repo.get_profile()).cash_balance == 10000.0
    assert await repo.list_watchlist() == DEFAULTS


async def test_reset_twice_is_stable(database):
    await repo.reset()
    await repo.reset()
    assert await repo.list_watchlist() == DEFAULTS


# ------------------------------------------------------------------ user scoping


async def test_user_id_scoping(database):
    con = sqlite3.connect(database)
    con.execute("INSERT INTO users_profile VALUES ('bob', 500, '2026-01-01T00:00:00.000Z')")
    con.commit()
    con.close()
    await repo.add_watchlist("ZZZ", user_id="bob")
    assert await repo.list_watchlist(user_id="bob") == ["ZZZ"]
    assert "ZZZ" not in await repo.list_watchlist()
    await repo.execute_trade("ZZZ", "buy", 1, 100, 500, user_id="bob")
    assert (await repo.get_profile("bob")).cash_balance == 400
    assert (await repo.get_profile()).cash_balance == 10000
    assert await repo.list_positions() == []


def test_db_layer_does_not_import_market():
    src = open(repo.__file__).read() + open(db.__file__).read()
    assert "app.market" not in src and "from ..market" not in src

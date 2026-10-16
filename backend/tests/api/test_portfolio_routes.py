from __future__ import annotations

import pytest

from app.db import repo
from app.services import market

DEFAULT_WATCHLIST = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


async def _buy(client, ticker="AAPL", qty=5, side="buy"):
    return await client.post("/api/portfolio/trade", json={"ticker": ticker, "quantity": qty, "side": side})


async def test_fresh_portfolio(client):
    r = await client.get("/api/portfolio")
    assert r.status_code == 200
    assert r.json() == {"cash_balance": 10000.0, "total_value": 10000.0, "unrealized_pnl": 0.0, "positions": []}


async def test_buy_returns_trade_and_portfolio(client):
    r = await _buy(client, "aapl", 5)
    assert r.status_code == 200
    body = r.json()
    t = body["trade"]
    assert set(t) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert t["ticker"] == "AAPL" and t["side"] == "buy" and t["quantity"] == 5
    assert t["executed_at"].endswith("Z")
    pf = body["portfolio"]
    assert pf["cash_balance"] == pytest.approx(10000 - 5 * t["price"], abs=1e-3)
    [pos] = pf["positions"]
    assert set(pos) == {"ticker", "quantity", "avg_cost", "current_price", "market_value", "unrealized_pnl", "pnl_pct"}
    assert pos["ticker"] == "AAPL" and pos["quantity"] == 5
    assert pos["avg_cost"] == pytest.approx(t["price"], abs=1e-4)
    assert pf["total_value"] == pytest.approx(pf["cash_balance"] + pos["market_value"], abs=1e-3)
    assert (await client.get("/api/portfolio")).json()["positions"][0]["ticker"] == "AAPL"


async def test_fractional_quantity_rounded_to_4dp(client):
    r = await _buy(client, "AAPL", 0.123456)
    assert r.status_code == 200
    assert r.json()["trade"]["quantity"] == 0.1235


async def test_sell_all_removes_position(client):
    await _buy(client, "AAPL", 5)
    r = await _buy(client, "AAPL", 5, "sell")
    assert r.status_code == 200
    assert r.json()["portfolio"]["positions"] == []


async def test_sell_more_than_held_is_400(client):
    await _buy(client, "AAPL", 5)
    r = await _buy(client, "AAPL", 10, "sell")
    assert r.status_code == 400
    assert r.json() == {"detail": "Insufficient shares: have 5, selling 10"}


async def test_insufficient_cash_is_400(client):
    r = await _buy(client, "NVDA", 1000)
    assert r.status_code == 400
    assert r.json()["detail"].startswith("Insufficient cash: need $")
    assert r.json()["detail"].endswith("have $10,000.00")


@pytest.mark.parametrize(
    "payload",
    [
        {"ticker": "TOOLONG", "quantity": 1, "side": "buy"},
        {"ticker": "A1", "quantity": 1, "side": "buy"},
        {"ticker": "AAPL", "quantity": 0, "side": "buy"},
        {"ticker": "AAPL", "quantity": -2, "side": "buy"},
        {"ticker": "AAPL", "quantity": 1, "side": "hold"},
        {"ticker": "AAPL", "quantity": "lots", "side": "buy"},
        {"ticker": "AAPL", "side": "buy"},
    ],
)
async def test_malformed_trade_is_422(client, payload):
    r = await client.post("/api/portfolio/trade", json=payload)
    assert r.status_code == 422
    assert "detail" in r.json()


async def test_buy_unwatched_ticker_keeps_it_priced(client):
    assert "PYPL" not in market.source().health()["tickers"]
    r = await _buy(client, "PYPL", 1)
    assert r.status_code == 200
    assert "PYPL" in market.source().health()["tickers"]
    assert "PYPL" not in await repo.list_watchlist()


async def test_failed_buy_of_unwatched_ticker_ages_out(client):
    r = await _buy(client, "COIN", 10_000)
    assert r.status_code == 400
    assert market.cache().get("COIN") is None


async def test_price_unavailable_is_503(client, env):
    async def no_price(tickers, timeout=5.0):
        return {}

    env.setattr(market.source(), "prime", no_price)
    r = await _buy(client, "AAPL", 1)
    assert r.status_code == 503
    assert r.json() == {"detail": "Price unavailable for AAPL"}


async def test_trade_records_snapshot(client):
    before = len((await client.get("/api/portfolio/history")).json())
    await _buy(client, "AAPL", 1)
    rows = (await client.get("/api/portfolio/history")).json()
    assert len(rows) == before + 1
    assert set(rows[-1]) == {"recorded_at", "total_value"}
    assert rows[-1]["total_value"] == pytest.approx(10000.0, abs=1e-3)  # a fill at market keeps total value


async def test_history_startup_snapshot_limit_and_since(client):
    rows = (await client.get("/api/portfolio/history")).json()
    assert len(rows) == 1 and rows[0]["total_value"] == 10000.0  # recorded at startup
    for _ in range(3):
        await _buy(client, "AAPL", 1)
    assert len((await client.get("/api/portfolio/history?limit=2")).json()) == 2
    all_rows = (await client.get("/api/portfolio/history")).json()
    assert [r["recorded_at"] for r in all_rows] == sorted(r["recorded_at"] for r in all_rows)
    since = all_rows[2]["recorded_at"]
    assert len((await client.get("/api/portfolio/history", params={"since": since})).json()) == 2
    # second-precision 'since' with +00:00 offset still compares correctly
    sec = since[:19] + "+00:00"
    assert len((await client.get("/api/portfolio/history", params={"since": sec})).json()) >= 2


@pytest.mark.parametrize("query", ["?limit=0", "?limit=abc", "?since=yesterday"])
async def test_history_bad_query_is_422(client, query):
    assert (await client.get(f"/api/portfolio/history{query}")).status_code == 422


async def test_reset_restores_seed_state(client):
    await _buy(client, "PYPL", 2)
    await client.post("/api/watchlist", json={"ticker": "COIN"})
    await client.delete("/api/watchlist/AAPL")
    await repo.add_chat("user", "hi")
    r = await client.post("/api/reset")
    assert r.status_code == 200
    assert r.json()["portfolio"] == {"cash_balance": 10000.0, "total_value": 10000.0, "unrealized_pnl": 0.0, "positions": []}
    assert [w["ticker"] for w in (await client.get("/api/watchlist")).json()] == DEFAULT_WATCHLIST
    assert set(market.source().health()["tickers"]) == set(DEFAULT_WATCHLIST)
    assert market.cache().tickers() == set(DEFAULT_WATCHLIST)
    assert len((await client.get("/api/portfolio/history")).json()) == 1
    assert (await client.get("/api/chat/history")).json() == []


async def test_snapshot_task_records_periodically(env, static_dir):
    import asyncio

    import httpx

    from app.main import create_app

    env.setenv("SNAPSHOT_INTERVAL_S", "0.05")
    app = create_app(static_dir=static_dir)
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.3)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            assert len((await c.get("/api/portfolio/history")).json()) >= 3

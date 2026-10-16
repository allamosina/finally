from __future__ import annotations

from app.services import market


async def test_get_watchlist_has_live_prices(client):
    r = await client.get("/api/watchlist")
    assert r.status_code == 200
    rows = r.json()
    assert [w["ticker"] for w in rows][:3] == ["AAPL", "GOOGL", "MSFT"] and len(rows) == 10
    for w in rows:
        assert set(w) == {"ticker", "price", "prev_price", "session_open", "change_pct", "direction"}
        assert w["price"] > 0


async def test_add_then_duplicate(client):
    r = await client.post("/api/watchlist", json={"ticker": "pypl"})
    assert r.status_code == 201
    assert r.json()["ticker"] == "PYPL" and r.json()["price"] > 0
    assert "PYPL" in market.source().health()["tickers"]
    r2 = await client.post("/api/watchlist", json={"ticker": "PYPL"})
    assert r2.status_code == 200
    assert [w["ticker"] for w in (await client.get("/api/watchlist")).json()].count("PYPL") == 1


async def test_add_invalid_ticker_is_422(client):
    for bad in ("TOOLONG", "12", ""):
        r = await client.post("/api/watchlist", json={"ticker": bad})
        assert r.status_code == 422, bad
    assert (await client.post("/api/watchlist", json={})).status_code == 422


async def test_remove_then_404(client):
    r = await client.delete("/api/watchlist/NFLX")
    assert r.status_code == 200 and r.json() == {"ticker": "NFLX", "removed": True}
    assert "NFLX" not in market.cache().tickers()
    r2 = await client.delete("/api/watchlist/NFLX")
    assert r2.status_code == 404 and "detail" in r2.json()
    assert (await client.delete("/api/watchlist/BAD1")).status_code == 422


async def test_removed_but_held_ticker_keeps_streaming(client):
    await client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "buy"})
    assert (await client.delete("/api/watchlist/AAPL")).status_code == 200
    assert "AAPL" in market.cache().tickers()
    assert "AAPL" not in [w["ticker"] for w in (await client.get("/api/watchlist")).json()]

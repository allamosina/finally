from __future__ import annotations

from app import db

DEFAULT_WATCHLIST = {"AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"}


async def test_health_shape(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["market_data"] == "simulator"
    assert body["llm"] == "mock"
    assert body["db"] == "ok"
    assert set(body["market"]["tickers"]) == DEFAULT_WATCHLIST
    assert body["market"]["name"] == "simulator"


async def test_health_llm_unconfigured(client, env):
    env.setenv("LLM_MOCK", "false")
    env.delenv("OPENROUTER_API_KEY", raising=False)
    assert (await client.get("/api/health")).json()["llm"] == "unconfigured"


async def test_health_llm_live(client, env):
    env.setenv("LLM_MOCK", "false")
    env.setenv("OPENROUTER_API_KEY", "sk-test")
    assert (await client.get("/api/health")).json()["llm"] == "live"


async def test_health_reports_db_error(client, env):
    def broken():
        raise RuntimeError("disk gone")

    env.setattr(db, "connect", broken)
    r = await client.get("/api/health")
    assert r.status_code == 503
    assert r.json()["status"] == "error"
    assert r.json()["db"] == "error"


async def test_startup_prices_watchlist(app):
    from app.services import market

    assert DEFAULT_WATCHLIST <= market.cache().tickers()

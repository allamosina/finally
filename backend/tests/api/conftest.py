"""Fixtures for route tests: a fresh app per test with its own SQLite file, a fast
seeded simulator, a tiny static frontend, and an httpx client over ASGITransport."""

from __future__ import annotations

import os

os.environ.setdefault("FINALLY_SKIP_DOTENV", "1")  # never load the developer's .env in tests
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # no network fetch on litellm import

import httpx
import pytest
import pytest_asyncio

from app.main import create_app


@pytest.fixture
def static_dir(tmp_path):
    root = tmp_path / "static"
    (root / "_next").mkdir(parents=True)
    (root / "index.html").write_text("<html>INDEX</html>")
    (root / "about.html").write_text("<html>ABOUT</html>")
    (root / "_next" / "app.js").write_text("console.log('js')")
    (tmp_path / "secret.txt").write_text("SECRET")
    return root


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "db" / "finally.db"))
    monkeypatch.setenv("SIM_TICK_MS", "20")
    monkeypatch.setenv("SIM_SEED", "7")
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("SNAPSHOT_INTERVAL_S", "3600")  # one snapshot at startup, then quiet
    return monkeypatch


@pytest_asyncio.fixture
async def app(env, static_dir):
    application = create_app(static_dir=static_dir)
    application.state.sse_ping_interval = 0.2
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

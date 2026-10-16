"""Serve the real Next.js export through the backend (TEAM.md §2.5, PLAN §11).
Skipped when frontend/out has not been built."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from app.main import create_app

OUT = Path(__file__).resolve().parents[3] / "frontend" / "out"
pytestmark = pytest.mark.skipif(not (OUT / "index.html").is_file(), reason="frontend/out not built")


@pytest_asyncio.fixture
async def export_client(env):
    app = create_app(static_dir=OUT)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield c


async def test_index_and_spa_fallback(export_client):
    index = (OUT / "index.html").read_text()
    for path in ("/", "/some/unknown/path"):
        r = await export_client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("text/html")
        assert r.text == index


async def test_next_assets_serve_with_content_type(export_client):
    index = (await export_client.get("/")).text
    assets = sorted(set(re.findall(r'(?:src|href)="(/_next/[^"]+)"', index)))
    assert any(a.endswith(".js") for a in assets) and any(a.endswith(".css") for a in assets)
    for a in assets:
        r = await export_client.get(a)
        assert r.status_code == 200, a
        ct = r.headers["content-type"]
        if a.endswith(".js"):
            assert "javascript" in ct, (a, ct)
        elif a.endswith(".css"):
            assert ct.startswith("text/css"), (a, ct)


async def test_api_still_wins_over_spa(export_client):
    assert (await export_client.get("/api/health")).headers["content-type"] == "application/json"
    r = await export_client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}

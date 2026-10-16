from __future__ import annotations

import asyncio
import json
import re

ISO_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


async def test_history_known_ticker(client):
    await asyncio.sleep(0.1)  # let the 20 ms simulator tick a few times
    r = await client.get("/api/prices/AAPL/history")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 2
    assert all(set(row) == {"ts", "price"} for row in rows)
    assert all(ISO_Z.match(row["ts"]) for row in rows)
    assert [row["ts"] for row in rows] == sorted(row["ts"] for row in rows)  # oldest first
    assert all(row["price"] > 0 for row in rows)


async def test_history_lowercase_is_normalized(client):
    r = await client.get("/api/prices/aapl/history")
    assert r.status_code == 200
    assert r.json()


async def test_history_unpriced_ticker_is_empty(client):
    r = await client.get("/api/prices/ZZZZ/history")
    assert r.status_code == 200
    assert r.json() == []


async def test_history_invalid_ticker_is_422(client):
    for bad in ("TOOLONG", "A1", "BRK.B"):
        r = await client.get(f"/api/prices/{bad}/history")
        assert r.status_code == 422, bad
        assert "detail" in r.json()


async def _read_sse(app, path: str = "/api/stream/prices", want_events: int = 1, timeout: float = 3.0):
    """Drive the ASGI app directly: collect the response start and body chunks until
    `want_events` prices events arrived, then disconnect. httpx's ASGITransport buffers
    the whole body, which never ends for SSE."""
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [(b"host", b"test")], "client": ("test", 1), "server": ("test", 80),
    }
    disconnect = asyncio.Event()
    start: dict = {}
    body = ""

    async def receive():
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        nonlocal body
        if message["type"] == "http.response.start":
            start.update(message)
        elif message["type"] == "http.response.body":
            body += message.get("body", b"").decode()
            if body.count("event: prices") >= want_events:
                disconnect.set()

    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(disconnect.wait(), timeout)
    finally:
        disconnect.set()
        try:
            await asyncio.wait_for(task, 1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
    return start, body


async def test_sse_route_headers_and_first_event(app):
    start, body = await _read_sse(app, want_events=2)
    assert start["status"] == 200
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-cache"
    assert body.startswith("retry: 2000\n\n")
    events = [chunk for chunk in body.split("\n\n") if chunk.startswith("event: prices")]
    first = json.loads(events[0].split("data: ", 1)[1])
    assert ISO_Z.match(first["ts"])
    assert len(first["prices"]) == 10  # full snapshot of the default watchlist
    row = first["prices"][0]
    assert set(row) == {"ticker", "price", "prev_price", "session_open", "change_pct", "direction"}
    assert row["direction"] in {"up", "down", "flat"}

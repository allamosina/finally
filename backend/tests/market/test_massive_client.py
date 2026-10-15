import asyncio

import httpx

from app.market import MarketDataSource, MassiveClient, PriceCache
from app.market.massive_client import parse_snapshot

PAYLOAD = {
    "status": "OK",
    "tickers": [
        {"ticker": "AAPL", "lastTrade": {"p": 191.5, "t": 1_700_000_000_000_000_000}},
        {"ticker": "MSFT", "lastTrade": {}, "min": {"c": 420.25}},
        {"ticker": "TSLA", "day": {"c": 250.0}},
        {"ticker": "BAD", "lastTrade": {"p": 0}},
        {"lastTrade": {"p": 1.0}},
    ],
}


def test_implements_interface():
    assert issubclass(MassiveClient, MarketDataSource)


def test_parse_snapshot_fallbacks_and_skips():
    out = parse_snapshot(PAYLOAD)
    assert out["AAPL"] == (191.5, 1_700_000_000.0)
    assert out["MSFT"] == (420.25, None)
    assert out["TSLA"] == (250.0, None)
    assert set(out) == {"AAPL", "MSFT", "TSLA"}


def test_parse_snapshot_empty():
    assert parse_snapshot({}) == {}
    assert parse_snapshot({"tickers": None}) == {}


def make_client(handler, **kw):
    cache = PriceCache()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.test")
    return cache, MassiveClient(cache, api_key="KEY", client=http, **kw)


async def test_poll_once_sends_request_and_updates_cache():
    seen = {}

    def handler(request: httpx.Request):
        seen["params"] = dict(request.url.params)
        seen["path"] = request.url.path
        return httpx.Response(200, json=PAYLOAD)

    cache, client = make_client(handler)
    await client.start([])
    await client.add_ticker("aapl")
    await client.add_ticker("MSFT")
    n = await client.poll_once()
    await client.stop()
    assert n == 2
    assert seen["params"]["tickers"] == "AAPL,MSFT"
    assert seen["params"]["apiKey"] == "KEY"
    assert seen["path"].endswith("/tickers")
    assert cache.get_price("AAPL") == 191.5
    assert cache.get_price("MSFT") == 420.25
    assert "TSLA" not in cache  # not tracked


async def test_poll_without_tickers_makes_no_request():
    def handler(request):
        raise AssertionError("should not be called")

    _, client = make_client(handler)
    assert await client.poll_once() == 0
    await client.stop()


async def test_http_error_raises_from_poll_once_but_loop_survives():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429)
        return httpx.Response(200, json=PAYLOAD)

    cache, client = make_client(handler, poll_interval=0.01)
    await client.start(["AAPL"])
    await asyncio.sleep(0.15)
    await client.stop()
    assert calls >= 2
    assert cache.get_price("AAPL") == 191.5


async def test_remove_ticker_clears_cache():
    cache, client = make_client(lambda r: httpx.Response(200, json=PAYLOAD))
    await client.add_ticker("AAPL")
    await client.poll_once()
    await client.remove_ticker("aapl")
    assert client.get_tickers() == [] and "AAPL" not in cache
    await client.stop()

import json

from app.market import MarketSimulator, MassiveClient, PriceCache, create_market_source
from app.market.stream import price_events


async def test_factory_defaults_to_simulator():
    for env in ({}, {"MASSIVE_API_KEY": ""}, {"MASSIVE_API_KEY": "   "}):
        assert isinstance(create_market_source(PriceCache(), env), MarketSimulator)


async def test_factory_uses_massive_when_key_set():
    src = create_market_source(PriceCache(), {"MASSIVE_API_KEY": "k", "MASSIVE_POLL_INTERVAL": "5"})
    assert isinstance(src, MassiveClient)
    assert src.poll_interval == 5.0
    await src.stop()


async def test_price_events_emit_retry_then_one_frame_per_ticker():
    cache = PriceCache()
    cache.update("AAPL", 100)
    cache.update("MSFT", 200)
    gen = price_events(cache, interval=0.01)
    assert await anext(gen) == "retry: 1000\n\n"
    frames = [await anext(gen), await anext(gen)]
    await gen.aclose()
    payloads = [json.loads(f.removeprefix("data: ")) for f in frames]
    assert {p["ticker"] for p in payloads} == {"AAPL", "MSFT"}
    assert all(f.endswith("\n\n") for f in frames)
    assert {"price", "previous_price", "timestamp", "direction"} <= set(payloads[0])


async def test_price_events_only_resend_on_change_and_stop_on_disconnect():
    cache = PriceCache()
    cache.update("AAPL", 100)
    state = {"calls": 0}

    async def disconnected():
        state["calls"] += 1
        if state["calls"] == 3:
            cache.update("AAPL", 101)
        return state["calls"] > 4

    out = [f async for f in price_events(cache, disconnected, interval=0.001)]
    data = [json.loads(f.removeprefix("data: ")) for f in out if f.startswith("data:")]
    assert [d["price"] for d in data] == [100, 101]
    assert data[1]["direction"] == "up"

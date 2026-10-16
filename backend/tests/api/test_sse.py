"""The SSE generator in isolation, against a bare PriceCache (no source, no app)."""

from __future__ import annotations

import asyncio
import json

from app.market import PriceCache
from app.sse import event_stream, iso_z, to_sse_payload


def _data(event: str) -> dict:
    assert event.startswith("event: prices\ndata: ") and event.endswith("\n\n")
    return json.loads(event.split("data: ", 1)[1])


async def test_iso_z():
    assert iso_z(0) == "1970-01-01T00:00:00.000Z"
    assert iso_z(1_792_324_800_500) == "2026-10-18T12:00:00.500Z"


async def test_retry_then_snapshot_then_one_event_per_apply():
    cache = PriceCache()
    await cache.apply({"AAPL": (190.0, 1, "simulator"), "MSFT": (415.0, 1, "simulator")})
    gen = event_stream(cache, ping_interval=5)
    assert await anext(gen) == "retry: 2000\n\n"
    first = _data(await anext(gen))  # full snapshot immediately on connect
    assert [p["ticker"] for p in first["prices"]] == ["AAPL", "MSFT"]

    nxt = asyncio.create_task(anext(gen))
    await asyncio.sleep(0)
    await cache.apply({"AAPL": (191.0, 2, "simulator"), "MSFT": (414.0, 2, "simulator")})
    ev = _data(await asyncio.wait_for(nxt, 1))
    by = {p["ticker"]: p for p in ev["prices"]}
    assert by["AAPL"] == {
        "ticker": "AAPL", "price": 191.0, "prev_price": 190.0, "session_open": 190.0,
        "change_pct": round((191 / 190 - 1) * 100, 4), "direction": "up",
    }
    assert by["MSFT"]["direction"] == "down"
    await gen.aclose()


async def test_empty_cache_sends_empty_events_and_pings():
    cache = PriceCache()
    gen = event_stream(cache, ping_interval=0.25, empty_heartbeat=0.05)
    assert await anext(gen) == "retry: 2000\n\n"
    assert _data(await anext(gen))["prices"] == []  # snapshot on connect, even when empty
    seen = [await asyncio.wait_for(anext(gen), 1) for _ in range(8)]
    empties = [e for e in seen if e.startswith("event: prices")]
    assert empties and all(_data(e)["prices"] == [] for e in empties)
    assert ": ping\n\n" in seen
    await gen.aclose()


async def test_non_empty_cache_is_not_resent_without_change():
    cache = PriceCache()
    await cache.apply({"AAPL": (190.0, 1, "simulator")})
    gen = event_stream(cache, ping_interval=0.1, empty_heartbeat=0.01)
    await anext(gen), await anext(gen)
    assert await asyncio.wait_for(anext(gen), 1) == ": ping\n\n"  # no repeated snapshot
    await gen.aclose()


async def test_drop_emits_event_without_the_ticker():
    cache = PriceCache()
    await cache.apply({"AAPL": (190.0, 1, "simulator"), "MSFT": (415.0, 1, "simulator")})
    gen = event_stream(cache, ping_interval=5)
    await anext(gen), await anext(gen)
    nxt = asyncio.create_task(anext(gen))
    await asyncio.sleep(0)
    await cache.drop("MSFT")
    ev = _data(await asyncio.wait_for(nxt, 1))
    assert [p["ticker"] for p in ev["prices"]] == ["AAPL"]
    await gen.aclose()


async def test_payload_flat_direction_and_zero_change():
    cache = PriceCache()
    await cache.apply({"V": (275.0, 1, "simulator")})
    p = to_sse_payload(cache.snapshot())["prices"][0]
    assert p["direction"] == "flat" and p["change_pct"] == 0.0

# Review: market data backend (issue #2)

Scope: `backend/app/market/*` and `backend/tests/market/*`, added in one commit on `claude/issue-2-20261015-1109`.

Method: read-through only. The sandbox denied `uv`, `pytest` and `python3 -m pytest`, so the code and tests have **not been executed**. Treat everything below as unverified until `cd backend && uv sync && uv run pytest` passes.

## Checked by reading

- Simulator correlation weights: market 0.3 and sector at most 0.6 give a combined squared weight of 0.45, so the idiosyncratic term is real and each shock keeps unit variance.
- GBM step follows `S * exp((mu - sigma^2/2) dt + sigma sqrt(dt) z)`. `dt` is derived from the tick interval over trading seconds per year.
- `PriceCache` uppercases tickers and rounds prices to 2 dp. A first update has `previous_price == price`, so the direction is `flat`.
- The SSE generator re-emits all tickers only when `cache.version` changes. I traced the disconnect test by hand and it should yield prices 100 then 101.
- All three tasks (simulator, Massive, plus the factory) share the `MarketDataSource` interface.

## Issues and limitations

1. **Not run.** See above. This is the main gap.
2. **Massive endpoint unverified.** The snapshot path and field names (`lastTrade.p`/`t` in nanoseconds, `min.c`, `day.c`) come from memory of the Polygon API, not from a live response or docs.
3. **Newly added Massive tickers have no price until the next poll**, up to 15s on the free tier. The watchlist API will need to handle a missing cache entry.
4. **`MassiveClient.stop()` closes its `httpx.AsyncClient`**, so an instance cannot be restarted after stopping.
5. **Poll failures are only logged as a warning with the exception type.** There is no backoff, and no distinct handling of 429 rate limiting.
6. **The simulator accepts any ticker string** and invents a random price profile for unknown ones. Ticker validation belongs in the watchlist layer.
7. **No lifecycle wiring.** Nothing starts the source from a FastAPI lifespan, and the cache and source are not seeded from the DB watchlist. This was out of scope for the issue but is needed before the SSE route works end to end.
8. **Timing-based tests** (`asyncio.sleep` windows in the simulator and Massive loop tests) could be flaky on a slow CI runner.
9. `MASSIVE_POLL_INTERVAL` is an extra env var not in PLAN.md section 5. It should be documented there if kept.

## Verdict

Structure and logic look consistent with PLAN.md section 6. Merge only after the test suite has actually been run.

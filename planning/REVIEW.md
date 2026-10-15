# Change Review Log

Reviews of changes made in each agent session, appended chronologically.

---

## 2026-10-15 — Review of `planning/MARKET_DATA_DESIGN.md` (new document)

**Scope.** One new file, `planning/MARKET_DATA_DESIGN.md`, committed as
`05bf52f`. No code was added to the repository; the document contains the
reference implementation for `backend/app/market_data/` as fenced snippets.
All 26 Python snippets were parsed with `ast.parse` and are syntactically
valid. The review below reads them as if they were the real modules.

### Defects found and fixed in this review

1. **SSE unit test could never finish.** `test_sse.py` streamed the endpoint
   through `httpx.ASGITransport`, which buffers the entire response body before
   returning. Against an endless event generator the test would hang forever.
   *Fixed:* the test now drives `price_events()` directly with a stub request
   that reports "disconnected" after N checks, adds a `format_sse` unit test and
   a keep-alive test, and notes that header/transport coverage belongs to the
   Playwright scenario.

2. **Provider failures during an on-demand fetch surfaced as HTTP 500.** The
   watchlist and trade handlers only caught `UnknownTickerError`. A 429, a 5xx,
   or a network error raised from `track()` / `ensure_price()` (the only path
   where a request handler calls the provider) would have escaped as an
   unhandled exception. *Fixed:* both handlers catch `MarketDataError` and map
   it to HTTP 503 with a retry hint; §5.1's error-mapping prose now matches.

3. **Circular import.** `watchlist/routes.py` imported `get_market` from
   `app.main`, while `main.py` imports the routers. *Fixed:* the dependency
   moved to a new `market_data/deps.py`; `sse.py`, `main.py`, and the watchlist
   snippet all import it from there.

### Findings left as-is (minor, noted for the implementer)

- `SimulatedMarketDataSource.validate()` creates simulation state for any
  well-formed ticker, even one that is never tracked. Repeated validation of
  junk symbols grows `_state` by a few hundred bytes each. Bounded by the
  ticker regex and harmless in practice; an LRU or a `validate()` that does not
  call `_ensure()` would close it.
- The service tests `test_start_primes_cache_and_loop_advances` and
  `test_loop_survives_source_errors` use real `asyncio.sleep` of 1.2 s and
  2.5 s against the default 0.5 s tick. They pass but slow the suite; the
  `sim_service` fixture should construct the source with
  `tick_interval=0.05` and the sleeps shrink accordingly.
- `MassiveMarketDataSource.fetch()` treats a `"DELAYED"` status as OK. That
  value is what Polygon returned for delayed-tier plans; it has not been
  re-verified against Massive's current docs because massive.com is blocked
  by this environment's network policy. The parser does not depend on it
  (unknown statuses only log a warning), so the risk is a spurious warning,
  not a failure.
- `PriceCache.update()` leaves `prev_close` untouched when the price is
  unchanged. With Massive, `prevDay.c` rolls over once a day at 03:30 ET and
  the price nearly always moves soon after, so this is cosmetic.
- `config.PROJECT_ROOT = Path(__file__).resolve().parents[2]` assumes the
  layout `<root>/backend/app/config.py`. The Dockerfile copies `backend/` to
  an as-yet-undecided path; `load_dotenv` is a no-op there anyway because the
  container receives variables via `--env-file`. Worth a comment in the real
  file, nothing more.

### Opportunities to simplify

- `SourceUnavailableError` and the bare `Exception` branch in `_run()` are
  handled identically. The class still earns its place as a documented
  contract for `fetch()`, but the implementer could collapse the two
  `except` arms into one.
- `SSE_KEEPALIVE_INTERVAL` and `SSE_PUSH_INTERVAL` are unlikely to ever be
  tuned outside tests. They could become constructor arguments of the SSE
  generator with the env plumbing dropped, which removes two settings fields.

### Verdict

The document is consistent with `PLAN.md` §5, §6 and §8 (env-var driven
source selection, GBM simulator at ~500 ms with correlation and events,
Massive REST polling at a tier-appropriate interval, single shared cache,
SSE at ~500 ms with ticker / price / previous price / timestamp / direction).
With the three fixes above applied in the same session, it is ready for the
Backend and Market Data agents to implement from.

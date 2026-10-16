# Market Data Interface

The unified Python API through which FinAlly obtains stock prices. One abstract interface, two implementations: the Massive REST client when `MASSIVE_API_KEY` is set and non-empty, otherwise the built-in simulator. Nothing downstream (price cache, SSE stream, REST routes, trade execution, frontend) may know which one is active.

Companion documents: [MASSIVE_API.md](MASSIVE_API.md) (the external API), [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md) (the simulator internals). This document is the contract between them and the rest of the backend.

---

## 1. Goals and non-goals

Goals:

- A single call site in `main.py` builds the source; everything else talks to the **price cache**, never to the source.
- Both sources produce identical cache state, so the SSE payload, history endpoint, trade pricing and `/api/health` are source-agnostic.
- Sources can be started, stopped and told which tickers to price. The priced set is `watchlist ∪ positions` and changes at runtime.
- Any syntactically valid ticker can be priced on demand so a buy of an unwatched symbol has a defined price path (closes review finding C-1 / P1).
- The whole thing is testable without network: a conformance test suite runs against both implementations.

Non-goals (core build): WebSocket streaming, order books, multi-process sharing of the cache, historical bars beyond the in-memory ring buffer.

---

## 2. Module layout

```
backend/app/market/
├── __init__.py          # build_source(), get_cache(); the only import the rest of the app needs
├── types.py             # Quote, Tick, PriceSnapshot dataclasses
├── cache.py             # PriceCache (in-memory, ring buffers, change notification)
├── base.py              # MarketDataSource ABC + shared polling-loop helper
├── simulator.py         # SimulatorSource (see MARKET_SIMULATOR.md)
├── massive_client.py    # thin httpx wrapper over the two Massive endpoints we use
├── massive_source.py    # MassiveSource: poll loop, mode detection, backoff
└── config.py            # MarketConfig parsed from env
```

Everything under `backend/app/market/` is importable without touching the database or FastAPI.

---

## 3. Data types (`types.py`)

```python
from dataclasses import dataclass, field
from collections import deque


@dataclass(frozen=True)
class Tick:
    """One observed price for one ticker."""
    ts_ms: int           # Unix milliseconds, UTC
    price: float


@dataclass
class Quote:
    """Everything the cache knows about one ticker. Mutable; owned by PriceCache."""
    ticker: str
    price: float
    prev_price: float            # previous tick's price (for direction/flash)
    session_open: float          # reference for change_pct (seed at start | previous close)
    ts_ms: int                   # when `price` was observed
    source: str                  # "simulator" | "last_trade" | "last_minute" | "session_close" | "eod_close"
    history: deque[Tick] = field(default_factory=lambda: deque(maxlen=600))

    @property
    def direction(self) -> str:
        if self.price > self.prev_price: return "up"
        if self.price < self.prev_price: return "down"
        return "flat"

    @property
    def change_pct(self) -> float:
        return 0.0 if not self.session_open else (self.price / self.session_open - 1.0) * 100.0


@dataclass(frozen=True)
class PriceSnapshot:
    """What one SSE event carries: all priced tickers at one instant."""
    ts_ms: int
    quotes: tuple[Quote, ...]
```

Rules:

- `session_open` is set **once** when a ticker first enters the cache and never changes for the process lifetime. The simulator uses its seed price; Massive uses the previous close when available, else the first observed price. Restarts reset it; PLAN §6 accepts this.
- `history` holds the last 600 ticks (~5 min at 500 ms, or ~5 days at 15-min EOD polling; the count is what matters for chart seeding, not the duration).
- All timestamps are integer Unix milliseconds internally and are formatted to ISO-8601 `Z` strings only at the API boundary.

---

## 4. Price cache (`cache.py`)

The cache is the single rendezvous point. Sources write; everyone else reads.

```python
import asyncio
import time


class PriceCache:
    def __init__(self, history_len: int = 600):
        self._quotes: dict[str, Quote] = {}
        self._history_len = history_len
        self._version = 0
        self._changed = asyncio.Condition()

    # ---- write side (sources only) ---------------------------------------
    async def apply(self, ticks: dict[str, tuple[float, int, str]], session_open: dict[str, float] | None = None) -> None:
        """Atomically apply one batch: {ticker: (price, ts_ms, source)}. Wakes SSE waiters once."""
        async with self._changed:
            for ticker, (price, ts_ms, source) in ticks.items():
                q = self._quotes.get(ticker)
                if q is None:
                    so = (session_open or {}).get(ticker, price)
                    q = Quote(ticker, price, price, so, ts_ms, source, deque(maxlen=self._history_len))
                    self._quotes[ticker] = q
                else:
                    q.prev_price, q.price, q.ts_ms, q.source = q.price, price, ts_ms, source
                q.history.append(Tick(ts_ms, price))
            self._version += 1
            self._changed.notify_all()

    async def drop(self, *tickers: str) -> None:
        """Remove tickers; bump the version and wake SSE waiters once if anything was removed."""
        async with self._changed:
            removed = [t for t in tickers if self._quotes.pop(t, None) is not None]
            if removed:
                self._version += 1
                self._changed.notify_all()

    # ---- read side -------------------------------------------------------
    def get(self, ticker: str) -> Quote | None:
        return self._quotes.get(ticker)

    def snapshot(self) -> PriceSnapshot:
        return PriceSnapshot(int(time.time() * 1000), tuple(self._quotes.values()))

    def history(self, ticker: str) -> list[Tick]:
        q = self._quotes.get(ticker)
        return list(q.history) if q else []

    def tickers(self) -> set[str]:
        return set(self._quotes)

    async def wait_for_change(self, last_seen: int) -> int:
        """Block until version > last_seen. SSE handlers use this instead of polling."""
        async with self._changed:
            await self._changed.wait_for(lambda: self._version > last_seen)
            return self._version
```

Why one `apply()` per batch: PLAN §6 wants **one SSE event per tick containing all tickers**. The simulator moves every ticker in one call; the Massive poller writes one batch per HTTP response. SSE handlers wake once per batch, build one event, and go back to sleep. No per-ticker events, no timer-based polling of the cache.

The cache is process-local and single-event-loop. Run exactly one Uvicorn worker (`--workers 1`); document this in the Dockerfile `CMD`.

---

## 5. The abstract source (`base.py`)

```python
from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    """Produces price ticks for a mutable set of tickers into a PriceCache."""

    name: str                      # "simulator" | "massive:snapshot" | "massive:eod"

    def __init__(self, cache: PriceCache):
        self.cache = cache
        self._tickers: set[str] = set()
        self._task: asyncio.Task | None = None

    # ---- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        """Begin producing ticks. Idempotent. Must return promptly (spawn a task)."""
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"market:{self.name}")

    async def stop(self) -> None:
        """Cancel the background task and release resources. Idempotent."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    # ---- ticker set -------------------------------------------------------
    async def set_tickers(self, tickers: set[str]) -> None:
        """Replace the priced set. Added tickers are primed before this returns;
        removed tickers are dropped from the cache. Removal is computed against the cache
        too, so a ticker that was only ever prime()d ages out here."""
        tickers = set(tickers)
        added = tickers - self._tickers
        removed = (self._tickers | self.cache.tickers()) - tickers
        self._tickers = tickers
        if removed:
            await self.cache.drop(*removed)
        if added:
            await self.prime(added)

    async def prime(self, tickers: set[str], timeout: float = 5.0) -> dict[str, Quote]:
        """Ensure each ticker has a price in the cache, fetching if needed. Returns what is
        now cached. Missing keys mean 'no price available'. This is what the trade service
        calls before pricing a buy for a symbol in neither watchlist nor positions."""
        missing = {t for t in tickers if self.cache.get(t) is None}
        if missing:
            await asyncio.wait_for(self._fetch_now(missing), timeout)
        return {t: q for t in tickers if (q := self.cache.get(t))}

    # ---- implementation hooks --------------------------------------------
    @abstractmethod
    async def _run(self) -> None:
        """The long-running loop. Must handle CancelledError and its own errors."""

    @abstractmethod
    async def _fetch_now(self, tickers: set[str]) -> None:
        """Produce a price for each ticker immediately and write it to the cache."""

    # ---- diagnostics ------------------------------------------------------
    def health(self) -> dict:
        """Merged into GET /api/health. At minimum {'name', 'tickers', 'last_tick_ms'}."""
        return {"name": self.name, "tickers": sorted(self._tickers)}
```

Contract notes:

- `prime()` is the answer to "how does a buy of an unwatched ticker get a price". The trade service calls `await source.prime({ticker})` and uses the returned quote, or returns `503 {"detail": "Price unavailable for XYZ"}` if the ticker is absent. After a successful buy the ticker is in `positions`, so the next `set_tickers()` keeps it. If the buy fails, nothing retains it and it ages out at the next `set_tickers()`.
- `set_tickers()` is called by the app after any watchlist or position mutation, with the fresh `watchlist ∪ positions`. It is cheap to call with an unchanged set.
- Sources must never raise out of `_run()`. Log, back off, keep the last cached prices, retry.

---

## 6. Simulator source (summary)

`SimulatorSource(cache, config)` ticks every 500 ms, moving every ticker in `_tickers` by one GBM step and calling `cache.apply()` once per tick. `_fetch_now()` seeds the ticker (from the seed table or the hashed fallback) and writes a single tick so the price exists immediately. `session_open` is the seed price. Full detail in [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md).

---

## 7. Massive source (`massive_source.py`)

```python
class MassiveSource(MarketDataSource):
    def __init__(self, cache: PriceCache, client: MassiveClient, cfg: MarketConfig):
        super().__init__(cache)
        self._client, self._cfg = client, cfg
        self._mode: str | None = None      # "snapshot" | "eod", decided at start
        self.name = "massive"
        self._last_ok_ms = 0
        self._consecutive_errors = 0

    async def start(self) -> None:
        self._mode = self._cfg.massive_mode or await detect_mode(self._client)   # see MASSIVE_API.md §6
        self.name = f"massive:{self._mode}"
        await super().start()

    async def _run(self) -> None:
        while True:
            try:
                await self._fetch_now(set(self._tickers))
                self._consecutive_errors = 0
                delay = self._interval()
            except NotEntitled:
                # plan changed mid-run, or probe was wrong: degrade to EOD rather than die
                self._mode, self.name = "eod", "massive:eod"
                delay = 1
            except Exception as e:                        # 429, 5xx, timeouts, DNS
                self._consecutive_errors += 1
                delay = min(600, 60 * 2 ** (self._consecutive_errors - 1))
                log.warning("massive poll failed (%s); retrying in %ss", e, delay)
            await asyncio.sleep(delay)

    async def _fetch_now(self, tickers: set[str]) -> None:
        if not tickers:
            return
        quotes = await (self._client.snapshot(sorted(tickers)) if self._mode == "snapshot"
                        else self._client.latest_eod(tickers))
        ticks = {q.ticker: (q.price, q.as_of_ms, q.source) for q in quotes.values()}
        opens = {q.ticker: q.previous_close for q in quotes.values() if q.previous_close}
        await self.cache.apply(ticks, session_open=opens)
        self._last_ok_ms = int(time.time() * 1000)

    def _interval(self) -> float:
        if self._mode == "eod":
            return self._cfg.poll_interval or 900.0
        return self._cfg.poll_interval or 15.0

    def health(self) -> dict:
        return {**super().health(), "mode": self._mode, "last_ok_ms": self._last_ok_ms,
                "consecutive_errors": self._consecutive_errors}
```

Design decisions:

- **Mode detection once at start**, by probing the unified snapshot with one ticker. `MASSIVE_MODE=snapshot|eod` overrides the probe (useful in tests and when the probe burns a Basic-plan call you'd rather keep).
- **One HTTP request per poll** regardless of ticker count (≤ 250). Above 250 tickers, chunk; FinAlly will never get there.
- **`session_open` = previous close** from the API, so "change %" is a real daily change. Falls back to first observed price if the API omits it.
- **Backoff** is exponential from 60 s (Basic's window) capped at 10 min. On any failure the cache keeps its last prices and SSE keeps streaming them, so the UI stays alive, just flat. The health endpoint exposes `consecutive_errors` so the status dot can turn yellow.
- **Market closed**: optional refinement, poll `/v1/marketstatus/now` once per 5 min and stretch the interval to 300 s while `market == "closed"`. Not required for correctness.
- Rate budget on Basic: one grouped-daily poll every 15 min plus a walk-back of at most ten calls on the first poll of a day is well under 5/min averaged, but the walk-back itself can exceed 5 calls in one minute on a holiday weekend. Sleep 13 s between walk-back calls to stay under the limit.

---

## 8. Selection and lifecycle (`__init__.py`, `config.py`, `main.py`)

```python
# config.py
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MarketConfig:
    massive_api_key: str | None
    massive_mode: str | None          # None = auto-detect
    poll_interval: float | None       # None = per-mode default
    sim_seed: int | None              # None = nondeterministic
    sim_tick_ms: int = 500

    @classmethod
    def from_env(cls) -> "MarketConfig":
        key = (os.getenv("MASSIVE_API_KEY") or "").strip() or None
        return cls(
            massive_api_key=key,
            massive_mode=os.getenv("MASSIVE_MODE") or None,
            poll_interval=float(os.environ["MASSIVE_POLL_INTERVAL"]) if os.getenv("MASSIVE_POLL_INTERVAL") else None,
            sim_seed=int(os.environ["SIM_SEED"]) if os.getenv("SIM_SEED") else None,
            sim_tick_ms=int(os.getenv("SIM_TICK_MS", "500")),
        )
```

```python
# __init__.py
def build_source(cache: PriceCache, cfg: MarketConfig) -> MarketDataSource:
    if cfg.massive_api_key:
        return MassiveSource(cache, MassiveClient(cfg.massive_api_key), cfg)
    return SimulatorSource(cache, cfg)
```

```python
# main.py (FastAPI lifespan)
@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = MarketConfig.from_env()
    cache = PriceCache()
    source = build_source(cache, cfg)
    app.state.cache, app.state.source = cache, source
    await source.set_tickers(await load_priced_set())       # watchlist ∪ positions from DB
    await source.start()
    yield
    await source.stop()
```

Selection rule, stated once: **`MASSIVE_API_KEY` set and non-blank → Massive; anything else → simulator.** There is no runtime switching and no "try Massive, fall back to simulator on error": a wrong key fails loudly at startup with a clear log line and `/api/health` reports `"market_data": "massive:error"`. Silently falling back would hide a misconfiguration behind fake prices.

Exception: if the key is set but the **first** request returns 401/403 for the key itself (not for an endpoint), startup logs `MASSIVE_API_KEY rejected; using simulator` and builds the simulator instead. The health endpoint then reports `"market_data": "simulator"` with `"market_data_note": "massive key rejected"`. This keeps the single-script first launch working when a student pastes a bad key.

---

## 9. Consumers

**SSE stream** (`GET /api/stream/prices`):

```python
async def event_stream(cache: PriceCache):
    yield "retry: 2000\n\n"
    version = 0
    while True:
        try:
            version = await asyncio.wait_for(cache.wait_for_change(version), timeout=15)
            snap = cache.snapshot()
            yield f"event: prices\ndata: {json.dumps(to_sse_payload(snap))}\n\n"
        except asyncio.TimeoutError:
            yield ": ping\n\n"                        # keepalive when nothing moved (EOD mode, market closed)
```

`to_sse_payload()` maps `Quote` → `{ticker, price, prev_price, session_open, change_pct, direction}` and formats `ts` as ISO-8601 `Z`. In EOD mode the stream still sends a full snapshot on connect, then pings every 15 s until the next daily update.

**History** (`GET /api/prices/{ticker}/history`): `cache.history(ticker)` → `[{ts, price}]`. For an unknown ticker, return `[]` with 200 (not 404; it may simply not be priced).

**Trade pricing**: the trade service calls `source.prime({ticker})` then reads `cache.get(ticker).price` **inside** the trade transaction. The price used is recorded on the `trades` row. If `prime()` returns nothing for the ticker, respond `503 {"detail": "Price unavailable for XYZ"}`.

**Portfolio valuation and snapshots**: read `cache.get(t).price` for each position. The 30-second snapshot task does the same.

**Health**: `/api/health` includes `"market_data": source.name` and `"market": source.health()`.

---

## 10. Environment variables

| Variable | Default | Effect |
|---|---|---|
| `MASSIVE_API_KEY` | unset | Set and non-blank selects the Massive source |
| `MASSIVE_MODE` | auto | `snapshot` or `eod`; skips the entitlement probe |
| `MASSIVE_POLL_INTERVAL` | 15 (snapshot) / 900 (eod) | Seconds between polls |
| `SIM_SEED` | unset | Integer seed for reproducible simulator paths (tests) |
| `SIM_TICK_MS` | 500 | Simulator tick interval |

`.env.example` should list all five with comments.

---

## 11. Testing

**Conformance suite** (`backend/tests/market/test_source_contract.py`), parametrized over both sources. The Massive source is constructed with an `httpx.MockTransport` that serves canned JSON from `tests/market/fixtures/`.

For each source it asserts:

- `start()` then `stop()` is clean and idempotent; no task leaks.
- After `set_tickers({"AAPL","MSFT"})`, both appear in the cache within one interval with positive finite prices.
- `set_tickers({"AAPL"})` drops MSFT from the cache.
- `prime({"ZZZZ"})` returns a quote for ZZZZ without it being in the ticker set (simulator: always; Massive: when the fixture contains it) and returns `{}` for a symbol the fixture lacks.
- `session_open` is fixed across subsequent ticks.
- `history()` is oldest-first and capped at 600.
- Exactly one `cache.apply()` per poll/tick (spy on the cache), so one SSE event per batch.
- `health()` contains `name` and `tickers`.

**Massive-specific**:

- Probe returns 403 → mode `eod`; returns 200 → mode `snapshot`.
- Unified snapshot rows with `error: NOT_FOUND` / `NOT_ENTITLED` are skipped without aborting the batch.
- `limit=250` and `type=stocks` are present on the request.
- Grouped-daily walk-back skips empty days and stops after two non-empty days; `previous_close` comes from the earlier day.
- A 429 sets a ≥ 60 s delay; three consecutive failures grow the delay; a success resets it.
- A 401 on the key at startup falls back to the simulator and the health note is set.

**Simulator-specific**: see MARKET_SIMULATOR.md §8.

**No test contacts the network.** A separate, opt-in `tests/market/test_massive_live.py` (skipped unless `MASSIVE_API_KEY` is set and `--run-live` is passed) does one real snapshot or grouped-daily call to catch schema drift.

---

## 12. Open items and decisions taken

- Chosen: `httpx` over the official `massive` package (async-native, easier to mock, no import-time env read).
- Chosen: `prime()` on the source rather than a separate "pricing service", so the trade path has one dependency.
- Chosen: no automatic simulator fallback on runtime errors, only on a rejected key at startup.
- Deferred: WebSocket source for Advanced plans. It would be a third `MarketDataSource` implementation writing to the same cache; nothing else changes.
- Deferred: persisting ring-buffer history across restarts. Not needed for a demo.

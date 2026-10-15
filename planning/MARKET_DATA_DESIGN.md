# FinAlly — Market Data Backend Design

This document is the implementation-level design for everything in the backend
that produces prices: the unified source interface, the GBM simulator, the
Massive REST client, the shared price cache, the polling service, and the SSE
stream that feeds the frontend. It expands sections 5, 6 and 8 of `PLAN.md`
and is the contract that the Backend, Market Data, and Frontend agents build
against.

Code snippets are written for Python 3.12 / FastAPI / `uv` and are meant to be
copied nearly verbatim into `backend/app/market_data/`.

---

## 1. Goals and non-goals

**Goals**

- One interface, two implementations (simulator, Massive). Nothing downstream
  knows which one is running.
- The simulator is the default and needs zero configuration or network.
- The Massive client respects the free-tier budget (5 calls/min) and degrades
  gracefully on rate limits, auth errors, and market-closed hours.
- Prices live in one in-memory cache written by one background task and read
  by many consumers (SSE clients, trade execution, portfolio snapshots, chat
  context).
- The SSE stream delivers every price change at ~500 ms cadence with the
  fields the frontend needs for flashes, day-change %, and sparklines.
- Everything is unit-testable without network and deterministic under a seed.

**Non-goals**

- No WebSockets, no order book, no historical candles from the provider. The
  main chart and sparklines are built on the frontend from the live stream.
- No multi-user fan-out logic beyond what the single cache already gives us.
- No persistence of ticks. The only persisted time series is
  `portfolio_snapshots`, owned by the portfolio module.

---

## 2. Component overview

```
                 ┌──────────────────────────────────────────────────────────┐
                 │ FastAPI process                                          │
                 │                                                          │
   .env ───────▶ │  config.MarketDataSettings                               │
                 │          │                                               │
                 │          ▼  build_market_data_service()                  │
                 │  ┌───────────────────────┐    ┌───────────────────────┐  │
                 │  │ SimulatedMarketData   │ or │ MassiveMarketData     │  │
                 │  │ Source (GBM, in-proc) │    │ Source (httpx → REST) │  │
                 │  └──────────┬────────────┘    └──────────┬────────────┘  │
                 │             └──────── MarketDataSource ───┘               │
                 │                              │ fetch(tickers) -> Quotes   │
                 │                              ▼                            │
                 │                 MarketDataService (poll loop task)        │
                 │                  tracked tickers = watchlist ∪ positions  │
                 │                              │ cache.update(quotes)       │
                 │                              ▼                            │
                 │                        PriceCache (dict + version)        │
                 │           ┌──────────────┬───┴──────────┬──────────────┐  │
                 │           ▼              ▼              ▼              ▼  │
                 │   GET /api/stream   POST /api/portfolio  snapshot    chat │
                 │   /prices (SSE)     /trade (fill price)  task (30s)  ctx  │
                 └──────────────────────────────────────────────────────────┘
```

Key properties:

- **Single writer.** Only `MarketDataService._poll()` writes to the cache.
  Everything else reads. Because FastAPI runs on one asyncio event loop and no
  thread ever touches the cache, no locks are needed.
- **Pull-through for new tickers.** Adding a ticker to the watchlist (manually
  or via chat) calls `service.track()`, which validates the ticker against the
  source and primes the cache in one call.
- **Cadence belongs to the source.** The simulator reports a 0.5 s interval,
  Massive reports 15 s (configurable). The service loop just honors
  `source.poll_interval`. The SSE loop has its own independent 0.5 s cadence
  and only emits when the cache version moved.

---

## 3. Module layout

```
backend/
├── pyproject.toml
└── app/
    ├── main.py                   # FastAPI app, lifespan, static files
    ├── config.py                 # env → MarketDataSettings (and other settings)
    ├── market_data/
    │   ├── __init__.py           # re-exports: build_market_data_service, MarketDataService, ...
    │   ├── models.py             # Quote, PriceEntry, Direction
    │   ├── errors.py             # MarketDataError hierarchy
    │   ├── source.py             # MarketDataSource ABC, normalize_ticker
    │   ├── cache.py              # PriceCache
    │   ├── simulator.py          # SimulatedMarketDataSource + seed profiles
    │   ├── massive.py            # MassiveMarketDataSource + parse_snapshot
    │   ├── service.py            # MarketDataService (poll loop) + factory
    │   └── sse.py                # format_sse + /api/stream/prices router
    └── ...                       # portfolio/, watchlist/, chat/, db/ (other designs)

backend/tests/market_data/
    ├── conftest.py
    ├── test_cache.py
    ├── test_simulator.py
    ├── test_massive.py
    ├── test_service.py
    ├── test_interface.py
    └── test_sse.py
```

Dependencies to add to the uv project:

```bash
cd backend
uv add fastapi "uvicorn[standard]" httpx python-dotenv
uv add --dev pytest pytest-asyncio
```

No numpy: the simulator uses `random.Random` and `math`, which keeps the image
small and makes seeding trivial.

---

## 4. Configuration

### 4.1 Environment variables

The three variables from `PLAN.md` stay as-is. The market-data module adds
optional tuning knobs, all with sensible defaults, so `.env.example` becomes:

```bash
# ---- Required ----
OPENROUTER_API_KEY=your-openrouter-api-key-here

# ---- Market data source selection ----
# Empty / unset  -> built-in simulator (default)
# Non-empty      -> Massive (formerly Polygon.io) REST API
MASSIVE_API_KEY=

# ---- Massive tuning (only used when MASSIVE_API_KEY is set) ----
MASSIVE_BASE_URL=https://api.massive.com   # legacy https://api.polygon.io also works
MASSIVE_POLL_INTERVAL=15                   # seconds; free tier = 5 calls/min -> keep >= 15
MASSIVE_FALLBACK_TO_SIM=true               # on 401/403 at startup, fall back to simulator

# ---- Simulator tuning ----
SIM_TICK_INTERVAL=0.5        # seconds between simulated ticks
SIM_TIME_SCALE=60            # 1 real second = 60 simulated seconds (visible motion)
SIM_SEED=                    # integer for deterministic runs (tests); empty = random
SIM_EVENT_PROB=0.0017        # per-ticker, per-tick chance of a 2-5% "news" jump (~1 per 5 min)

# ---- SSE ----
SSE_PUSH_INTERVAL=0.5        # seconds between cache checks per client
SSE_KEEPALIVE_INTERVAL=15    # send a comment line if nothing changed for this long

# ---- Testing ----
LLM_MOCK=false
```

### 4.2 `config.py`

```python
# backend/app/config.py
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# backend/app/config.py -> parents[2] is the project root (where .env lives).
# In Docker the variables arrive via --env-file, so a missing .env is fine.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_float(name: str, default: float) -> float:
    raw = _env_str(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_str(name).lower()
    return default if not raw else raw in {"1", "true", "yes", "on"}


def _env_optional_int(name: str) -> int | None:
    raw = _env_str(name)
    return int(raw) if raw else None


@dataclass(frozen=True, slots=True)
class MarketDataSettings:
    massive_api_key: str = ""
    massive_base_url: str = "https://api.massive.com"
    massive_poll_interval: float = 15.0
    massive_fallback_to_sim: bool = True

    sim_tick_interval: float = 0.5
    sim_time_scale: float = 60.0
    sim_seed: int | None = None
    sim_event_prob: float = 1 / 600

    sse_push_interval: float = 0.5
    sse_keepalive_interval: float = 15.0

    @property
    def use_massive(self) -> bool:
        return bool(self.massive_api_key)

    @classmethod
    def from_env(cls) -> "MarketDataSettings":
        return cls(
            massive_api_key=_env_str("MASSIVE_API_KEY"),
            massive_base_url=_env_str("MASSIVE_BASE_URL", "https://api.massive.com").rstrip("/"),
            massive_poll_interval=max(1.0, _env_float("MASSIVE_POLL_INTERVAL", 15.0)),
            massive_fallback_to_sim=_env_bool("MASSIVE_FALLBACK_TO_SIM", True),
            sim_tick_interval=max(0.1, _env_float("SIM_TICK_INTERVAL", 0.5)),
            sim_time_scale=max(1.0, _env_float("SIM_TIME_SCALE", 60.0)),
            sim_seed=_env_optional_int("SIM_SEED"),
            sim_event_prob=_env_float("SIM_EVENT_PROB", 1 / 600),
            sse_push_interval=max(0.1, _env_float("SSE_PUSH_INTERVAL", 0.5)),
            sse_keepalive_interval=max(1.0, _env_float("SSE_KEEPALIVE_INTERVAL", 15.0)),
        )


@lru_cache
def get_market_data_settings() -> MarketDataSettings:
    return MarketDataSettings.from_env()
```

Tests call `MarketDataSettings(sim_seed=42)` directly and never touch the
environment.

---

## 5. Data model

Two types cross module boundaries. `Quote` is what a source *produces* for one
ticker on one fetch. `PriceEntry` is what the cache *holds* and what the SSE
stream and the REST layer *read*.

```python
# backend/app/market_data/models.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Direction = Literal["up", "down", "flat"]


@dataclass(frozen=True, slots=True)
class Quote:
    """One observation from a source. Immutable."""
    ticker: str
    price: float        # last traded / simulated price
    prev_close: float   # reference for the day-change column (previous session close)
    timestamp: float    # unix seconds, UTC


@dataclass(slots=True)
class PriceEntry:
    """Cache state for one ticker. Mutated in place only by PriceCache."""
    ticker: str
    price: float
    prev_price: float   # price before the most recent change (drives up/down flash)
    prev_close: float
    timestamp: float
    version: int        # cache version at the last price change

    @property
    def direction(self) -> Direction:
        if self.price > self.prev_price:
            return "up"
        if self.price < self.prev_price:
            return "down"
        return "flat"

    @property
    def change(self) -> float:
        return round(self.price - self.prev_close, 4)

    @property
    def change_pct(self) -> float:
        if not self.prev_close:
            return 0.0
        return round((self.price / self.prev_close - 1.0) * 100.0, 4)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "prev_price": self.prev_price,
            "prev_close": self.prev_close,
            "change": self.change,
            "change_pct": self.change_pct,
            "direction": self.direction,
            "timestamp": self.timestamp,
        }
```

Why `prev_close` is in the model: `PLAN.md` asks the watchlist to show a
"daily change %". For Massive that is `prevDay.c`; for the simulator it is the
seed price the session opened from. Without it the frontend could only show
change-since-page-load.

### 5.1 Errors

```python
# backend/app/market_data/errors.py
class MarketDataError(Exception):
    """Base class for anything the market data layer raises."""


class UnknownTickerError(MarketDataError):
    """The source has no data for this symbol (invalid or unsupported ticker)."""

    def __init__(self, ticker: str):
        super().__init__(f"Unknown ticker: {ticker}")
        self.ticker = ticker


class RateLimitedError(MarketDataError):
    """The provider returned 429. retry_after is in seconds."""

    def __init__(self, retry_after: float = 60.0):
        super().__init__(f"Rate limited; retry after {retry_after:.0f}s")
        self.retry_after = retry_after


class SourceAuthError(MarketDataError):
    """401/403 from the provider: bad or unentitled API key."""


class SourceUnavailableError(MarketDataError):
    """Transport or 5xx failure; transient, the loop backs off and retries."""
```

The REST layer maps `UnknownTickerError` → HTTP 404 on watchlist add and
HTTP 422 on trades; everything else is logged and never surfaces to the user
as anything but a stale price.

---

## 6. Unified source interface

```python
# backend/app/market_data/source.py
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar

from .errors import UnknownTickerError
from .models import Quote

# 1-5 uppercase letters, optional class suffix (BRK.B, BF-B).
_TICKER_RE = re.compile(r"^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$")


def normalize_ticker(raw: str) -> str:
    """Uppercase/strip and validate the *shape* of a ticker. Cheap, no I/O."""
    ticker = (raw or "").strip().upper()
    if not _TICKER_RE.match(ticker):
        raise UnknownTickerError(raw)
    return ticker


class MarketDataSource(ABC):
    """A thing that can produce quotes for a list of tickers.

    Implementations are stateless from the caller's point of view: calling
    fetch() twice with the same tickers returns two observations. Whether an
    observation is "advance the simulation one step" or "hit the REST API"
    is the implementation's business.
    """

    name: ClassVar[str]

    @property
    @abstractmethod
    def poll_interval(self) -> float:
        """Seconds the service should wait between fetch() calls."""

    @abstractmethod
    async def fetch(self, tickers: Sequence[str]) -> dict[str, Quote]:
        """Return a quote for every ticker the source knows. Unknown tickers
        are simply absent from the result (never raise for them). An empty
        input returns an empty dict without doing any work."""

    async def validate(self, ticker: str) -> Quote:
        """Default validation: fetch the single ticker and require a quote."""
        quotes = await self.fetch([ticker])
        if ticker not in quotes:
            raise UnknownTickerError(ticker)
        return quotes[ticker]

    async def aclose(self) -> None:
        """Release network resources. No-op by default."""
        return None
```

Design notes:

- `fetch()` takes the full ticker list every call. For Massive this maps to a
  single snapshot request; for the simulator it is one simulation step. This
  is what makes the two interchangeable: both are "give me the current state
  of these N symbols".
- Unknown tickers are *absent*, not exceptions, so one bad symbol in the
  tracked set can never stall the loop for the other nine.
- `validate()` is overridable. The simulator overrides it to be pure (any
  well-formed ticker is accepted and gets a synthetic price); Massive uses the
  default (a real lookup).

---

## 7. Price cache

```python
# backend/app/market_data/cache.py
from __future__ import annotations

from collections.abc import Iterable

from .models import PriceEntry, Quote


class PriceCache:
    """In-memory latest-price store with a monotonic version counter.

    The version increments once per *price change*, not per update() call,
    so SSE clients can ask "what changed since version N?" and get exactly
    the entries whose price moved. All methods are synchronous and safe
    because the whole app runs on one event loop thread.
    """

    def __init__(self) -> None:
        self._entries: dict[str, PriceEntry] = {}
        self._version: int = 0

    # ---- write side (MarketDataService only) ------------------------------

    def update(self, quotes: Iterable[Quote]) -> list[str]:
        """Merge quotes; return tickers whose price actually changed."""
        changed: list[str] = []
        for q in quotes:
            cur = self._entries.get(q.ticker)
            if cur is None:
                self._version += 1
                self._entries[q.ticker] = PriceEntry(
                    ticker=q.ticker,
                    price=q.price,
                    prev_price=q.price,          # first sight: flat
                    prev_close=q.prev_close,
                    timestamp=q.timestamp,
                    version=self._version,
                )
                changed.append(q.ticker)
            elif q.price != cur.price:
                self._version += 1
                cur.prev_price = cur.price
                cur.price = q.price
                cur.prev_close = q.prev_close
                cur.timestamp = q.timestamp
                cur.version = self._version
                changed.append(q.ticker)
            else:
                # Same price (e.g. Massive poll outside market hours): refresh
                # the timestamp quietly, don't bump the version.
                cur.timestamp = max(cur.timestamp, q.timestamp)
        return changed

    def remove(self, ticker: str) -> None:
        self._entries.pop(ticker, None)

    # ---- read side ----------------------------------------------------------

    @property
    def version(self) -> int:
        return self._version

    def get(self, ticker: str) -> PriceEntry | None:
        return self._entries.get(ticker)

    def price(self, ticker: str) -> float | None:
        entry = self._entries.get(ticker)
        return entry.price if entry else None

    def prices(self) -> dict[str, float]:
        return {t: e.price for t, e in self._entries.items()}

    def snapshot(self) -> list[PriceEntry]:
        return sorted(self._entries.values(), key=lambda e: e.ticker)

    def changed_since(self, version: int) -> list[PriceEntry]:
        return sorted(
            (e for e in self._entries.values() if e.version > version),
            key=lambda e: e.ticker,
        )

    def __contains__(self, ticker: str) -> bool:
        return ticker in self._entries

    def __len__(self) -> int:
        return len(self._entries)
```

Consumers and what they call:

| Consumer | Call | Notes |
|---|---|---|
| SSE stream | `changed_since(v)`, `snapshot()` | Each client tracks its own `v` |
| Trade execution | `price(ticker)` | Fill price; `None` → call `service.ensure_price()` |
| Portfolio GET / snapshot task | `prices()` | Mark-to-market every position in one pass |
| Watchlist GET | `get(ticker)` | Joins DB rows with live price, `null` if not yet fetched |
| Chat context builder | `prices()` + `get()` | Live prices in the LLM prompt |

---

## 8. Simulator

### 8.1 Model

Each ticker follows geometric Brownian motion with a correlated shock, a
gentle pull back toward its seed price (so an all-night run never drifts to
$0 or $10,000), and occasional multi-tick "news" jumps.

Per tick, for ticker *i* with annual drift μᵢ and volatility σᵢ:

```
dt      = tick_interval * time_scale / TRADING_SECONDS_PER_YEAR
zᵢ      = βᵢ·√w_m·M  +  √w_s·S_sector(i)  +  √w_e·εᵢ          (M, S, ε ~ N(0,1))
rᵢ      = (μᵢ − σᵢ²/2)·dt  +  σᵢ·√dt·zᵢ                      (GBM log-return)
        + κ·ln(seedᵢ / priceᵢ)                                 (mean reversion)
        + jumpᵢ                                                (pending event slice, if any)
priceᵢ ← priceᵢ · exp(rᵢ)
```

- `w_m = 0.40`, `w_s = 0.30`, `w_e = 0.30` are variance shares for the
  market, sector and idiosyncratic factors. Tech names share one `S`, so they
  visibly move together; JPM and V share another.
- `TRADING_SECONDS_PER_YEAR = 252 × 6.5 × 3600 = 5,896,800`.
- With the defaults (σ = 0.30, tick = 0.5 s, time_scale = 60) one tick has
  σ√dt ≈ 0.07 %, so a sparkline over a minute shows ~0.5 % swings: lively but
  not absurd. `SIM_TIME_SCALE=1` gives realistic-but-boring motion.
- `κ` is derived from a half-life in real seconds (default 30 min):
  `κ = ln2 / half_life × tick_interval`. At 30 min a 5 % deviation decays to
  2.5 % in half an hour, which is invisible tick-to-tick but keeps prices
  bounded over days.
- Events: with probability `event_prob` per ticker per tick, a jump of
  ±2–5 % is scheduled and spread over 4 ticks (≈2 s), so the UI flashes
  several times in the same direction instead of a single discontinuity.

### 8.2 Seed prices

```python
# backend/app/market_data/simulator.py (top of file)
from __future__ import annotations

import math
import random
import time
import zlib
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field

from .models import Quote
from .source import MarketDataSource, normalize_ticker

TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600
W_MARKET, W_SECTOR, W_IDIO = 0.40, 0.30, 0.30


@dataclass(frozen=True, slots=True)
class TickerProfile:
    seed_price: float
    sector: str
    drift: float = 0.08        # annualised
    vol: float = 0.30          # annualised
    market_beta: float = 1.0


# Static, "about right" prices. They are seeds, not quotes: the point is that
# AAPL looks like AAPL. Extend freely; unknown symbols get a synthetic profile.
PROFILES: dict[str, TickerProfile] = {
    # Default watchlist (must match the DB seed list in PLAN.md §7)
    "AAPL":  TickerProfile(190.0, "tech",    vol=0.25),
    "GOOGL": TickerProfile(175.0, "tech",    vol=0.28),
    "MSFT":  TickerProfile(420.0, "tech",    vol=0.24),
    "AMZN":  TickerProfile(185.0, "tech",    vol=0.32),
    "TSLA":  TickerProfile(250.0, "auto",    vol=0.55, market_beta=1.6),
    "NVDA":  TickerProfile(120.0, "tech",    vol=0.50, market_beta=1.5),
    "META":  TickerProfile(500.0, "tech",    vol=0.35, market_beta=1.2),
    "JPM":   TickerProfile(200.0, "finance", vol=0.22, market_beta=0.9),
    "V":     TickerProfile(275.0, "finance", vol=0.20, market_beta=0.8),
    "NFLX":  TickerProfile(650.0, "media",   vol=0.38, market_beta=1.1),
    # Extras the AI or users commonly ask for
    "AMD":   TickerProfile(160.0, "tech",    vol=0.48, market_beta=1.5),
    "INTC":  TickerProfile(30.0,  "tech",    vol=0.40),
    "PYPL":  TickerProfile(65.0,  "finance", vol=0.38, market_beta=1.2),
    "DIS":   TickerProfile(95.0,  "media",   vol=0.30),
    "BA":    TickerProfile(180.0, "industrial", vol=0.35),
    "KO":    TickerProfile(62.0,  "consumer", vol=0.15, market_beta=0.5),
    "WMT":   TickerProfile(70.0,  "consumer", vol=0.18, market_beta=0.6),
    "XOM":   TickerProfile(115.0, "energy",  vol=0.25, market_beta=0.7),
    "GS":    TickerProfile(450.0, "finance", vol=0.28, market_beta=1.1),
    "UBER":  TickerProfile(75.0,  "tech",    vol=0.42, market_beta=1.3),
}


def synthetic_profile(ticker: str) -> TickerProfile:
    """Deterministic made-up profile for any ticker not in PROFILES.
    Same ticker -> same seed price on every run (crc32-based)."""
    h = zlib.crc32(ticker.encode())
    seed_price = 20.0 + (h % 48_000) / 100.0          # $20.00 .. $499.99
    vol = 0.25 + ((h >> 8) % 30) / 100.0              # 0.25 .. 0.54
    sector = ("tech", "finance", "consumer", "energy", "media")[(h >> 16) % 5]
    return TickerProfile(seed_price, sector, vol=vol)
```

### 8.3 Source implementation

```python
# backend/app/market_data/simulator.py (continued)
@dataclass(slots=True)
class _TickerState:
    ticker: str
    profile: TickerProfile
    price: float          # unrounded internal price
    prev_close: float
    jumps: deque[float] = field(default_factory=deque)   # pending log-return slices

    def quote(self, now: float) -> Quote:
        decimals = 2 if self.price >= 1.0 else 4
        return Quote(
            ticker=self.ticker,
            price=round(self.price, decimals),
            prev_close=round(self.prev_close, decimals),
            timestamp=now,
        )


class SimulatedMarketDataSource(MarketDataSource):
    name = "simulator"

    def __init__(
        self,
        *,
        tick_interval: float = 0.5,
        time_scale: float = 60.0,
        seed: int | None = None,
        event_prob: float = 1 / 600,
        reversion_half_life_s: float = 1800.0,
        event_ticks: int = 4,
        profiles: dict[str, TickerProfile] | None = None,
    ) -> None:
        self._rng = random.Random(seed)
        self._tick_interval = tick_interval
        self._dt = tick_interval * time_scale / TRADING_SECONDS_PER_YEAR
        self._sqrt_dt = math.sqrt(self._dt)
        self._event_prob = event_prob
        self._event_ticks = max(1, event_ticks)
        self._kappa = math.log(2) / reversion_half_life_s * tick_interval
        self._profiles = profiles if profiles is not None else PROFILES
        self._state: dict[str, _TickerState] = {}

    # ---- MarketDataSource -----------------------------------------------------

    @property
    def poll_interval(self) -> float:
        return self._tick_interval

    async def validate(self, ticker: str) -> Quote:
        # Any well-formed symbol is tradeable in the simulator; it just gets a
        # synthetic price. normalize_ticker() already raised for bad shapes.
        normalize_ticker(ticker)
        return self._ensure(ticker).quote(time.time())

    async def fetch(self, tickers: Sequence[str]) -> dict[str, Quote]:
        if not tickers:
            return {}
        now = time.time()
        market_shock = self._rng.gauss(0.0, 1.0)
        sector_shocks: dict[str, float] = defaultdict(lambda: self._rng.gauss(0.0, 1.0))
        out: dict[str, Quote] = {}
        for ticker in tickers:
            state = self._ensure(ticker)
            self._step(state, market_shock, sector_shocks[state.profile.sector])
            out[ticker] = state.quote(now)
        return out

    # ---- internals -------------------------------------------------------------

    def _ensure(self, ticker: str) -> _TickerState:
        state = self._state.get(ticker)
        if state is None:
            profile = self._profiles.get(ticker) or synthetic_profile(ticker)
            # Open the session a little away from the seed so the day-change
            # column is not a wall of 0.00% at launch.
            opening = profile.seed_price * math.exp(self._rng.gauss(0.0, 0.01))
            state = _TickerState(ticker=ticker, profile=profile, price=opening, prev_close=profile.seed_price)
            self._state[ticker] = state
        return state

    def _step(self, state: _TickerState, market_shock: float, sector_shock: float) -> None:
        p = state.profile
        idio = self._rng.gauss(0.0, 1.0)
        z = (
            p.market_beta * math.sqrt(W_MARKET) * market_shock
            + math.sqrt(W_SECTOR) * sector_shock
            + math.sqrt(W_IDIO) * idio
        )
        ret = (p.drift - 0.5 * p.vol**2) * self._dt + p.vol * self._sqrt_dt * z
        ret += self._kappa * math.log(p.seed_price / state.price)

        if not state.jumps and self._rng.random() < self._event_prob:
            magnitude = self._rng.uniform(0.02, 0.05) * self._rng.choice((-1.0, 1.0))
            total_log = math.log1p(magnitude)
            state.jumps.extend([total_log / self._event_ticks] * self._event_ticks)
        if state.jumps:
            ret += state.jumps.popleft()

        state.price *= math.exp(ret)
```

Behavioural guarantees the tests pin down (see §13):

- Deterministic under `seed`: two sources with the same seed and the same call
  sequence produce identical quotes.
- Prices are always `> 0` (multiplicative updates cannot cross zero).
- Rounding happens only at the `Quote` boundary; internal state keeps full
  precision so sub-cent moves accumulate instead of being lost.
- A ticker's day-change (`price / prev_close − 1`) matches the frontend's
  `change_pct` field exactly because both derive from the same `prev_close`.

---

## 9. Massive REST client

### 9.1 Endpoint

Massive is the renamed Polygon.io. One endpoint covers everything we need:

```
GET {MASSIVE_BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,NVDA
Authorization: Bearer <MASSIVE_API_KEY>
```

- `tickers` is a comma-separated, case-sensitive list. Without it the endpoint
  returns the *entire* market (10k+ symbols, several MB), so always pass it.
- Auth works either as the `Authorization: Bearer` header or an `apiKey` query
  parameter. Use the header so the key never lands in access logs.
- Response shape (fields marked † are present only on plans with trades /
  quotes entitlement and must be treated as optional):

```json
{
  "status": "OK",
  "count": 2,
  "tickers": [
    {
      "ticker": "AAPL",
      "todaysChange": 1.23,
      "todaysChangePerc": 0.65,
      "updated": 1760000000123456789,
      "day":     {"o": 189.9, "h": 191.4, "l": 189.1, "c": 190.6, "v": 41234567, "vw": 190.3},
      "min":     {"av": 41234567, "t": 1760000000000, "n": 120, "o": 190.5, "h": 190.7, "l": 190.4, "c": 190.6, "v": 12000, "vw": 190.55},
      "prevDay": {"o": 188.0, "h": 190.1, "l": 187.6, "c": 189.4, "v": 50123456, "vw": 188.9},
      "lastTrade": {"p": 190.61, "s": 100, "t": 1760000000123456789, "x": 4},   "†": "trades plan",
      "lastQuote": {"P": 190.62, "S": 2, "p": 190.60, "s": 3, "t": 1760000000123456789}
    }
  ]
}
```

- Tickers that don't exist are silently omitted from `tickers[]`; that is how
  we detect an invalid symbol (one call, no extra reference lookup).
- Snapshot data is cleared daily at 03:30 ET and repopulates from ~04:00 ET as
  pre-market trades arrive. During that window `day`/`min` may be empty and we
  fall through to `prevDay.c`. Outside market hours prices simply stop moving;
  the cache's "same price → no version bump" rule means SSE clients receive
  keep-alives only, which is correct.
- Timestamps: `lastTrade.t` and `updated` are nanoseconds, `min.t` is
  milliseconds. The parser normalises all of them to seconds.

### 9.2 Rate budget

| Plan | Limit | Poll interval | Notes |
|---|---|---|---|
| Basic (free) | 5 calls/min, delayed/EOD data | 15 s (4/min) | Leaves 1 call/min for on-demand ticker validation |
| Starter | unlimited, 15-min delayed | 5 s | `lastTrade` absent; price comes from `min.c` |
| Developer / Advanced | unlimited, real-time | 2 s | `lastTrade.p` available |

`MASSIVE_POLL_INTERVAL` is the only knob; the loop additionally backs off to
`Retry-After` (or doubles, capped at 60 s) on a 429.

### 9.3 Parser (pure, fully unit-tested)

```python
# backend/app/market_data/massive.py
from __future__ import annotations

import logging
import time
from collections.abc import Sequence

import httpx

from .errors import RateLimitedError, SourceAuthError, SourceUnavailableError
from .models import Quote
from .source import MarketDataSource

log = logging.getLogger(__name__)

SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"


def _first_positive(*values) -> float | None:
    for v in values:
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def _epoch_seconds(value) -> float | None:
    """Accept ns / µs / ms / s epoch values and return seconds."""
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    v = float(value)
    if v > 1e17:      # nanoseconds
        return v / 1e9
    if v > 1e14:      # microseconds
        return v / 1e6
    if v > 1e11:      # milliseconds
        return v / 1e3
    return v


def parse_ticker_item(item: dict) -> Quote | None:
    ticker = item.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        return None
    last_trade = item.get("lastTrade") or {}
    minute = item.get("min") or {}
    day = item.get("day") or {}
    prev = item.get("prevDay") or {}

    # Precedence: real-time trade > last minute bar > today's running close >
    # previous close. Lower tiers lack the earlier fields; pre-market lacks
    # the middle ones.
    price = _first_positive(last_trade.get("p"), minute.get("c"), day.get("c"), prev.get("c"))
    if price is None:
        return None
    prev_close = _first_positive(prev.get("c")) or price

    timestamp = (
        _epoch_seconds(last_trade.get("t"))
        or _epoch_seconds(minute.get("t"))
        or _epoch_seconds(item.get("updated"))
        or time.time()
    )
    return Quote(ticker=ticker, price=price, prev_close=prev_close, timestamp=timestamp)


def parse_snapshot(payload: dict) -> dict[str, Quote]:
    quotes: dict[str, Quote] = {}
    for item in payload.get("tickers") or []:
        if not isinstance(item, dict):
            continue
        quote = parse_ticker_item(item)
        if quote is not None:
            quotes[quote.ticker] = quote
    return quotes
```

### 9.4 Source implementation

```python
# backend/app/market_data/massive.py (continued)
class MassiveMarketDataSource(MarketDataSource):
    name = "massive"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.massive.com",
        poll_interval: float = 15.0,
        client: httpx.AsyncClient | None = None,   # injectable for tests
    ) -> None:
        if not api_key:
            raise ValueError("MassiveMarketDataSource requires an API key")
        self._poll_interval = poll_interval
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "finally-trading-workstation/1.0",
            },
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    @property
    def poll_interval(self) -> float:
        return self._poll_interval

    async def fetch(self, tickers: Sequence[str]) -> dict[str, Quote]:
        if not tickers:
            return {}
        try:
            resp = await self._client.get(SNAPSHOT_PATH, params={"tickers": ",".join(tickers)})
        except httpx.HTTPError as exc:               # DNS, timeout, connection reset
            raise SourceUnavailableError(str(exc)) from exc

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            raise RateLimitedError(float(retry_after) if retry_after and retry_after.isdigit() else 60.0)
        if resp.status_code in (401, 403):
            raise SourceAuthError(f"Massive rejected the API key ({resp.status_code})")
        if resp.status_code >= 500:
            raise SourceUnavailableError(f"Massive returned {resp.status_code}")
        if resp.status_code != 200:
            raise SourceUnavailableError(f"Unexpected status {resp.status_code}: {resp.text[:200]}")

        payload = resp.json()
        if payload.get("status") not in (None, "OK", "DELAYED"):
            log.warning("Massive snapshot status=%s", payload.get("status"))
        return parse_snapshot(payload)

    async def aclose(self) -> None:
        await self._client.aclose()
```

`"DELAYED"` is the status lower tiers return; the data is still usable.

---

## 10. Market data service (poll loop, tracked set, factory)

```python
# backend/app/market_data/service.py
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable

from ..config import MarketDataSettings
from .cache import PriceCache
from .errors import RateLimitedError, SourceAuthError, UnknownTickerError
from .massive import MassiveMarketDataSource
from .models import PriceEntry, Quote
from .simulator import SimulatedMarketDataSource
from .source import MarketDataSource, normalize_ticker

log = logging.getLogger(__name__)


class MarketDataService:
    """Owns the background poll task and the set of tracked tickers.

    tracked = watchlist ∪ tickers with an open position. The watchlist and
    portfolio modules call track()/untrack(); the service never reads the DB.
    """

    def __init__(self, source: MarketDataSource, cache: PriceCache, *, max_backoff: float = 60.0) -> None:
        self.source = source
        self.cache = cache
        self._max_backoff = max_backoff
        self._tracked: set[str] = set()
        self._task: asyncio.Task | None = None
        self._last_poll_at: float = 0.0
        self._last_error: str | None = None
        self._poll_count: int = 0

    # ---- lifecycle --------------------------------------------------------------

    async def start(self, initial_tickers: Iterable[str]) -> None:
        self._tracked = {normalize_ticker(t) for t in initial_tickers}
        await self._poll()      # prime the cache; raises SourceAuthError on a bad key
        self._task = asyncio.create_task(self._run(), name="market-data-poll")
        log.info("market data started: source=%s tracked=%d", self.source.name, len(self._tracked))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.source.aclose()

    async def _run(self) -> None:
        backoff = 0.0
        while True:
            interval = backoff or self.source.poll_interval
            await asyncio.sleep(max(0.0, self._last_poll_at + interval - time.time()))
            try:
                await self._poll()
                backoff = 0.0
            except asyncio.CancelledError:
                raise
            except RateLimitedError as exc:
                backoff = min(max(exc.retry_after, interval * 2), self._max_backoff)
                self._note_error(exc, backoff)
            except Exception as exc:  # noqa: BLE001 — the loop must never die
                backoff = min((backoff or interval) * 2, self._max_backoff)
                self._note_error(exc, backoff)

    def _note_error(self, exc: Exception, backoff: float) -> None:
        self._last_error = f"{type(exc).__name__}: {exc}"
        self._last_poll_at = time.time()
        log.warning("market data poll failed (%s); retrying in %.1fs", self._last_error, backoff)

    async def _poll(self, extra: Iterable[str] = ()) -> dict[str, Quote]:
        tickers = sorted(self._tracked | set(extra))
        if not tickers:
            self._last_poll_at = time.time()
            return {}
        quotes = await self.source.fetch(tickers)
        self.cache.update(quotes.values())
        self._last_poll_at = time.time()
        self._last_error = None
        self._poll_count += 1
        return quotes

    # ---- ticker management ----------------------------------------------------

    @property
    def tracked(self) -> frozenset[str]:
        return frozenset(self._tracked)

    async def track(self, raw_ticker: str) -> PriceEntry:
        """Start tracking a ticker and return its current price entry.

        Validates against the source. For Massive this costs one API call, but
        it refreshes every other tracked ticker at the same time (one snapshot
        request) and resets the poll timer, so the rate budget is unaffected.
        """
        ticker = normalize_ticker(raw_ticker)
        if ticker in self._tracked and (entry := self.cache.get(ticker)):
            return entry
        quotes = await self._poll(extra=[ticker])
        if ticker not in quotes:
            raise UnknownTickerError(ticker)
        self._tracked.add(ticker)
        return self.cache.get(ticker)  # type: ignore[return-value]  # just written

    def untrack(self, raw_ticker: str) -> None:
        """Stop tracking. Caller must ensure the ticker is in neither the
        watchlist nor the positions table (see §11.1)."""
        ticker = raw_ticker.strip().upper()
        self._tracked.discard(ticker)
        self.cache.remove(ticker)

    # ---- price access ----------------------------------------------------------

    def get_price(self, ticker: str) -> float | None:
        return self.cache.price(ticker.strip().upper())

    async def ensure_price(self, ticker: str) -> float:
        """Price for a trade fill; tracks the ticker if needed.
        Raises UnknownTickerError for symbols the source does not know."""
        entry = await self.track(ticker)
        return entry.price

    # ---- diagnostics ------------------------------------------------------------

    def status(self) -> dict:
        return {
            "source": self.source.name,
            "poll_interval": self.source.poll_interval,
            "tracked": sorted(self._tracked),
            "cached": len(self.cache),
            "cache_version": self.cache.version,
            "polls": self._poll_count,
            "last_poll_at": self._last_poll_at or None,
            "last_error": self._last_error,
            "running": bool(self._task and not self._task.done()),
        }
```

### 10.1 Factory with simulator fallback

```python
# backend/app/market_data/service.py (continued)
def build_source(settings: MarketDataSettings) -> MarketDataSource:
    if settings.use_massive:
        return MassiveMarketDataSource(
            settings.massive_api_key,
            base_url=settings.massive_base_url,
            poll_interval=settings.massive_poll_interval,
        )
    return SimulatedMarketDataSource(
        tick_interval=settings.sim_tick_interval,
        time_scale=settings.sim_time_scale,
        seed=settings.sim_seed,
        event_prob=settings.sim_event_prob,
    )


async def build_market_data_service(
    settings: MarketDataSettings,
    initial_tickers: Iterable[str],
) -> MarketDataService:
    """Create, start and return the service. If Massive rejects the key at
    startup and fallback is enabled, run the simulator instead so the UI is
    never dead because of a typo in .env."""
    initial = list(initial_tickers)
    service = MarketDataService(build_source(settings), PriceCache())
    try:
        await service.start(initial)
        return service
    except SourceAuthError as exc:
        await service.stop()
        if not (settings.use_massive and settings.massive_fallback_to_sim):
            raise
        log.error("Massive auth failed (%s); falling back to the simulator", exc)
        fallback = MarketDataService(
            SimulatedMarketDataSource(
                tick_interval=settings.sim_tick_interval,
                time_scale=settings.sim_time_scale,
                seed=settings.sim_seed,
                event_prob=settings.sim_event_prob,
            ),
            PriceCache(),
        )
        await fallback.start(initial)
        return fallback
```

Transient failures at startup (DNS, 5xx) are *not* caught here: `start()`'s
priming poll raises `SourceUnavailableError`, which the lifespan treats the
same way, so the app still boots and the loop retries with backoff. Concretely,
`start()` should wrap the priming call:

```python
class MarketDataService:  # revised start(); replaces the version in §10
    async def start(self, initial_tickers: Iterable[str]) -> None:
        self._tracked = {normalize_ticker(t) for t in initial_tickers}
        try:
            await self._poll()
        except SourceAuthError:
            raise                               # let the factory decide
        except Exception as exc:  # noqa: BLE001
            self._note_error(exc, self.source.poll_interval)   # loop will retry
        self._task = asyncio.create_task(self._run(), name="market-data-poll")
```

### 10.2 FastAPI wiring

```python
# backend/app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from .config import get_market_data_settings
from .db import get_db, init_db                       # owned by the DB design
from .market_data import MarketDataService, build_market_data_service
from .market_data.sse import router as stream_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()                                          # lazy schema + seed (PLAN.md §7)
    db = get_db()
    initial = set(db.watchlist_tickers()) | set(db.position_tickers())
    app.state.market = await build_market_data_service(get_market_data_settings(), initial)
    # The 30-second portfolio snapshot task is started here too (portfolio design).
    try:
        yield
    finally:
        await app.state.market.stop()


app = FastAPI(title="FinAlly", lifespan=lifespan)
app.include_router(stream_router)
# ... portfolio, watchlist, chat, health routers ...
app.mount("/", StaticFiles(directory="static", html=True), name="frontend")   # last


def get_market(request: Request) -> MarketDataService:
    """FastAPI dependency used by every router that needs prices."""
    return request.app.state.market
```

Using `app.state` rather than a module-level singleton is what lets tests spin
up an app with a seeded simulator and tear it down cleanly.

---

## 11. SSE stream

### 11.1 Wire format

`GET /api/stream/prices` → `text/event-stream`. Two event types:

```
retry: 2000

event: snapshot
data: {"source":"simulator","ts":1760000000.512,"ticks":[{"ticker":"AAPL","price":190.12,"prev_price":190.12,"prev_close":190.0,"change":0.12,"change_pct":0.0632,"direction":"flat","timestamp":1760000000.5}, ...all tracked tickers...]}

event: prices
data: {"source":"simulator","ts":1760000001.013,"ticks":[{"ticker":"AAPL","price":190.21,"prev_price":190.12,"prev_close":190.0,"change":0.21,"change_pct":0.1105,"direction":"up","timestamp":1760000001.0},{"ticker":"NVDA",...}]}

: keepalive

event: prices
data: ...
```

- `snapshot` is sent once per connection (including every reconnect) and
  contains **all** tracked tickers. The client replaces its price map.
- `prices` carries only tickers whose price changed since the client's last
  event. The client merges. With the simulator this is usually all 10 every
  500 ms; with Massive it is a burst every 15 s during market hours and
  nothing (just keep-alives) when the market is closed.
- Each tick object has exactly the fields `PriceEntry.to_dict()` produces:
  `ticker, price, prev_price, prev_close, change, change_pct, direction,
  timestamp`. `PLAN.md` §6 requires ticker / price / previous price /
  timestamp / direction; the extra three save the frontend from recomputing.
- `retry: 2000` tells `EventSource` to reconnect after 2 s. Keep-alive comments
  every 15 s stop proxies and browsers from timing out an idle stream.
- One event per batch (not per ticker) means one React state update per tick,
  which matters at 20 tickers × 2 Hz.

### 11.2 Implementation

```python
# backend/app/market_data/sse.py
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..config import MarketDataSettings, get_market_data_settings
from .service import MarketDataService

router = APIRouter(prefix="/api/stream", tags=["stream"])


def format_sse(data: dict, event: str | None = None) -> str:
    lines = []
    if event:
        lines.append(f"event: {event}")
    lines.append("data: " + json.dumps(data, separators=(",", ":")))
    return "\n".join(lines) + "\n\n"


def _get_market(request: Request) -> MarketDataService:
    return request.app.state.market


async def price_events(
    request: Request,
    market: MarketDataService,
    settings: MarketDataSettings,
) -> AsyncIterator[str]:
    cache = market.cache
    yield "retry: 2000\n\n"

    # Full state first so a (re)connecting client never starts from nothing.
    last_version = cache.version
    yield format_sse(
        {"source": market.source.name, "ts": time.time(), "ticks": [e.to_dict() for e in cache.snapshot()]},
        event="snapshot",
    )
    last_sent = time.monotonic()

    while True:
        if await request.is_disconnected():
            return
        await asyncio.sleep(settings.sse_push_interval)

        if cache.version != last_version:
            changed = cache.changed_since(last_version)
            last_version = cache.version
            if changed:
                yield format_sse(
                    {"source": market.source.name, "ts": time.time(), "ticks": [e.to_dict() for e in changed]},
                    event="prices",
                )
                last_sent = time.monotonic()
                continue

        if time.monotonic() - last_sent >= settings.sse_keepalive_interval:
            yield ": keepalive\n\n"
            last_sent = time.monotonic()


@router.get("/prices")
async def stream_prices(
    request: Request,
    market: MarketDataService = Depends(_get_market),
    settings: MarketDataSettings = Depends(get_market_data_settings),
) -> StreamingResponse:
    return StreamingResponse(
        price_events(request, market, settings),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",     # disable buffering if ever placed behind nginx
        },
    )
```

Notes:

- `cache.version != last_version` is an O(1) check; `changed_since()` is O(N)
  over ≤ a few dozen tickers. No per-client queues, no fan-out bookkeeping:
  N clients cost N tiny loops.
- A ticker that was untracked disappears from the cache; the client sees no
  further events for it and the watchlist DELETE response is what removes the
  row from the UI. No tombstone event is needed.
- `request.is_disconnected()` plus the 0.5 s sleep means a closed tab is
  noticed within a second and the generator exits. Uvicorn also cancels the
  task on client disconnect.
- The hand-rolled formatter is ~10 lines; `sse-starlette` would also work but
  adds a dependency for no gain here.

### 11.3 Frontend contract

```ts
// frontend/src/lib/prices.ts
export type Direction = "up" | "down" | "flat";

export interface PriceTick {
  ticker: string;
  price: number;
  prev_price: number;   // for the green/red flash
  prev_close: number;   // for the daily change column
  change: number;
  change_pct: number;
  direction: Direction;
  timestamp: number;    // unix seconds
}

export interface PricesEvent {
  source: "simulator" | "massive";
  ts: number;
  ticks: PriceTick[];
}

export type ConnectionState = "connected" | "reconnecting" | "disconnected";

export function connectPrices(
  onSnapshot: (ev: PricesEvent) => void,
  onPrices: (ev: PricesEvent) => void,
  onState: (s: ConnectionState) => void,
): () => void {
  const es = new EventSource("/api/stream/prices");
  es.onopen = () => onState("connected");
  es.onerror = () =>
    onState(es.readyState === EventSource.CLOSED ? "disconnected" : "reconnecting");
  es.addEventListener("snapshot", (e) => onSnapshot(JSON.parse((e as MessageEvent).data)));
  es.addEventListener("prices", (e) => onPrices(JSON.parse((e as MessageEvent).data)));
  return () => es.close();
}
```

Sparklines: append `tick.price` to a per-ticker ring buffer (e.g. last 300
points) on every `prices` event; reset the buffer on `snapshot` only if the
ticker is new. The detailed chart uses the same buffer at full resolution.

---

## 12. Integration points with the rest of the backend

### 12.1 Watchlist routes

```python
# backend/app/watchlist/routes.py (relevant parts)
from fastapi import APIRouter, Depends, HTTPException

from ..market_data import MarketDataService, UnknownTickerError
from ..main import get_market

router = APIRouter(prefix="/api/watchlist")


@router.get("")
async def list_watchlist(db=Depends(get_db), market: MarketDataService = Depends(get_market)):
    rows = db.watchlist_rows()                      # [{ticker, added_at}, ...]
    return [
        {**row, "quote": (e.to_dict() if (e := market.cache.get(row["ticker"])) else None)}
        for row in rows
    ]


@router.post("", status_code=201)
async def add_to_watchlist(body: AddTickerBody, db=Depends(get_db), market: MarketDataService = Depends(get_market)):
    try:
        entry = await market.track(body.ticker)     # validates + primes the cache
    except UnknownTickerError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    db.watchlist_add(entry.ticker)                  # idempotent on UNIQUE(user_id, ticker)
    return {"ticker": entry.ticker, "quote": entry.to_dict()}


@router.delete("/{ticker}", status_code=204)
async def remove_from_watchlist(ticker: str, db=Depends(get_db), market: MarketDataService = Depends(get_market)):
    t = ticker.strip().upper()
    db.watchlist_remove(t)
    if not db.position_exists(t):                   # still need its price if we hold it
        market.untrack(t)
```

The chat module's `watchlist_changes` executor calls the same two functions,
so a typo from the LLM (`"ticker": "APPL"`) surfaces as a per-action error in
the chat response rather than a dead row.

### 12.2 Trade execution

```python
# backend/app/portfolio/service.py (relevant part)
async def execute_trade(db, market: MarketDataService, ticker: str, side: str, quantity: float) -> Trade:
    try:
        price = await market.ensure_price(ticker)   # tracks if needed; raises for unknown symbol
    except UnknownTickerError as exc:
        raise TradeError(str(exc))
    # ... cash / position validation, write trades + positions rows, snapshot ...
```

A buy of a ticker that is not on the watchlist starts tracking it, so the
position is marked to market from the first SSE event after the fill. Selling
to zero does not untrack by itself; the watchlist DELETE handler's check above
is the only place `untrack()` is called, which keeps the rule in one spot.

### 12.3 Portfolio snapshot task (every 30 s)

```python
async def snapshot_loop(db, market: MarketDataService, interval: float = 30.0) -> None:
    while True:
        prices = market.cache.prices()
        total = db.cash_balance() + sum(
            pos.quantity * prices.get(pos.ticker, pos.avg_cost) for pos in db.positions()
        )
        db.insert_snapshot(total)
        await asyncio.sleep(interval)
```

Falling back to `avg_cost` when a price is missing (Massive before its first
poll) keeps the P&L chart continuous instead of dipping to cash-only.

### 12.4 Health

```python
@router.get("/api/health")
async def health(market: MarketDataService = Depends(get_market)):
    return {"status": "ok", "market_data": market.status()}
```

The E2E suite and the Docker `HEALTHCHECK` both read this; `status()` exposes
`source`, `last_error`, and `polls` so a mis-set Massive key is diagnosable
without reading logs.

### 12.5 Sequence: user adds a ticker via chat

```
Browser ──POST /api/chat {"message":"add PYPL and buy 5"}──▶ chat router
   chat router ──▶ LLM (structured output) ──▶ {watchlist_changes:[{PYPL,add}], trades:[{PYPL,buy,5}]}
   chat router ──▶ market.track("PYPL")
                     └─▶ source.fetch([AAPL,...,NFLX,PYPL])   # one call, refreshes everything
                     └─▶ cache.update(...)  version 1041 → 1052
   chat router ──▶ db.watchlist_add("PYPL")
   chat router ──▶ execute_trade(PYPL, buy, 5) ──▶ market.ensure_price("PYPL") (cache hit)
   chat router ◀── {message, actions:[...]}
Browser ◀── 200 JSON
Browser ◀── SSE "prices" event ≤500 ms later includes PYPL (version > client's last)
```

---

## 13. Testing

All tests are offline. `pytest-asyncio` in auto mode (`asyncio_mode = "auto"`
in `pyproject.toml`).

### 13.1 Fixtures

```python
# backend/tests/market_data/conftest.py
import json

import httpx
import pytest

from app.market_data.cache import PriceCache
from app.market_data.massive import MassiveMarketDataSource
from app.market_data.service import MarketDataService
from app.market_data.simulator import SimulatedMarketDataSource

SNAPSHOT_FIXTURE = {
    "status": "OK",
    "count": 2,
    "tickers": [
        {
            "ticker": "AAPL",
            "updated": 1_760_000_000_123_456_789,
            "day": {"o": 189.9, "h": 191.4, "l": 189.1, "c": 190.6, "v": 1},
            "min": {"t": 1_760_000_000_000, "c": 190.55},
            "prevDay": {"c": 189.4},
            "lastTrade": {"p": 190.61, "t": 1_760_000_000_123_456_789},
        },
        {   # Starter-tier shape: no lastTrade/lastQuote
            "ticker": "MSFT",
            "updated": 1_760_000_000_000_000_000,
            "min": {"t": 1_760_000_000_000, "c": 420.10},
            "prevDay": {"c": 418.0},
        },
    ],
}


@pytest.fixture
def sim() -> SimulatedMarketDataSource:
    return SimulatedMarketDataSource(seed=42)


def mock_massive(handler) -> MassiveMarketDataSource:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(base_url="https://api.massive.test", transport=transport)
    return MassiveMarketDataSource("test-key", poll_interval=0.01, client=client)


@pytest.fixture
def massive_ok() -> MassiveMarketDataSource:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        requested = request.url.params["tickers"].split(",")
        payload = {**SNAPSHOT_FIXTURE, "tickers": [t for t in SNAPSHOT_FIXTURE["tickers"] if t["ticker"] in requested]}
        return httpx.Response(200, json=payload)
    return mock_massive(handler)


@pytest.fixture
async def sim_service(sim) -> MarketDataService:
    service = MarketDataService(sim, PriceCache())
    await service.start(["AAPL", "MSFT"])
    yield service
    await service.stop()
```

### 13.2 Simulator

```python
# backend/tests/market_data/test_simulator.py
import math
import statistics

from app.market_data.simulator import SimulatedMarketDataSource, PROFILES, synthetic_profile

TICKERS = ["AAPL", "GOOGL", "MSFT", "JPM", "V"]


async def test_deterministic_under_seed():
    a, b = SimulatedMarketDataSource(seed=7), SimulatedMarketDataSource(seed=7)
    for _ in range(50):
        qa, qb = await a.fetch(TICKERS), await b.fetch(TICKERS)
        assert {t: q.price for t, q in qa.items()} == {t: q.price for t, q in qb.items()}


async def test_prices_positive_and_near_seed(sim):
    for _ in range(2000):
        quotes = await sim.fetch(TICKERS)
        for t, q in quotes.items():
            assert q.price > 0
            assert 0.5 < q.price / PROFILES[t].seed_price < 2.0   # reversion keeps it bounded


async def test_prev_close_is_seed_price(sim):
    q = (await sim.fetch(["AAPL"]))["AAPL"]
    assert q.prev_close == PROFILES["AAPL"].seed_price


async def test_tick_volatility_matches_parameters():
    src = SimulatedMarketDataSource(seed=1, event_prob=0.0, time_scale=60.0, tick_interval=0.5)
    log_returns, prev = [], None
    for _ in range(5000):
        p = (await src.fetch(["KO"]))["KO"].price          # KO: vol 0.15, low beta
        if prev:
            log_returns.append(math.log(p / prev))
        prev = p
    expected = 0.15 * math.sqrt(0.5 * 60 / (252 * 6.5 * 3600))
    observed = statistics.pstdev(log_returns)
    # Rounding to cents adds noise on a $62 stock; allow a wide band.
    assert 0.5 * expected < observed < 2.0 * expected


async def test_sector_correlation():
    src = SimulatedMarketDataSource(seed=3, event_prob=0.0)
    a, g = [], []
    prev_a = prev_g = None
    for _ in range(3000):
        q = await src.fetch(["AAPL", "GOOGL"])
        if prev_a:
            a.append(math.log(q["AAPL"].price / prev_a))
            g.append(math.log(q["GOOGL"].price / prev_g))
        prev_a, prev_g = q["AAPL"].price, q["GOOGL"].price
    assert statistics.correlation(a, g) > 0.3


async def test_events_produce_2_to_5_percent_moves():
    src = SimulatedMarketDataSource(seed=11, event_prob=1.0, event_ticks=1, time_scale=1.0)
    before = (await src.fetch(["AAPL"]))["AAPL"].price
    after = (await src.fetch(["AAPL"]))["AAPL"].price
    assert 0.015 < abs(after / before - 1) < 0.06


def test_synthetic_profile_is_stable_and_in_range():
    p1, p2 = synthetic_profile("ZZZT"), synthetic_profile("ZZZT")
    assert p1 == p2
    assert 20.0 <= p1.seed_price < 500.0


async def test_validate_accepts_unknown_but_well_formed(sim):
    q = await sim.validate("ZZZT")
    assert q.ticker == "ZZZT" and q.price > 0


async def test_empty_fetch_is_noop(sim):
    assert await sim.fetch([]) == {}
```

### 13.3 Massive parser and client

```python
# backend/tests/market_data/test_massive.py
import httpx
import pytest

from app.market_data.errors import RateLimitedError, SourceAuthError, SourceUnavailableError, UnknownTickerError
from app.market_data.massive import parse_snapshot, parse_ticker_item
from .conftest import SNAPSHOT_FIXTURE, mock_massive


def test_parse_prefers_last_trade_then_minute_bar():
    quotes = parse_snapshot(SNAPSHOT_FIXTURE)
    assert quotes["AAPL"].price == 190.61            # lastTrade.p
    assert quotes["AAPL"].prev_close == 189.4
    assert abs(quotes["AAPL"].timestamp - 1_760_000_000.123456789) < 1e-3   # ns -> s
    assert quotes["MSFT"].price == 420.10            # min.c (no lastTrade on lower tiers)
    assert abs(quotes["MSFT"].timestamp - 1_760_000_000.0) < 1e-6           # ms -> s


def test_parse_premarket_falls_back_to_prev_close():
    item = {"ticker": "AAPL", "day": {}, "min": {}, "prevDay": {"c": 189.4}}
    q = parse_ticker_item(item)
    assert q.price == 189.4 and q.prev_close == 189.4


def test_parse_skips_garbage():
    assert parse_snapshot({"tickers": [None, {}, {"ticker": "X"}, {"ticker": "Y", "day": {"c": 0}}]}) == {}
    assert parse_snapshot({}) == {}


async def test_fetch_sends_tickers_and_bearer(massive_ok):
    quotes = await massive_ok.fetch(["AAPL", "MSFT"])
    assert set(quotes) == {"AAPL", "MSFT"}


async def test_unknown_ticker_absent_then_validate_raises(massive_ok):
    assert "NOPE" not in await massive_ok.fetch(["AAPL", "NOPE"])
    with pytest.raises(UnknownTickerError):
        await massive_ok.validate("NOPE")


@pytest.mark.parametrize(
    "status,headers,exc",
    [
        (429, {"Retry-After": "30"}, RateLimitedError),
        (401, {}, SourceAuthError),
        (403, {}, SourceAuthError),
        (503, {}, SourceUnavailableError),
    ],
)
async def test_http_errors_map_to_exceptions(status, headers, exc):
    src = mock_massive(lambda r: httpx.Response(status, headers=headers, json={}))
    with pytest.raises(exc) as info:
        await src.fetch(["AAPL"])
    if exc is RateLimitedError:
        assert info.value.retry_after == 30.0


async def test_transport_error_is_unavailable():
    def boom(request):
        raise httpx.ConnectError("dns", request=request)
    with pytest.raises(SourceUnavailableError):
        await mock_massive(boom).fetch(["AAPL"])
```

### 13.4 Cache and service

```python
# backend/tests/market_data/test_cache.py
from app.market_data.cache import PriceCache
from app.market_data.models import Quote


def test_update_tracks_direction_and_version():
    c = PriceCache()
    assert c.update([Quote("AAPL", 100.0, 99.0, 1.0)]) == ["AAPL"]
    assert c.version == 1 and c.get("AAPL").direction == "flat"
    assert c.update([Quote("AAPL", 101.0, 99.0, 2.0)]) == ["AAPL"]
    e = c.get("AAPL")
    assert (e.price, e.prev_price, e.direction, e.version) == (101.0, 100.0, "up", 2)
    assert c.update([Quote("AAPL", 101.0, 99.0, 3.0)]) == []      # same price: no bump
    assert c.version == 2 and e.timestamp == 3.0
    assert c.changed_since(1) == [e] and c.changed_since(2) == []


def test_change_pct_uses_prev_close():
    c = PriceCache()
    c.update([Quote("X", 110.0, 100.0, 0.0)])
    assert c.get("X").change_pct == 10.0 and c.get("X").change == 10.0
```

```python
# backend/tests/market_data/test_service.py
import asyncio

import pytest

from app.market_data.errors import UnknownTickerError


async def test_start_primes_cache_and_loop_advances(sim_service):
    assert sim_service.get_price("AAPL") is not None
    v0 = sim_service.cache.version
    await asyncio.sleep(1.2)                  # > 2 ticks at 0.5 s
    assert sim_service.cache.version > v0


async def test_track_and_untrack(sim_service):
    entry = await sim_service.track("pypl")   # normalised
    assert entry.ticker == "PYPL" and "PYPL" in sim_service.tracked
    sim_service.untrack("PYPL")
    assert "PYPL" not in sim_service.tracked and sim_service.get_price("PYPL") is None


async def test_track_rejects_malformed(sim_service):
    with pytest.raises(UnknownTickerError):
        await sim_service.track("not a ticker")


async def test_loop_survives_source_errors(monkeypatch, sim_service):
    calls = {"n": 0}
    real_fetch = sim_service.source.fetch

    async def flaky(tickers):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return await real_fetch(tickers)

    monkeypatch.setattr(sim_service.source, "fetch", flaky)
    await asyncio.sleep(2.5)
    assert calls["n"] >= 2                                   # it retried
    assert sim_service.status()["last_error"] is None        # and recovered
```

### 13.5 Interface conformance (both sources, same assertions)

```python
# backend/tests/market_data/test_interface.py
import pytest

from app.market_data.models import Quote
from app.market_data.source import MarketDataSource


@pytest.fixture(params=["sim", "massive_ok"])
def source(request) -> MarketDataSource:
    return request.getfixturevalue(request.param)


async def test_contract(source: MarketDataSource):
    assert isinstance(source.name, str) and source.poll_interval > 0
    assert await source.fetch([]) == {}
    quotes = await source.fetch(["AAPL", "MSFT"])
    assert set(quotes) == {"AAPL", "MSFT"}
    for t, q in quotes.items():
        assert isinstance(q, Quote) and q.ticker == t
        assert q.price > 0 and q.prev_close > 0 and q.timestamp > 1_600_000_000
    assert (await source.validate("AAPL")).ticker == "AAPL"
    await source.aclose()
```

### 13.6 SSE endpoint

```python
# backend/tests/market_data/test_sse.py
import json

import httpx
import pytest
from fastapi import FastAPI

from app.config import MarketDataSettings
from app.market_data.cache import PriceCache
from app.market_data.service import MarketDataService
from app.market_data.simulator import SimulatedMarketDataSource
from app.market_data.sse import router
from app.config import get_market_data_settings


def _parse_events(raw: str) -> list[tuple[str, dict]]:
    events = []
    for block in raw.strip().split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:])
        if name and data is not None:
            events.append((name, data))
    return events


@pytest.fixture
async def app():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_market_data_settings] = lambda: MarketDataSettings(
        sim_seed=1, sse_push_interval=0.05
    )
    service = MarketDataService(SimulatedMarketDataSource(seed=1, tick_interval=0.05), PriceCache())
    await service.start(["AAPL", "MSFT"])
    app.state.market = service
    yield app
    await service.stop()


async def test_snapshot_then_deltas(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("GET", "/api/stream/prices") as resp:
            assert resp.headers["content-type"].startswith("text/event-stream")
            buf = ""
            async for chunk in resp.aiter_text():
                buf += chunk
                if buf.count("\n\n") >= 4:       # retry + snapshot + >=2 price events
                    break
    events = _parse_events(buf)
    assert events[0][0] == "snapshot"
    assert {t["ticker"] for t in events[0][1]["ticks"]} == {"AAPL", "MSFT"}
    assert events[1][0] == "prices"
    tick = events[1][1]["ticks"][0]
    assert set(tick) == {"ticker", "price", "prev_price", "prev_close", "change", "change_pct", "direction", "timestamp"}
    assert tick["direction"] in {"up", "down", "flat"}
```

### 13.7 E2E hooks

For Playwright (`test/`), run the app with `SIM_SEED=1 SIM_TICK_INTERVAL=0.25`
so prices visibly move within the first second and the "prices are streaming"
assertion (watch a cell's text change) is reliable. The "SSE resilience"
scenario can use `page.route('/api/stream/prices', r => r.abort())` for a few
seconds, then un-route and assert the header dot goes yellow → green.

---

## 14. Operational notes

- **Logging.** The service logs one line at startup (`source=`, tracked
  count) and one `WARNING` per failed poll with the backoff. Successful polls
  are silent; `/api/health` is the place to look.
- **Memory.** The cache holds one `PriceEntry` per tracked ticker. Even 500
  tickers is a few hundred KB. There is no tick history on the server.
- **Clock.** All timestamps are unix seconds, UTC, as floats. The frontend
  formats in local time.
- **Market closed with Massive.** Prices freeze, the SSE stream sends only
  keep-alives, and the UI's last-update timestamp is the tell. Nothing to do.
- **Switching sources** requires a restart: `MASSIVE_API_KEY` is read once at
  startup. Positions and watchlist survive the switch (they are in SQLite),
  but the simulator will price AAPL at ~$190 regardless of what Massive said,
  so P&L jumps. This is accepted for a simulated-money tool.
- **Multi-user later.** `tracked` becomes the union over all users' watchlists
  and positions; the cache and SSE loop need no change. `track()`/`untrack()`
  would gain reference counting. Nothing in this design blocks that.

---

## 15. Decision log

| Decision | Alternative considered | Why this one |
|---|---|---|
| Full ticker list on every `fetch()` | Per-ticker `get_quote()` | One snapshot call for N tickers is how Massive is priced; the simulator also wants one correlated step for all names |
| Unknown tickers are absent, not raised | Raise on any unknown | A single bad symbol must not stop updates for the rest |
| Version counter on the cache | Per-client asyncio queues | Zero fan-out bookkeeping; late/slow clients can never back-pressure the poll loop |
| `snapshot` + `prices` events | One event type | Makes "replace" vs "merge" explicit on the client; cheap to implement |
| Batch ticks per event | One event per ticker | One render per tick; fewer parsed messages |
| `prev_close` in the model | Compute day change on the frontend from first-seen price | The watchlist's "daily change %" would otherwise be change-since-page-load |
| Mean reversion in the simulator | Pure GBM | Pure GBM wanders unboundedly over multi-day runs; a 30-minute half-life is invisible short-term and keeps prices sane long-term |
| Jumps spread over 4 ticks | Instant jump | Several same-direction flashes read as "news" in the UI |
| Simulator fallback on Massive auth failure | Fail to start | A typo in `.env` should not produce a dead dashboard |
| Hand-rolled SSE formatter | `sse-starlette` | 10 lines vs a dependency; full control over keep-alive and headers |
| No numpy | numpy GBM vectorisation | ≤ 50 tickers at 2 Hz is nothing; stdlib keeps the image small and seeding trivial |

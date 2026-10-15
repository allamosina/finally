# Market Simulator

Design and code structure for FinAlly's built-in price simulator: the default `MarketDataSource` used whenever `MASSIVE_API_KEY` is not set, and the only source exercised in CI. It must look alive, be cheap, be deterministic when asked, and conform to the interface in [MARKET_INTERFACE.md](MARKET_INTERFACE.md).

---

## 1. Requirements (from PLAN.md §6 and the reviews)

- Geometric Brownian motion (GBM) per ticker with per-ticker drift and volatility.
- Ticks every ~500 ms; all tickers move in one batch so the SSE stream emits one event per tick.
- Seed table of ~30 well-known tickers with realistic prices. Unknown tickers get a **stable** pseudo-random seed in $20–$400 derived from a cryptographic hash (not Python's `hash()`, which is salted per process).
- `session_open` = seed price at process start. Restarts reset prices; accepted.
- Any valid ticker can be priced immediately on demand (`prime()`), so buying an unwatched symbol works.
- Optional reproducibility via `SIM_SEED` for tests.
- Second pass, not core: sector correlation and occasional 2–5% "event" jumps.

---

## 2. The math

GBM in discrete time:

```
S(t+Δt) = S(t) · exp( (μ − σ²/2)·Δt + σ·√Δt·Z ),   Z ~ N(0, 1)
```

We parametrize **per tick**, not per year. A real annualized σ of 25% over a 500 ms tick is ~0.007% per tick, which is invisible on a chart for minutes. A demo needs motion the eye can see within seconds but that does not blow up over an hour. So each ticker carries:

| Parameter | Meaning | Typical value |
|---|---|---|
| `mu_tick` | drift per tick (log-return) | `0.0` to `±2e-6` (effectively zero; slight bias for "story") |
| `sigma_tick` | volatility per tick (std of log-return) | `0.0003` (calm) … `0.0012` (wild) |

Resulting visible behavior with `sigma_tick = 0.0005` (7,200 ticks/hour):

| Horizon | Std dev of % move |
|---|---|
| 1 tick | 0.05% |
| 1 min (120 ticks) | 0.55% |
| 5 min (600 ticks) | 1.2% |
| 1 hour | 4.2% |

That is far more volatile than a real large-cap but reads as "a lively tape". Tune `sigma_tick`, nothing else, if it feels wrong.

Implementation of one step:

```python
import math

def gbm_step(price: float, mu: float, sigma: float, z: float) -> float:
    return price * math.exp((mu - 0.5 * sigma * sigma) + sigma * z)
```

`Δt` is folded into `mu` and `sigma` (both already per tick), so it disappears from the formula. Prices are clamped to a floor of `0.01` after each step; GBM cannot cross zero mathematically, but float rounding and the floor keep the UI sane.

Optional mild mean reversion toward the seed keeps a 2-hour demo from drifting a ticker to 3× its seed. Add a pull term before the exponent:

```
mu_eff = mu_tick − κ · ln(S / S_seed),   κ ≈ 1e-4 per tick
```

With `κ = 1e-4` the half-life of a deviation is ~6,900 ticks (~58 min). It is subtle enough not to look fake. On by default; `kappa=0` turns it off.

---

## 3. Seed table

`backend/app/market/seeds.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class SeedSpec:
    price: float
    sigma_tick: float
    mu_tick: float = 0.0
    sector: str = "other"


SEEDS: dict[str, SeedSpec] = {
    # ticker : price,   sigma,   mu,      sector
    "AAPL":  SeedSpec(190.0,  0.0004, 0.0,    "tech"),
    "MSFT":  SeedSpec(415.0,  0.0004, 0.0,    "tech"),
    "GOOGL": SeedSpec(175.0,  0.0005, 0.0,    "tech"),
    "AMZN":  SeedSpec(185.0,  0.0005, 0.0,    "tech"),
    "META":  SeedSpec(500.0,  0.0006, 0.0,    "tech"),
    "NVDA":  SeedSpec(880.0,  0.0009, 1e-6,   "semis"),
    "AMD":   SeedSpec(160.0,  0.0009, 0.0,    "semis"),
    "INTC":  SeedSpec(31.0,   0.0007, -1e-6,  "semis"),
    "TSLA":  SeedSpec(175.0,  0.0012, 0.0,    "auto"),
    "F":     SeedSpec(12.5,   0.0006, 0.0,    "auto"),
    "GM":    SeedSpec(44.0,   0.0006, 0.0,    "auto"),
    "JPM":   SeedSpec(195.0,  0.0004, 0.0,    "finance"),
    "BAC":   SeedSpec(38.0,   0.0005, 0.0,    "finance"),
    "GS":    SeedSpec(420.0,  0.0005, 0.0,    "finance"),
    "V":     SeedSpec(275.0,  0.0003, 0.0,    "finance"),
    "MA":    SeedSpec(460.0,  0.0003, 0.0,    "finance"),
    "NFLX":  SeedSpec(610.0,  0.0007, 0.0,    "media"),
    "DIS":   SeedSpec(112.0,  0.0005, 0.0,    "media"),
    "XOM":   SeedSpec(118.0,  0.0004, 0.0,    "energy"),
    "CVX":   SeedSpec(160.0,  0.0004, 0.0,    "energy"),
    "JNJ":   SeedSpec(155.0,  0.0003, 0.0,    "health"),
    "PFE":   SeedSpec(27.0,   0.0005, 0.0,    "health"),
    "UNH":   SeedSpec(500.0,  0.0004, 0.0,    "health"),
    "WMT":   SeedSpec(60.0,   0.0003, 0.0,    "retail"),
    "COST":  SeedSpec(730.0,  0.0003, 0.0,    "retail"),
    "KO":    SeedSpec(62.0,   0.0002, 0.0,    "staples"),
    "PEP":   SeedSpec(170.0,  0.0002, 0.0,    "staples"),
    "BA":    SeedSpec(180.0,  0.0008, 0.0,    "industrial"),
    "CAT":   SeedSpec(340.0,  0.0005, 0.0,    "industrial"),
    "PYPL":  SeedSpec(64.0,   0.0007, 0.0,    "fintech"),
    "COIN":  SeedSpec(210.0,  0.0014, 0.0,    "crypto"),
    "GME":   SeedSpec(25.0,   0.0015, 0.0,    "meme"),
}

DEFAULT_SIGMA = 0.0006
DEFAULT_MU = 0.0
```

Prices are plausible mid-2026 levels; exactness does not matter. Volatility classes are what give the tape its texture: `KO` barely moves, `TSLA`/`COIN`/`GME` jump around.

---

## 4. Unknown tickers: stable hashed seeds

```python
import hashlib


def hashed_seed_price(ticker: str, lo: float = 20.0, hi: float = 400.0) -> float:
    digest = hashlib.sha256(ticker.encode("ascii")).digest()
    frac = int.from_bytes(digest[:8], "big") / 2**64          # uniform in [0, 1)
    return round(lo + frac * (hi - lo), 2)


def spec_for(ticker: str) -> SeedSpec:
    return SEEDS.get(ticker) or SeedSpec(hashed_seed_price(ticker), DEFAULT_SIGMA, DEFAULT_MU)
```

SHA-256 is stable across processes, platforms and Python versions, so `XYZ` seeds at the same price every restart and in every test. Python's `hash()` is salted per process and must not be used.

---

## 5. Randomness and determinism

Each ticker gets **its own** `random.Random` instance seeded from `(SIM_SEED, ticker)`. Consequences:

- With `SIM_SEED` set, the path of `AAPL` is identical run to run **regardless of which other tickers are present or in what order they were added**. Tests can add and remove tickers without perturbing assertions on another ticker.
- Without `SIM_SEED`, each RNG is seeded from `os.urandom`, so every launch differs.

```python
import random


def rng_for(ticker: str, global_seed: int | None) -> random.Random:
    if global_seed is None:
        return random.Random()                             # os.urandom-seeded
    material = hashlib.sha256(f"{global_seed}:{ticker}".encode()).digest()
    return random.Random(int.from_bytes(material[:8], "big"))
```

`random.Random.gauss(0, 1)` is used for `Z`. The standard library is sufficient; NumPy is not a dependency of the backend and 30 Gaussians every 500 ms is nothing.

---

## 6. Code structure

```
backend/app/market/
├── simulator.py     # SimulatorSource (the MarketDataSource implementation)
├── seeds.py         # SEEDS table, hashed_seed_price(), spec_for()
└── gbm.py           # gbm_step(), rng_for(), pure functions, no asyncio
```

```python
# simulator.py
import asyncio
import logging
import math
import random
import time
from dataclasses import dataclass

from .base import MarketDataSource
from .cache import PriceCache
from .config import MarketConfig
from .gbm import gbm_step, rng_for
from .seeds import spec_for

log = logging.getLogger(__name__)
PRICE_FLOOR = 0.01


@dataclass
class _SimState:
    price: float
    seed_price: float
    mu: float
    sigma: float
    rng: random.Random


class SimulatorSource(MarketDataSource):
    name = "simulator"

    def __init__(self, cache: PriceCache, cfg: MarketConfig, kappa: float = 1e-4):
        super().__init__(cache)
        self._cfg = cfg
        self._kappa = kappa
        self._state: dict[str, _SimState] = {}
        self._tick_count = 0

    # ---- MarketDataSource hooks ------------------------------------------
    async def _fetch_now(self, tickers: set[str]) -> None:
        """Seed any unseen tickers and write their current price immediately."""
        now_ms = int(time.time() * 1000)
        ticks, opens = {}, {}
        for t in tickers:
            st = self._state.get(t) or self._seed(t)
            ticks[t] = (st.price, now_ms, "simulator")
            opens[t] = st.seed_price
        await self.cache.apply(ticks, session_open=opens)

    async def _run(self) -> None:
        interval = self._cfg.sim_tick_ms / 1000.0
        next_at = time.monotonic()
        while True:
            next_at += interval
            try:
                await self._tick()
            except Exception:                  # never let the loop die
                log.exception("simulator tick failed")
            await asyncio.sleep(max(0.0, next_at - time.monotonic()))   # drift-free cadence

    # ---- internals --------------------------------------------------------
    def _seed(self, ticker: str) -> _SimState:
        spec = spec_for(ticker)
        st = _SimState(spec.price, spec.price, spec.mu_tick, spec.sigma_tick, rng_for(ticker, self._cfg.sim_seed))
        self._state[ticker] = st
        return st

    async def _tick(self) -> None:
        if not self._tickers:
            return
        now_ms = int(time.time() * 1000)
        ticks = {}
        for t in sorted(self._tickers):              # sorted: deterministic order for tests
            st = self._state.get(t) or self._seed(t)
            mu_eff = st.mu - self._kappa * math.log(st.price / st.seed_price)
            st.price = max(PRICE_FLOOR, gbm_step(st.price, mu_eff, st.sigma, st.rng.gauss(0.0, 1.0)))
            ticks[t] = (round(st.price, 4), now_ms, "simulator")
        self._tick_count += 1
        await self.cache.apply(ticks)

    async def set_tickers(self, tickers: set[str]) -> None:
        await super().set_tickers(tickers)
        for t in list(self._state):                  # forget state for dropped tickers
            if t not in self._tickers:
                del self._state[t]

    def health(self) -> dict:
        return {**super().health(), "ticks": self._tick_count, "tick_ms": self._cfg.sim_tick_ms,
                "seeded": self._cfg.sim_seed is not None}
```

Behavioral notes:

- **One `cache.apply()` per tick** with every ticker: one SSE event per tick, as PLAN §6 requires.
- **Drift-free cadence**: the loop schedules against `monotonic()` targets, so 500 ms means 500 ms even if a tick takes 3 ms. If the event loop stalls, it catches up by skipping sleep rather than firing a burst.
- **Removed tickers lose their state.** Re-adding one re-seeds at the seed price. This matches "a ticker leaves the simulator only when it is in neither set" and keeps memory bounded.
- **Prices are rounded to 4 decimals** in the cache (internal state stays full precision), so display math is stable.
- `prime()` (inherited) calls `_fetch_now()`, which seeds and writes one tick synchronously. A buy of an unwatched ticker therefore gets a price within the same request, no waiting for the next tick.

---

## 7. Second pass (not core): correlation and events

Both are additive and change no interface.

**Sector correlation** via a one-factor model per sector. Each tick, draw one market factor `M ~ N(0,1)` and one factor per sector `F_s ~ N(0,1)` from a shared "market" RNG, then for each ticker:

```
Z = √ρ_m · M  +  √ρ_s · F_sector  +  √(1 − ρ_m − ρ_s) · ε,   ε ~ N(0,1) from the ticker's own RNG
```

with `ρ_m ≈ 0.3`, `ρ_s ≈ 0.3`. Tech names then rise and fall together, which makes the heatmap look like a real market. Determinism holds as long as the market RNG is seeded from `SIM_SEED` too; tickers' own paths are no longer independent of the set, so tests that depend on exact per-ticker paths should set `rho=0`.

**Events**: each ticker has a small per-tick probability `p_event ≈ 1/36000` (about one per 5 hours per ticker, so a 10-ticker board sees one every ~30 min) of a jump. On an event, multiply the price by `exp(±u)` with `u ~ U(0.02, 0.05)`, sign random, and log `"event: NVDA +3.8%"`. The jump passes through the normal `apply()` path, so the UI flashes hard once and the sparkline shows a step. Mean reversion will slowly pull it back, which is fine.

Both are controlled by `MarketConfig` fields (`sim_rho_market`, `sim_rho_sector`, `sim_event_rate`) defaulting to off, and can be enabled in the demo `.env` once the core is stable.

---

## 8. Tests (`backend/tests/market/test_simulator.py`)

Pure-function tests (no asyncio, fast):

- `gbm_step` with `sigma=0, mu=0` returns the same price; with `mu=ln(2)` doubles it; with `z=0` moves by exactly `exp(mu − σ²/2)`.
- Statistical sanity: 20,000 steps with `mu=0, sigma=0.0005`: mean log-return within `±3·σ/√n` of `−σ²/2`, sample std within 5% of `σ`.
- `hashed_seed_price("XYZ")` is in `[20, 400]`, equal across two separate Python processes (spawn a subprocess and compare), and different for `"XYZ"` vs `"XYZA"`.
- `spec_for("AAPL")` comes from the table; `spec_for("QQQQ")` uses defaults.
- `rng_for("AAPL", 42)` produces the same first 10 Gaussians in two instances; `rng_for("AAPL", 43)` differs.

Source tests (asyncio, use a fake clock or `sim_tick_ms=1`):

- After `set_tickers({"AAPL"})` and three ticks, `cache.history("AAPL")` has 4 entries (the prime tick plus three), oldest first, and `session_open == 190.0`.
- With `SIM_SEED=7`, the first 50 prices of `AAPL` are identical whether the ticker set is `{"AAPL"}` or `{"AAPL","MSFT","ZZZZ"}`.
- `prime({"QQQQ"})` returns a quote whose price equals `hashed_seed_price("QQQQ")` without `QQQQ` being in the ticker set.
- `set_tickers(set())` → `_tick()` writes nothing and the cache is empty.
- Price never drops below `0.01` over 100,000 ticks at `sigma=0.05` (stress, marked slow).
- Exactly one `cache.apply()` call per tick (spy).
- Conformance suite from MARKET_INTERFACE.md §11 passes.

---

## 9. Tuning cheatsheet

| Symptom | Knob |
|---|---|
| Board looks frozen | raise `sigma_tick` (0.0006 → 0.001) or lower `SIM_TICK_MS` |
| Prices wander far from seed in a long demo | raise `kappa` (1e-4 → 3e-4) |
| Everything moves in lockstep | lower `sim_rho_market` |
| Not enough drama | enable events, raise `sim_event_rate` |
| Tests flaky | set `SIM_SEED`, `rho=0`, `sim_event_rate=0` |

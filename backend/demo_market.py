#!/usr/bin/env python3
"""Terminal demo of the FinAlly market simulator.

Runs the real `SimulatorSource` against the real `PriceCache` (backend/app/market)
and renders a live tape in the terminal: price, direction, change vs. session open
and a sparkline per ticker. A short scripted sequence shows the interface at work
(prime() an unwatched ticker, add it to the priced set, drop another). At the end
it prints the source's health() dict and a checklist of the contract guarantees.

Usage (from the repo root; only the standard library is needed):

    python3 backend/demo_market.py                      # default watchlist, until Ctrl+C
    python3 backend/demo_market.py --seconds 20         # stop after 20 s
    python3 backend/demo_market.py --seed 42            # reproducible paths (SIM_SEED)
    python3 backend/demo_market.py --tickers AAPL,TSLA,XYZQ --tick-ms 250
    python3 backend/demo_market.py --json --seconds 3   # print the SSE payload per tick
    python3 backend/demo_market.py --plain --seconds 5  # one summary line per tick (for logs/CI)

Or with uv:  cd backend && uv run python demo_market.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make `app` importable without install

from app.market import MarketConfig, PriceCache, PriceSnapshot, SimulatorSource, build_source  # noqa: E402
from app.market.seeds import SEEDS, hashed_seed_price, spec_for  # noqa: E402

DEFAULT_WATCHLIST = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]
SPARK_BARS = "▁▂▃▄▅▆▇█"

# ---- ANSI helpers ---------------------------------------------------------------
RESET, BOLD, DIM = "\x1b[0m", "\x1b[1m", "\x1b[2m"
GREEN, RED, YELLOW, BLUE, PURPLE, GRAY = "\x1b[32m", "\x1b[31m", "\x1b[33m", "\x1b[34m", "\x1b[35m", "\x1b[90m"
HOME, CLEAR_LINE, CLEAR_BELOW = "\x1b[H", "\x1b[K", "\x1b[J"
HIDE_CURSOR, SHOW_CURSOR = "\x1b[?25l", "\x1b[?25h"


def color_enabled(args: argparse.Namespace) -> bool:
    return sys.stdout.isatty() and not args.no_color and not os.getenv("NO_COLOR")


def paint(text: str, *codes: str, enabled: bool = True) -> str:
    return "".join(codes) + text + RESET if enabled else text


# ---- formatting -----------------------------------------------------------------
def iso_z(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts_ms % 1000:03d}Z"


def sparkline(values: list[float], width: int = 36) -> str:
    vals = values[-width:]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return SPARK_BARS[3] * len(vals)
    return "".join(SPARK_BARS[int((v - lo) / (hi - lo) * (len(SPARK_BARS) - 1))] for v in vals)


def to_sse_payload(snap: PriceSnapshot) -> dict:
    """The exact shape GET /api/stream/prices will send per tick (PLAN.md §6)."""
    return {
        "ts": iso_z(snap.ts_ms),
        "prices": [
            {
                "ticker": q.ticker,
                "price": round(q.price, 4),
                "prev_price": round(q.prev_price, 4),
                "session_open": round(q.session_open, 4),
                "change_pct": round(q.change_pct, 4),
                "direction": q.direction,
            }
            for q in sorted(snap.quotes, key=lambda q: q.ticker)
        ],
    }


# ---- the demo -------------------------------------------------------------------
class Demo:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.color = color_enabled(args)
        self.tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        self.cfg = MarketConfig(sim_seed=args.seed, sim_tick_ms=args.tick_ms)
        self.cache = PriceCache()
        self.source = build_source(self.cache, self.cfg)
        assert isinstance(self.source, SimulatorSource)
        self.events: list[str] = []
        self.apply_calls = 0
        self.fetch_now_calls = 0
        self.opens_seen: dict[str, float] = {}
        self.max_history = 0
        self.contract_ok = True  # session_open constant and history oldest-first
        self.min_price = math.inf
        self.started = 0.0
        self._spy()

    # Count the writes so we can prove "one cache.apply() per tick" at the end.
    def _spy(self) -> None:
        orig_apply, orig_fetch = self.cache.apply, self.source._fetch_now

        async def apply(ticks, session_open=None):
            self.apply_calls += 1
            await orig_apply(ticks, session_open)

        async def fetch_now(tickers):
            self.fetch_now_calls += 1
            await orig_fetch(tickers)

        self.cache.apply = apply  # type: ignore[method-assign]
        self.source._fetch_now = fetch_now  # type: ignore[method-assign]

    def log(self, msg: str) -> None:
        stamp = f"+{time.monotonic() - self.started:5.1f}s"
        self.events.append(f"{stamp}  {msg}")
        if self.args.plain or self.args.json:
            print(paint(f"[{stamp}] {msg}", YELLOW, enabled=self.color), flush=True)

    # ---- the scripted sequence that exercises the interface --------------------
    async def script(self) -> None:
        if self.args.no_script:
            return
        extra = "ZZZZ"
        await asyncio.sleep(3)
        quotes = await self.source.prime({extra})  # not in the priced set: what a buy of an unwatched ticker does
        q = quotes[extra]
        self.log(
            f"prime({{'{extra}'}}) -> ${q.price:,.2f} (hashed seed, {extra} is NOT in the ticker set, "
            f"so it is cached but does not tick)"
        )
        await asyncio.sleep(3)
        await self.source.set_tickers(set(self.tickers) | {extra})
        self.log(f"set_tickers(watchlist + {extra}) -> {extra} now ticks every {self.cfg.sim_tick_ms} ms")
        await asyncio.sleep(4)
        victim = self.tickers[-1]
        await self.source.set_tickers((set(self.tickers) | {extra}) - {victim})
        self.log(f"set_tickers(... - {victim}) -> {victim} dropped from the cache; its state is forgotten")

    # ---- rendering -----------------------------------------------------------------
    def render_table(self) -> str:
        c = self.color
        snap = self.cache.snapshot()
        h = self.source.health()
        elapsed = max(1e-9, time.monotonic() - self.started)
        lines = [
            paint(" FinAlly market simulator ", BOLD, YELLOW, enabled=c)
            + paint(
                f"  source={h['name']}  tick={h['tick_ms']}ms  ticks={h['ticks']}  "
                f"measured={h['ticks'] / elapsed:.2f}/s  elapsed={elapsed:5.1f}s  "
                f"seed={'SIM_SEED=' + str(self.cfg.sim_seed) if h['seeded'] else 'random'}",
                DIM,
                enabled=c,
            ),
            paint(f" {'TICKER':<7}{'PRICE':>11} {'':2}{'PREV':>11}{'CHG%':>9}  {'OPEN':>10}  {'HIST':>4}  SPARKLINE (last 36 ticks)", BOLD, enabled=c),
        ]
        for q in sorted(snap.quotes, key=lambda q: q.ticker):
            arrow, col = {"up": ("▲", GREEN), "down": ("▼", RED)}.get(q.direction, ("·", GRAY))
            chg_col = GREEN if q.change_pct > 0 else RED if q.change_pct < 0 else GRAY
            in_set = q.ticker in h["tickers"]
            name = paint(f"{q.ticker:<7}", BOLD if in_set else DIM, enabled=c)
            price = paint(f"{q.price:>11,.2f}", col, BOLD, enabled=c)
            line = (
                f" {name}{price} {paint(arrow, col, enabled=c):2}{q.prev_price:>11,.2f}"
                f"{paint(f'{q.change_pct:>+8.2f}%', chg_col, enabled=c)}  {q.session_open:>10,.2f}"
                f"  {len(q.history):>4}  {paint(sparkline([t.price for t in q.history]), BLUE, enabled=c)}"
            )
            if not in_set:
                line += paint("  (primed only, not ticking)", DIM, enabled=c)
            lines.append(line)
        lines.append("")
        lines.append(paint(" events", BOLD, enabled=c) + paint("  (prime / set_tickers calls made by the demo script)", DIM, enabled=c))
        for e in self.events[-5:] or ["   (none yet)"]:
            lines.append(paint(f"   {e}", YELLOW, enabled=c))
        lines.append("")
        lines.append(paint(" Ctrl+C to stop and print the summary", DIM, enabled=c))
        return "\n".join(line + CLEAR_LINE for line in lines)

    def render_plain(self, version: int) -> str:
        snap = self.cache.snapshot()
        parts = []
        for q in sorted(snap.quotes, key=lambda q: q.ticker):
            arrow = {"up": "+", "down": "-"}.get(q.direction, "=")
            parts.append(f"{q.ticker} {q.price:.2f}{arrow} ({q.change_pct:+.2f}%)")
        return f"v{version:<4} {iso_z(snap.ts_ms)}  " + "  ".join(parts)

    # ---- bookkeeping for the final checklist ----------------------------------------
    def observe(self) -> None:
        for q in self.cache.snapshot().quotes:
            self.opens_seen.setdefault(q.ticker, q.session_open)
            if self.opens_seen[q.ticker] != q.session_open:
                self.contract_ok = False  # session_open changed: contract violated
            self.min_price = min(self.min_price, q.price)
            self.max_history = max(self.max_history, len(q.history))
            ts = [t.ts_ms for t in q.history]
            if ts != sorted(ts):
                self.contract_ok = False

    # ---- main loop ------------------------------------------------------------------
    async def run(self) -> None:
        self.print_banner()
        await self.source.set_tickers(set(self.tickers))  # primes every ticker before returning
        self.started = time.monotonic()
        await self.source.start()

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, stop.set)
            loop.add_signal_handler(signal.SIGTERM, stop.set)
        except NotImplementedError:  # Windows: fall back to KeyboardInterrupt
            pass
        if self.args.seconds:
            loop.call_later(self.args.seconds, stop.set)

        script_task = asyncio.create_task(self.script())
        live = not (self.args.plain or self.args.json)
        if live:
            sys.stdout.write(HIDE_CURSOR + "\x1b[2J")
        version = 0
        try:
            while not stop.is_set():
                waiter = asyncio.create_task(self.cache.wait_for_change(version))
                stopper = asyncio.create_task(stop.wait())
                done, _ = await asyncio.wait({waiter, stopper}, return_when=asyncio.FIRST_COMPLETED)
                stopper.cancel()
                if waiter not in done:
                    waiter.cancel()
                    break
                version = waiter.result()
                self.observe()
                if self.args.json:
                    print(json.dumps(to_sse_payload(self.cache.snapshot())), flush=True)
                elif self.args.plain:
                    print(self.render_plain(version), flush=True)
                else:
                    sys.stdout.write(HOME + self.render_table() + CLEAR_BELOW)
                    sys.stdout.flush()
        except KeyboardInterrupt:
            pass
        finally:
            script_task.cancel()
            await self.source.stop()
            if live:
                sys.stdout.write(SHOW_CURSOR + "\n")
        self.print_summary()

    def print_banner(self) -> None:
        c = self.color
        print(paint("FinAlly market simulator demo", BOLD, YELLOW, enabled=c))
        print(paint(f"tick={self.cfg.sim_tick_ms} ms   seed={self.cfg.sim_seed if self.cfg.sim_seed is not None else 'random (os.urandom)'}   tickers={len(self.tickers)}", DIM, enabled=c))
        print()
        print(paint(f"{'TICKER':<7}{'SEED $':>10}{'SIGMA/tick':>12}{'MU/tick':>10}  SECTOR    ORIGIN", BOLD, enabled=c))
        for t in self.tickers:
            s = spec_for(t)
            origin = "seed table" if t in SEEDS else f"sha256 hash -> ${hashed_seed_price(t):.2f} in [20, 400]"
            print(f"{t:<7}{s.price:>10,.2f}{s.sigma_tick:>12.4f}{s.mu_tick:>10.0e}  {s.sector:<9} {origin}")
        print()
        if not (self.args.plain or self.args.json):
            print(paint("starting live tape...", DIM, enabled=c))
            time.sleep(1.0)

    def print_summary(self) -> None:
        c = self.color
        h = self.source.health()
        ticks, primes = h["ticks"], self.fetch_now_calls
        print(paint("summary", BOLD, YELLOW, enabled=c))
        print(f"health(): {json.dumps(h)}")
        print()
        print(paint(f"{'TICKER':<7}{'OPEN':>11}{'LAST':>11}{'CHG%':>9}{'LOW':>11}{'HIGH':>11}{'TICKS':>7}", BOLD, enabled=c))
        for q in sorted(self.cache.snapshot().quotes, key=lambda q: q.ticker):
            prices = [t.price for t in q.history]
            print(f"{q.ticker:<7}{q.session_open:>11,.2f}{q.price:>11,.2f}{q.change_pct:>+8.2f}%{min(prices):>11,.2f}{max(prices):>11,.2f}{len(prices):>7}")
        print()
        checks = [
            (ticks > 0, f"simulator ticked {ticks} times"),
            (self.apply_calls == ticks + primes, f"exactly one cache.apply() per tick: {self.apply_calls} applies = {ticks} ticks + {primes} prime/fetch calls"),
            (math.isfinite(self.min_price) and self.min_price >= 0.01, f"all prices finite and >= $0.01 (min seen ${self.min_price:,.2f})"),
            (self.contract_ok, "session_open fixed per ticker; history oldest-first"),
            (self.max_history <= 600, f"history capped at 600 ticks (max seen {self.max_history})"),
        ]
        for ok, text in checks:
            mark = paint("PASS", GREEN, BOLD, enabled=c) if ok else paint("FAIL", RED, BOLD, enabled=c)
            print(f"  [{mark}] {text}")
        if not all(ok for ok, _ in checks):
            sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog="Usage" + __doc__.split("Usage", 1)[1])
    p.add_argument("--tickers", default=",".join(DEFAULT_WATCHLIST), help="comma-separated tickers (default: the seed watchlist)")
    p.add_argument("--seconds", type=float, default=0, help="stop after this many seconds (default: run until Ctrl+C)")
    p.add_argument("--tick-ms", type=int, default=int(os.getenv("SIM_TICK_MS", "500")), help="tick interval in ms (default: SIM_TICK_MS or 500)")
    p.add_argument("--seed", type=int, default=int(os.environ["SIM_SEED"]) if os.getenv("SIM_SEED") else None, help="integer seed for reproducible paths (default: SIM_SEED or random)")
    p.add_argument("--json", action="store_true", help="print the SSE `prices` payload per tick instead of the table")
    p.add_argument("--plain", action="store_true", help="one summary line per tick, no screen redraws")
    p.add_argument("--no-script", action="store_true", help="skip the scripted prime/set_tickers sequence")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    args = p.parse_args()
    if not sys.stdout.isatty() and not args.json:
        args.plain = True  # redraws make no sense in a pipe or a log file
    try:
        asyncio.run(Demo(args).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

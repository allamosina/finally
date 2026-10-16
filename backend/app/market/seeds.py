"""Seed table for the simulator plus the stable fallback for unknown tickers.

See planning/MARKET_SIMULATOR.md §3 and §4.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class SeedSpec:
    price: float
    sigma_tick: float
    mu_tick: float = 0.0
    sector: str = "other"


SEEDS: dict[str, SeedSpec] = {
    # ticker : price,   sigma,   mu,      sector
    "AAPL": SeedSpec(190.0, 0.0004, 0.0, "tech"),
    "MSFT": SeedSpec(415.0, 0.0004, 0.0, "tech"),
    "GOOGL": SeedSpec(175.0, 0.0005, 0.0, "tech"),
    "AMZN": SeedSpec(185.0, 0.0005, 0.0, "tech"),
    "META": SeedSpec(500.0, 0.0006, 0.0, "tech"),
    "NVDA": SeedSpec(880.0, 0.0009, 1e-6, "semis"),
    "AMD": SeedSpec(160.0, 0.0009, 0.0, "semis"),
    "INTC": SeedSpec(31.0, 0.0007, -1e-6, "semis"),
    "TSLA": SeedSpec(175.0, 0.0012, 0.0, "auto"),
    "F": SeedSpec(12.5, 0.0006, 0.0, "auto"),
    "GM": SeedSpec(44.0, 0.0006, 0.0, "auto"),
    "JPM": SeedSpec(195.0, 0.0004, 0.0, "finance"),
    "BAC": SeedSpec(38.0, 0.0005, 0.0, "finance"),
    "GS": SeedSpec(420.0, 0.0005, 0.0, "finance"),
    "V": SeedSpec(275.0, 0.0003, 0.0, "finance"),
    "MA": SeedSpec(460.0, 0.0003, 0.0, "finance"),
    "NFLX": SeedSpec(610.0, 0.0007, 0.0, "media"),
    "DIS": SeedSpec(112.0, 0.0005, 0.0, "media"),
    "XOM": SeedSpec(118.0, 0.0004, 0.0, "energy"),
    "CVX": SeedSpec(160.0, 0.0004, 0.0, "energy"),
    "JNJ": SeedSpec(155.0, 0.0003, 0.0, "health"),
    "PFE": SeedSpec(27.0, 0.0005, 0.0, "health"),
    "UNH": SeedSpec(500.0, 0.0004, 0.0, "health"),
    "WMT": SeedSpec(60.0, 0.0003, 0.0, "retail"),
    "COST": SeedSpec(730.0, 0.0003, 0.0, "retail"),
    "KO": SeedSpec(62.0, 0.0002, 0.0, "staples"),
    "PEP": SeedSpec(170.0, 0.0002, 0.0, "staples"),
    "BA": SeedSpec(180.0, 0.0008, 0.0, "industrial"),
    "CAT": SeedSpec(340.0, 0.0005, 0.0, "industrial"),
    "PYPL": SeedSpec(64.0, 0.0007, 0.0, "fintech"),
    "COIN": SeedSpec(210.0, 0.0014, 0.0, "crypto"),
    "GME": SeedSpec(25.0, 0.0015, 0.0, "meme"),
}

DEFAULT_SIGMA = 0.0006
DEFAULT_MU = 0.0


def hashed_seed_price(ticker: str, lo: float = 20.0, hi: float = 400.0) -> float:
    """Stable pseudo-random seed price in [lo, hi) for a ticker not in the table.

    SHA-256 is stable across processes, platforms and Python versions; Python's
    built-in hash() is salted per process and must not be used here.
    """
    digest = hashlib.sha256(ticker.encode("ascii")).digest()
    frac = int.from_bytes(digest[:8], "big") / 2**64  # uniform in [0, 1)
    return round(lo + frac * (hi - lo), 2)


def spec_for(ticker: str) -> SeedSpec:
    return SEEDS.get(ticker) or SeedSpec(hashed_seed_price(ticker), DEFAULT_SIGMA, DEFAULT_MU)

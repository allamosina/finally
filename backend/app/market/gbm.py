"""Pure functions for the geometric Brownian motion simulator. No asyncio here.

See planning/MARKET_SIMULATOR.md §2 and §5.
"""

from __future__ import annotations

import hashlib
import math
import random


def gbm_step(price: float, mu: float, sigma: float, z: float) -> float:
    """One discrete GBM step. `mu` and `sigma` are already per tick, so dt is folded in:

        S(t+1) = S(t) * exp((mu - sigma^2 / 2) + sigma * z),   z ~ N(0, 1)
    """
    return price * math.exp((mu - 0.5 * sigma * sigma) + sigma * z)


def rng_for(ticker: str, global_seed: int | None) -> random.Random:
    """A per-ticker RNG. With a global seed the path of each ticker is reproducible
    regardless of which other tickers are present; without one it is os.urandom-seeded."""
    if global_seed is None:
        return random.Random()
    material = hashlib.sha256(f"{global_seed}:{ticker}".encode()).digest()
    return random.Random(int.from_bytes(material[:8], "big"))

"""Market data configuration parsed from the environment.

See planning/MARKET_INTERFACE.md §8 and §10.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MarketConfig:
    massive_api_key: str | None = None
    massive_mode: str | None = None  # None = auto-detect
    poll_interval: float | None = None  # None = per-mode default
    sim_seed: int | None = None  # None = nondeterministic
    sim_tick_ms: int = 500

    @classmethod
    def from_env(cls) -> "MarketConfig":
        key = (os.getenv("MASSIVE_API_KEY") or "").strip() or None
        return cls(
            massive_api_key=key,
            massive_mode=os.getenv("MASSIVE_MODE") or None,
            poll_interval=float(os.environ["MASSIVE_POLL_INTERVAL"])
            if os.getenv("MASSIVE_POLL_INTERVAL")
            else None,
            sim_seed=int(os.environ["SIM_SEED"]) if os.getenv("SIM_SEED") else None,
            sim_tick_ms=int(os.getenv("SIM_TICK_MS", "500")),
        )

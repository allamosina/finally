"""LLM configuration and `status()` for /api/health."""

from __future__ import annotations

import os
from typing import Literal

import os

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
REASONING_EFFORT = "low"
HISTORY_LIMIT = 20


def is_mock() -> bool:
    return os.environ.get("LLM_MOCK", "").strip().lower() == "true"


def status() -> Literal["live", "mock", "unconfigured"]:
    """Read the environment on every call so tests and health checks see changes."""
    if is_mock():
        return "mock"
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        return "live"
    return "unconfigured"

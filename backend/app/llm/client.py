"""LiteLLM -> OpenRouter -> Cerebras call with structured output, retry once, raw-text fallback."""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from .config import EXTRA_BODY, MODEL, REASONING_EFFORT
from .schemas import LLMOutput

# A model call: messages -> raw text content of the first choice.
ModelCall = Callable[[list[dict[str, str]]], Awaitable[str | None]]

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


async def call_model(messages: list[dict[str, str]]) -> str | None:
    """One real model call. The API key is read by LiteLLM from the environment."""
    from litellm import acompletion  # lazy: keeps import cheap and tests offline

    response = await acompletion(
        model=MODEL,
        messages=messages,
        response_format=LLMOutput,
        reasoning_effort=REASONING_EFFORT,
        extra_body=EXTRA_BODY,
    )
    return response.choices[0].message.content


def parse_output(raw: str | None) -> LLMOutput:
    """Validate raw model text; raises ValueError (incl. pydantic ValidationError) when bad."""
    if raw is None or not raw.strip():
        raise ValueError("empty model response")
    text = raw.strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1)
    try:
        return LLMOutput.model_validate_json(text)
    except ValidationError as e:
        raise ValueError(str(e)) from e


async def get_structured_reply(
    messages: list[dict[str, str]], call: ModelCall | None = None
) -> LLMOutput:
    """Call the model; on invalid JSON/schema retry once; then use raw text as the message.

    Transport errors (network, auth) from the model call propagate to the caller.
    """
    call = call or call_model
    raw: str | None = None
    for _ in range(2):
        raw = await call(messages)
        try:
            return parse_output(raw)
        except ValueError:
            continue
    fallback = (raw or "").strip() or "Sorry, I could not produce a response. Please try again."
    return LLMOutput(message=fallback)

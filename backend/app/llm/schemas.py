"""Pydantic models for the LLM output (PLAN §9) and the chat API response."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LLMTrade(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    quantity: float = Field(gt=0)

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class LLMWatchlistChange(BaseModel):
    ticker: str
    action: Literal["add", "remove"]

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class LLMOutput(BaseModel):
    """What the model returns. Passed as `response_format` to LiteLLM."""

    message: str
    trades: list[LLMTrade] = Field(default_factory=list)
    watchlist_changes: list[LLMWatchlistChange] = Field(default_factory=list)

    @field_validator("trades", "watchlist_changes", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return [] if v is None else v


class TradeAction(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    quantity: float
    price: float | None = None
    status: Literal["executed", "failed"]
    error: str | None = None


class WatchlistAction(BaseModel):
    ticker: str
    action: Literal["add", "remove"]
    status: Literal["executed", "failed"]
    error: str | None = None


class Actions(BaseModel):
    trades: list[TradeAction] = Field(default_factory=list)
    watchlist_changes: list[WatchlistAction] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """`POST /api/chat` response; `actions` is also stored in chat_messages.actions."""

    message: str
    actions: Actions = Field(default_factory=Actions)

"""Chat routes (PLAN §8, §9): thin wrappers over `app.llm` (TEAM.md §2.3)."""

from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import llm
from app.db import repo

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@router.post("/chat")
async def post_chat(body: ChatRequest) -> dict:
    if llm.status() == "unconfigured":
        raise HTTPException(status_code=503, detail="LLM not configured")
    try:
        response = await llm.chat(body.message)
    except llm.LLMNotConfigured:
        raise HTTPException(status_code=503, detail="LLM not configured") from None
    except Exception as exc:  # model transport errors: OpenRouter down, timeout, auth
        log.exception("chat: LLM call failed")
        raise HTTPException(status_code=502, detail=f"LLM request failed: {type(exc).__name__}") from None
    return response.model_dump() if hasattr(response, "model_dump") else dict(response)


@router.get("/chat/history")
async def get_chat_history(limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    return [asdict(m) for m in await repo.list_chat(limit=limit)]

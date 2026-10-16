from __future__ import annotations

from app import llm
from app.db import repo


async def test_chat_unconfigured_is_503(client, env):
    env.setenv("LLM_MOCK", "false")
    env.delenv("OPENROUTER_API_KEY", raising=False)
    r = await client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 503
    assert r.json() == {"detail": "LLM not configured"}


async def test_chat_delegates_to_llm(client, env):
    seen = []

    class Resp:
        def model_dump(self):
            return {"message": "[mock] ok", "actions": {"trades": [], "watchlist_changes": []}}

    async def fake_chat(message):
        seen.append(message)
        return Resp()

    env.setattr(llm, "chat", fake_chat)
    r = await client.post("/api/chat", json={"message": "how am I doing?"})
    assert r.status_code == 200
    assert r.json()["message"] == "[mock] ok"
    assert seen == ["how am I doing?"]


async def test_chat_empty_message_is_422(client):
    assert (await client.post("/api/chat", json={"message": ""})).status_code == 422
    assert (await client.post("/api/chat", json={})).status_code == 422


async def test_chat_history_shape_and_limit(client):
    await repo.add_chat("user", "buy 5 AAPL")
    await repo.add_chat("assistant", "[mock] placing", {"trades": [], "watchlist_changes": []})
    r = await client.get("/api/chat/history")
    assert r.status_code == 200
    rows = r.json()
    assert [m["role"] for m in rows] == ["user", "assistant"]
    assert set(rows[0]) == {"id", "role", "content", "actions", "created_at"}
    assert rows[0]["actions"] is None and rows[1]["actions"] == {"trades": [], "watchlist_changes": []}
    assert len((await client.get("/api/chat/history?limit=1")).json()) == 1
    assert (await client.get("/api/chat/history?limit=0")).status_code == 422


async def test_chat_not_configured_exception_is_503(client, env):
    async def raise_nc(message):
        raise llm.LLMNotConfigured("no key")

    env.setattr(llm, "chat", raise_nc)
    r = await client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 503 and r.json() == {"detail": "LLM not configured"}


async def test_chat_transport_error_is_502(client, env):
    async def boom(message):
        raise ConnectionError("openrouter unreachable")

    env.setattr(llm, "chat", boom)
    r = await client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 502
    assert r.json()["detail"].startswith("LLM request failed")


async def test_mock_chat_end_to_end_executes_and_fails_trades(client):
    r = await client.post("/api/chat", json={"message": "buy 5 AAPL"})
    assert r.status_code == 200
    body = r.json()
    assert body["message"].startswith("[mock] ")
    [t] = body["actions"]["trades"]
    assert (t["ticker"], t["side"], t["quantity"], t["status"], t["error"]) == ("AAPL", "buy", 5, "executed", None)
    assert t["price"] > 0
    assert (await client.get("/api/portfolio")).json()["positions"][0]["quantity"] == 5

    r = await client.post("/api/chat", json={"message": "sell 500 AAPL"})
    [t] = r.json()["actions"]["trades"]
    assert t["status"] == "failed" and t["price"] is None
    assert t["error"] == "Insufficient shares: have 5, selling 500"

    history = (await client.get("/api/chat/history")).json()
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    assert history[3]["actions"]["trades"][0]["status"] == "failed"


async def test_mock_chat_watchlist_changes(client):
    r = await client.post("/api/chat", json={"message": "add PYPL"})
    [c] = r.json()["actions"]["watchlist_changes"]
    assert (c["ticker"], c["action"], c["status"]) == ("PYPL", "add", "executed")
    assert "PYPL" in [w["ticker"] for w in (await client.get("/api/watchlist")).json()]

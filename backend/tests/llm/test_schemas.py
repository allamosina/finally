import pytest
from pydantic import ValidationError

from app.llm.schemas import ChatResponse, LLMOutput


def test_message_only():
    o = LLMOutput.model_validate_json('{"message": "hi"}')
    assert o.trades == [] and o.watchlist_changes == []


def test_full_shape_uppercases_tickers():
    o = LLMOutput.model_validate_json(
        '{"message":"m","trades":[{"ticker":"aapl","side":"buy","quantity":10.5}],'
        '"watchlist_changes":[{"ticker":"pypl","action":"add"}]}'
    )
    assert o.trades[0].ticker == "AAPL" and o.trades[0].quantity == 10.5
    assert o.watchlist_changes[0].ticker == "PYPL"


def test_null_lists_accepted():
    o = LLMOutput.model_validate_json('{"message":"m","trades":null,"watchlist_changes":null}')
    assert o.trades == [] and o.watchlist_changes == []


@pytest.mark.parametrize(
    "bad",
    [
        '{"trades": []}',
        '{"message":"m","trades":[{"ticker":"A","side":"hold","quantity":1}]}',
        '{"message":"m","trades":[{"ticker":"A","side":"buy","quantity":0}]}',
        '{"message":"m","trades":[{"ticker":"A","side":"buy","quantity":-2}]}',
        '{"message":"m","watchlist_changes":[{"ticker":"A","action":"toggle"}]}',
    ],
)
def test_invalid_rejected(bad):
    with pytest.raises(ValidationError):
        LLMOutput.model_validate_json(bad)


def test_chat_response_shape():
    r = ChatResponse.model_validate(
        {
            "message": "x",
            "actions": {
                "trades": [
                    {"ticker": "AAPL", "side": "buy", "quantity": 10, "price": 190.12, "status": "executed", "error": None},
                    {"ticker": "TSLA", "side": "sell", "quantity": 50, "price": None, "status": "failed", "error": "e"},
                ],
                "watchlist_changes": [{"ticker": "PYPL", "action": "add", "status": "executed", "error": None}],
            },
        }
    )
    d = r.model_dump()
    assert d["actions"]["trades"][1]["status"] == "failed"
    assert ChatResponse(message="x").model_dump()["actions"] == {"trades": [], "watchlist_changes": []}

import pytest

from app.llm.client import get_structured_reply, parse_output

GOOD = '{"message":"ok","trades":[{"ticker":"AAPL","side":"buy","quantity":1}]}'


def scripted(*replies):
    calls = []

    async def call(messages):
        calls.append(messages)
        return replies[min(len(calls), len(replies)) - 1]

    call.calls = calls
    return call


def test_parse_strips_code_fence():
    assert parse_output("```json\n" + GOOD + "\n```").message == "ok"


@pytest.mark.parametrize("raw", [None, "", "  ", "not json", '{"trades":[]}'])
def test_parse_bad(raw):
    with pytest.raises(ValueError):
        parse_output(raw)


async def test_valid_first_try_single_call():
    call = scripted(GOOD)
    out = await get_structured_reply([{"role": "user", "content": "x"}], call)
    assert out.trades[0].ticker == "AAPL" and len(call.calls) == 1


async def test_retry_once_then_success():
    call = scripted("garbage", GOOD)
    out = await get_structured_reply([], call)
    assert out.message == "ok" and len(call.calls) == 2


async def test_two_failures_fall_back_to_raw_text():
    call = scripted("first bad", "plain text answer")
    out = await get_structured_reply([], call)
    assert out.message == "plain text answer"
    assert out.trades == [] and out.watchlist_changes == [] and len(call.calls) == 2


async def test_empty_fallback_has_message():
    out = await get_structured_reply([], scripted(None, ""))
    assert out.message


async def test_transport_error_propagates():
    async def boom(messages):
        raise RuntimeError("network")

    with pytest.raises(RuntimeError):
        await get_structured_reply([], boom)

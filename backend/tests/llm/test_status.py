import pytest

from app.llm import status


@pytest.mark.parametrize(
    "mock,key,expected",
    [
        ("true", "k", "mock"),
        ("TRUE", None, "mock"),
        ("false", "k", "live"),
        (None, "k", "live"),
        ("false", "", "unconfigured"),
        (None, "   ", "unconfigured"),
        (None, None, "unconfigured"),
    ],
)
def test_status(monkeypatch, mock, key, expected):
    for name, val in (("LLM_MOCK", mock), ("OPENROUTER_API_KEY", key)):
        if val is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, val)
    assert status() == expected

from __future__ import annotations

import math

import pytest

from app.services.validation import InvalidInput, normalize_quantity, normalize_ticker


@pytest.mark.parametrize("raw,expected", [("AAPL", "AAPL"), ("aapl", "AAPL"), (" v ", "V"), ("GOOGL", "GOOGL")])
def test_ticker_ok(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["", "TOOLONG", "A1", "BRK.B", "AA PL", None, 5])
def test_ticker_rejected(raw):
    with pytest.raises(InvalidInput):
        normalize_ticker(raw)


@pytest.mark.parametrize("raw,expected", [(1, 1.0), (2.5, 2.5), (0.123456, 0.1235), (10.00004, 10.0)])
def test_quantity_ok(raw, expected):
    assert normalize_quantity(raw) == expected


@pytest.mark.parametrize("raw", [0, -1, 0.00004, math.inf, math.nan, "5", True, None])
def test_quantity_rejected(raw):
    with pytest.raises(InvalidInput):
        normalize_quantity(raw)

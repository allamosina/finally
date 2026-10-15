from app.market import PriceCache


def test_first_update_has_flat_direction():
    c = PriceCache()
    u = c.update("aapl", 190.123)
    assert u.ticker == "AAPL"
    assert u.price == 190.12
    assert u.previous_price == u.price
    assert u.direction == "flat"


def test_direction_and_previous_price():
    c = PriceCache()
    c.update("AAPL", 100)
    up = c.update("AAPL", 101)
    assert (up.previous_price, up.direction, up.change) == (100, "up", 1)
    down = c.update("AAPL", 99)
    assert (down.previous_price, down.direction) == (101, "down")


def test_get_remove_and_version():
    c = PriceCache()
    v0 = c.version
    c.update("MSFT", 400)
    assert c.version == v0 + 1
    assert "msft" in c and len(c) == 1
    assert c.get_price("MSFT") == 400
    c.remove("MSFT")
    assert c.get("MSFT") is None and c.version == v0 + 2
    c.remove("MSFT")  # no-op, no version bump
    assert c.version == v0 + 2


def test_explicit_timestamp_and_to_dict():
    c = PriceCache()
    d = c.update("V", 280, timestamp=123.0).to_dict()
    assert d == {
        "ticker": "V",
        "price": 280,
        "previous_price": 280,
        "timestamp": 123.0,
        "direction": "flat",
    }

from models import Candle, OrderResult, Position

def test_candle_creation():
    c = Candle(
        timestamp=1700000000,
        open=100.0, high=105.0, low=99.0, close=103.0, volume=1000.0,
        symbol="ATOM-USD"
    )
    assert c.timestamp == 1700000000
    assert c.close == 103.0
    assert c.symbol == "ATOM-USD"

def test_candle_is_bullish():
    c = Candle(timestamp=0, open=100.0, high=105.0, low=99.0, close=103.0, volume=500.0, symbol="ATOM-USD")
    assert c.is_bullish() is True

def test_candle_is_bearish():
    c = Candle(timestamp=0, open=103.0, high=105.0, low=99.0, close=100.0, volume=500.0, symbol="ATOM-USD")
    assert c.is_bullish() is False


def test_order_result_fields():
    order = OrderResult(
        order_id="paper_1",
        symbol="ATOM/USD",
        side="buy",
        size=10.0,
        fill_price=7.20,
        timestamp=1000,
    )
    assert order.order_id == "paper_1"
    assert order.symbol == "ATOM/USD"
    assert order.side == "buy"
    assert order.size == 10.0
    assert order.fill_price == 7.20
    assert order.timestamp == 1000


def test_position_fields():
    pos = Position(
        symbol="ATOM/USD",
        side="long",
        size=13.88,
        entry_price=7.20,
        entry_time=1000,
    )
    assert pos.symbol == "ATOM/USD"
    assert pos.side == "long"
    assert pos.size == 13.88
    assert pos.entry_price == 7.20
    assert pos.entry_time == 1000

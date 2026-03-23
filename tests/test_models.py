from models import Candle
import pytest

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

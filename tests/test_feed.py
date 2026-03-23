import pytest
from unittest.mock import MagicMock
from data.feed import CandleBuilder, parse_trade_message


TRADE_MSG_BUY = {
    "channel": "market_trades",
    "events": [{
        "type": "update",
        "trades": [{
            "product_id": "ATOM-USD",
            "price": "10.50",
            "size": "5.0",
            "side": "BUY",
            "time": "2023-01-01T00:01:00Z",
        }]
    }]
}

TRADE_MSG_SELL = {
    "channel": "market_trades",
    "events": [{
        "type": "update",
        "trades": [{
            "product_id": "ATOM-USD",
            "price": "10.30",
            "size": "3.0",
            "side": "SELL",
            "time": "2023-01-01T00:02:00Z",
        }]
    }]
}


class TestParseTradeMessage:
    def test_parse_buy_trade(self):
        trades = parse_trade_message(TRADE_MSG_BUY)
        assert len(trades) == 1
        t = trades[0]
        assert t["price"] == 10.50
        assert t["size"] == 5.0
        assert t["side"] == "BUY"

    def test_parse_non_trade_message_returns_empty(self):
        msg = {"channel": "subscriptions", "events": []}
        trades = parse_trade_message(msg)
        assert trades == []

    def test_parse_multiple_trades(self):
        msg = {
            "channel": "market_trades",
            "events": [{
                "type": "update",
                "trades": [
                    {"product_id": "ATOM-USD", "price": "10.0", "size": "1.0", "side": "BUY", "time": "2023-01-01T00:01:00Z"},
                    {"product_id": "ATOM-USD", "price": "10.1", "size": "2.0", "side": "SELL", "time": "2023-01-01T00:01:01Z"},
                ]
            }]
        }
        trades = parse_trade_message(msg)
        assert len(trades) == 2


class TestCandleBuilder:
    def test_first_trade_opens_candle(self):
        callback = MagicMock()
        builder = CandleBuilder(symbol="ATOM-USD", timeframe_minutes=5, on_candle_close=callback)

        # Timestamp = 2023-01-01 00:01:00 UTC = 1672531260
        builder.process_trade(price=10.50, size=5.0, timestamp=1672531260)

        assert builder.current_open == 10.50
        assert builder.current_high == 10.50
        assert builder.current_low == 10.50
        assert builder.current_close == 10.50
        assert builder.current_volume == 5.0
        callback.assert_not_called()  # candle not closed yet

    def test_multiple_trades_update_ohlcv(self):
        callback = MagicMock()
        builder = CandleBuilder(symbol="ATOM-USD", timeframe_minutes=5, on_candle_close=callback)

        builder.process_trade(price=10.00, size=1.0, timestamp=1672531260)
        builder.process_trade(price=10.50, size=2.0, timestamp=1672531280)
        builder.process_trade(price=9.80, size=1.5, timestamp=1672531300)

        assert builder.current_open == 10.00
        assert builder.current_high == 10.50
        assert builder.current_low == 9.80
        assert builder.current_close == 9.80
        assert abs(builder.current_volume - 4.5) < 0.001

    def test_new_candle_period_fires_callback(self):
        callback = MagicMock()
        builder = CandleBuilder(symbol="ATOM-USD", timeframe_minutes=5, on_candle_close=callback)

        # Trade in minute 0
        builder.process_trade(price=10.00, size=1.0, timestamp=1672531200)  # 00:00:00
        # Trade in minute 6 (new 5-min candle)
        builder.process_trade(price=10.50, size=1.0, timestamp=1672531560)  # 00:06:00

        callback.assert_called_once()
        closed_candle = callback.call_args[0][0]
        assert closed_candle.open == 10.00
        assert closed_candle.close == 10.00
        assert closed_candle.symbol == "ATOM-USD"

    def test_callback_receives_candle_object(self):
        from models import Candle
        callback = MagicMock()
        builder = CandleBuilder(symbol="ATOM-USD", timeframe_minutes=5, on_candle_close=callback)

        builder.process_trade(10.00, 1.0, 1672531200)
        builder.process_trade(10.50, 1.0, 1672531560)  # new period

        closed = callback.call_args[0][0]
        assert isinstance(closed, Candle)

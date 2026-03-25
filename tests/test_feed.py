import pytest
from unittest.mock import MagicMock
from data.feed import KrakenFeed, parse_ohlc_message
from models import Candle


# Kraken OHLC message:
# [channelID, [beginTime, endTime, open, high, low, close, vwap, volume, count], "ohlc-5", "ATOM/USD"]
def make_ohlc_msg(
    begin_time: float,
    open_: float = 7.21,
    high: float = 7.30,
    low: float = 7.19,
    close: float = 7.26,
    volume: float = 100.0,
):
    return [
        42,
        [
            str(begin_time),
            str(begin_time + 300),
            str(open_),
            str(high),
            str(low),
            str(close),
            "7.24",
            str(volume),
            10,
        ],
        "ohlc-5",
        "ATOM/USD",
    ]


class TestParseOhlcMessage:
    def test_parse_valid_ohlc_message(self):
        msg = make_ohlc_msg(1616148000)
        result = parse_ohlc_message(msg)
        assert result is not None
        assert result["begin_time"] == 1616148000.0
        assert result["open"] == 7.21
        assert result["high"] == 7.30
        assert result["low"] == 7.19
        assert result["close"] == 7.26
        assert result["volume"] == 100.0
        assert result["pair"] == "ATOM/USD"

    def test_heartbeat_returns_none(self):
        assert parse_ohlc_message({"event": "heartbeat"}) is None

    def test_subscription_status_returns_none(self):
        assert parse_ohlc_message({"event": "subscriptionStatus", "status": "subscribed"}) is None

    def test_system_status_returns_none(self):
        assert parse_ohlc_message({"event": "systemStatus", "status": "online"}) is None

    def test_non_ohlc_channel_returns_none(self):
        msg = [42, ["data"], "ticker", "ATOM/USD"]
        assert parse_ohlc_message(msg) is None

    def test_wrong_length_array_returns_none(self):
        assert parse_ohlc_message([42, "data"]) is None


class TestKrakenFeedOhlcProcessing:
    def _make_feed(self):
        callback = MagicMock()
        feed = KrakenFeed("wss://ws.kraken.com", "ATOM/USD", 5, callback)
        return feed, callback

    def test_first_update_does_not_fire_callback(self):
        feed, callback = self._make_feed()
        feed._process_ohlc(parse_ohlc_message(make_ohlc_msg(1616148000)))
        callback.assert_not_called()

    def test_same_period_update_does_not_fire_callback(self):
        feed, callback = self._make_feed()
        feed._process_ohlc(parse_ohlc_message(make_ohlc_msg(1616148000, close=7.26)))
        feed._process_ohlc(parse_ohlc_message(make_ohlc_msg(1616148000, close=7.28)))
        callback.assert_not_called()

    def test_new_period_fires_callback_once(self):
        feed, callback = self._make_feed()
        feed._process_ohlc(parse_ohlc_message(make_ohlc_msg(1616148000)))
        feed._process_ohlc(parse_ohlc_message(make_ohlc_msg(1616148300)))  # new period
        callback.assert_called_once()

    def test_callback_receives_candle_with_last_update_values(self):
        """Emitted candle uses the final OHLC update before rollover."""
        feed, callback = self._make_feed()

        # Two updates for the same period — second has the final values
        feed._process_ohlc(parse_ohlc_message(make_ohlc_msg(1616148000, close=7.26)))
        feed._process_ohlc(parse_ohlc_message(make_ohlc_msg(1616148000, close=7.29)))

        # New period triggers emit of the completed candle
        feed._process_ohlc(parse_ohlc_message(make_ohlc_msg(1616148300)))

        candle = callback.call_args[0][0]
        assert isinstance(candle, Candle)
        assert candle.close == 7.29
        assert candle.timestamp == 1616148000
        assert candle.symbol == "ATOM/USD"

    def test_multiple_period_rollovers_fire_correct_count(self):
        feed, callback = self._make_feed()
        feed._process_ohlc(parse_ohlc_message(make_ohlc_msg(1616148000)))
        feed._process_ohlc(parse_ohlc_message(make_ohlc_msg(1616148300)))  # emits first
        feed._process_ohlc(parse_ohlc_message(make_ohlc_msg(1616148600)))  # emits second
        assert callback.call_count == 2

    def test_callback_receives_candle_object(self):
        feed, callback = self._make_feed()
        feed._process_ohlc(parse_ohlc_message(make_ohlc_msg(1616148000)))
        feed._process_ohlc(parse_ohlc_message(make_ohlc_msg(1616148300)))
        closed = callback.call_args[0][0]
        assert isinstance(closed, Candle)

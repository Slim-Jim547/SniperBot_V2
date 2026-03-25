import pytest
from unittest.mock import patch, MagicMock
from data.backfill import KrakenBackfill, parse_candles
from models import Candle


# Kraken OHLC row: [time, open, high, low, close, vwap, volume, count]
FAKE_KRAKEN_RESPONSE = {
    "error": [],
    "result": {
        "ATOMUSD": [
            [1616148000, "7.21", "7.30", "7.19", "7.26", "7.24", "100.0", 10],
            [1616148300, "7.26", "7.35", "7.22", "7.32", "7.29", "120.0", 12],
        ],
        "last": 1616148300,
    }
}


class TestParseCandles:
    def test_parse_returns_candle_list(self):
        rows = FAKE_KRAKEN_RESPONSE["result"]["ATOMUSD"]
        candles = parse_candles(rows, symbol="ATOM/USD")
        assert len(candles) == 2
        assert all(isinstance(c, Candle) for c in candles)

    def test_parse_sorts_ascending_by_timestamp(self):
        rows = [
            [1616148300, "7.26", "7.35", "7.22", "7.32", "7.29", "120.0", 12],
            [1616148000, "7.21", "7.30", "7.19", "7.26", "7.24", "100.0", 10],
        ]
        candles = parse_candles(rows, symbol="ATOM/USD")
        assert candles[0].timestamp < candles[1].timestamp

    def test_parse_correct_ohlcv_values(self):
        rows = FAKE_KRAKEN_RESPONSE["result"]["ATOMUSD"]
        candles = parse_candles(rows, symbol="ATOM/USD")
        c = candles[0]  # earliest candle
        assert c.timestamp == 1616148000
        assert c.open == 7.21
        assert c.high == 7.30
        assert c.low == 7.19
        assert c.close == 7.26
        assert c.volume == 100.0
        assert c.symbol == "ATOM/USD"

    def test_parse_sets_correct_symbol(self):
        rows = FAKE_KRAKEN_RESPONSE["result"]["ATOMUSD"]
        candles = parse_candles(rows, symbol="BTC/USD")
        assert all(c.symbol == "BTC/USD" for c in candles)


class TestKrakenBackfillFetch:
    @patch("data.backfill.requests.get")
    def test_fetch_returns_candles(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = FAKE_KRAKEN_RESPONSE
        mock_get.return_value = mock_resp

        backfill = KrakenBackfill(base_url="https://api.kraken.com")
        candles = backfill.fetch(symbol="ATOM/USD", timeframe="5", count=2)
        assert len(candles) == 2
        assert mock_get.called

    @patch("data.backfill.requests.get")
    def test_fetch_raises_on_non_200(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get.return_value = mock_resp

        backfill = KrakenBackfill(base_url="https://api.kraken.com")
        with pytest.raises(RuntimeError, match="Kraken API error"):
            backfill.fetch(symbol="ATOM/USD", timeframe="5", count=2)

    @patch("data.backfill.requests.get")
    def test_fetch_raises_on_api_error_field(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "error": ["EGeneral:Invalid arguments"],
            "result": {},
        }
        mock_get.return_value = mock_resp

        backfill = KrakenBackfill(base_url="https://api.kraken.com")
        with pytest.raises(RuntimeError, match="Kraken API returned errors"):
            backfill.fetch(symbol="ATOM/USD", timeframe="5", count=2)

    @patch("data.backfill.requests.get")
    def test_symbol_slash_stripped_for_rest(self, mock_get):
        """ATOM/USD must be sent as ATOMUSD in the REST request."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = FAKE_KRAKEN_RESPONSE
        mock_get.return_value = mock_resp

        backfill = KrakenBackfill(base_url="https://api.kraken.com")
        backfill.fetch(symbol="ATOM/USD", timeframe="5", count=2)

        params = mock_get.call_args.kwargs["params"]
        assert params["pair"] == "ATOMUSD"

    @patch("data.backfill.requests.get")
    def test_fetch_no_auth_headers(self, mock_get):
        """Kraken public API — no Authorization header should be sent."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = FAKE_KRAKEN_RESPONSE
        mock_get.return_value = mock_resp

        backfill = KrakenBackfill(base_url="https://api.kraken.com")
        backfill.fetch(symbol="ATOM/USD", timeframe="5", count=2)

        call_kwargs = mock_get.call_args.kwargs
        # No headers kwarg should be passed (or if present, no Authorization key)
        headers = call_kwargs.get("headers", {})
        assert "Authorization" not in headers

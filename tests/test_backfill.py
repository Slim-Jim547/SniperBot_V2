import pytest
from unittest.mock import patch, MagicMock
from data.backfill import CoinbaseBackfill, parse_candles, GRANULARITY_MAP
from models import Candle


FAKE_API_RESPONSE = {
    "candles": [
        {
            "start": "1700000300",
            "low": "9.80",
            "high": "10.20",
            "open": "9.90",
            "close": "10.10",
            "volume": "500.0",
        },
        {
            "start": "1700000000",
            "low": "9.70",
            "high": "10.00",
            "open": "9.75",
            "close": "9.90",
            "volume": "400.0",
        },
    ]
}


class TestGranularityMap:
    def test_five_minute_maps_correctly(self):
        assert GRANULARITY_MAP["5"] == "FIVE_MINUTE"

    def test_one_hour_maps_correctly(self):
        assert GRANULARITY_MAP["60"] == "ONE_HOUR"


class TestParseCandles:
    def test_parse_returns_candle_list(self):
        candles = parse_candles(FAKE_API_RESPONSE["candles"], symbol="ATOM-USD")
        assert len(candles) == 2
        assert all(isinstance(c, Candle) for c in candles)

    def test_parse_sorts_ascending_by_timestamp(self):
        candles = parse_candles(FAKE_API_RESPONSE["candles"], symbol="ATOM-USD")
        assert candles[0].timestamp < candles[1].timestamp

    def test_parse_correct_ohlcv_values(self):
        candles = parse_candles(FAKE_API_RESPONSE["candles"], symbol="ATOM-USD")
        # Older candle first (timestamp 1700000000)
        c = candles[0]
        assert c.open == 9.75
        assert c.high == 10.00
        assert c.low == 9.70
        assert c.close == 9.90
        assert c.volume == 400.0
        assert c.symbol == "ATOM-USD"

    def test_parse_sets_correct_symbol(self):
        candles = parse_candles(FAKE_API_RESPONSE["candles"], symbol="BTC-USD")
        assert all(c.symbol == "BTC-USD" for c in candles)


class TestCoinbaseBackfillFetch:
    @patch("data.backfill.requests.get")
    def test_fetch_returns_candles(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = FAKE_API_RESPONSE
        mock_get.return_value = mock_resp

        backfill = CoinbaseBackfill(
            api_key="test_key",
            api_secret="test_secret",
            base_url="https://api.coinbase.com",
        )
        candles = backfill.fetch(
            symbol="ATOM-USD", timeframe="5", count=2
        )
        assert len(candles) == 2
        assert mock_get.called

    @patch("data.backfill.requests.get")
    def test_fetch_raises_on_non_200(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_get.return_value = mock_resp

        backfill = CoinbaseBackfill(
            api_key="bad_key",
            api_secret="bad_secret",
            base_url="https://api.coinbase.com",
        )
        with pytest.raises(RuntimeError, match="Coinbase API error"):
            backfill.fetch(symbol="ATOM-USD", timeframe="5", count=2)

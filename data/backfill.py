"""
data/backfill.py

Fetches historical OHLCV candles from Kraken public REST API.
No authentication required — Kraken public endpoints are open.
Called once on startup to warm up indicator buffers.
"""

import logging
import time

import requests

from models import Candle

logger = logging.getLogger(__name__)

_SECONDS_PER_CANDLE = {
    "1": 60, "5": 300, "15": 900, "30": 1800,
    "60": 3600, "240": 14400, "1440": 86400,
    "10080": 604800, "21600": 2592000,
}

_KRAKEN_MAX_CANDLES = 720


def parse_candles(raw: list, symbol: str) -> list:
    """Parse raw Kraken OHLC rows into Candle objects, sorted ascending.

    Kraken row format: [time, open, high, low, close, vwap, volume, count]
    """
    candles = [
        Candle(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[6]),   # index 5 is vwap, 6 is volume
            symbol=symbol,
        )
        for row in raw
    ]
    return sorted(candles, key=lambda c: c.timestamp)


class KrakenBackfill:
    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")

    def _fetch_chunk(self, pair: str, interval: int, since: int) -> list:
        """Fetch one page of OHLC data from Kraken.

        pair:     REST symbol, e.g. "ATOMUSD"
        interval: candle interval in minutes
        since:    unix timestamp — returns candles at or after this time
        """
        url = f"{self._base_url}/0/public/OHLC"
        params = {"pair": pair, "interval": interval, "since": since}
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            raise RuntimeError(
                f"Kraken API error {response.status_code}: {response.text}"
            )
        data = response.json()
        if data.get("error"):
            raise RuntimeError(f"Kraken API returned errors: {data['error']}")

        result = data.get("result", {})
        # Kraken key is usually the pair name (e.g. "ATOMUSD" or "XATOMZUSD").
        # Try the exact pair first; fall back to any key that isn't "last".
        rows = result.get(pair) or next(
            (v for k, v in result.items() if k != "last"), []
        )
        return rows or []

    def fetch(
        self, symbol: str, timeframe: str, count: int, max_per_request: int = 720
    ) -> list:
        """
        Fetch `count` historical candles for `symbol` at `timeframe` (minutes).

        symbol: canonical slash format, e.g. "ATOM/USD"
        Returns candles sorted oldest -> newest.
        """
        candle_seconds = _SECONDS_PER_CANDLE.get(timeframe)
        if candle_seconds is None:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}'. "
                f"Supported: {list(_SECONDS_PER_CANDLE.keys())}"
            )
        interval = int(timeframe)
        pair = symbol.replace("/", "")          # "ATOM/USD" -> "ATOMUSD"
        chunk_limit = min(max_per_request, _KRAKEN_MAX_CANDLES)

        now = int(time.time())
        since = now - count * candle_seconds    # start of our desired range

        all_candles: list = []

        while len(all_candles) < count:
            raw = self._fetch_chunk(pair, interval, since)
            if not raw:
                break
            chunk = parse_candles(raw, symbol)
            all_candles.extend(chunk)

            if len(chunk) < chunk_limit:
                # Fewer rows than max — no more historical data available
                break

            # Advance past the last candle received for the next request
            since = chunk[-1].timestamp + candle_seconds
            if since >= now:
                break

        # Deduplicate and sort
        seen: set = set()
        unique: list = []
        for c in sorted(all_candles, key=lambda x: x.timestamp):
            if c.timestamp not in seen:
                seen.add(c.timestamp)
                unique.append(c)

        # Return only the most recent `count` candles
        result = unique[-count:] if len(unique) > count else unique
        logger.info("Backfilled %s candles for %s", len(result), symbol)
        return result

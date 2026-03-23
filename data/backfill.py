"""
data/backfill.py

Fetches historical OHLCV candles from Coinbase Advanced Trade REST API.
Called once on startup to warm up indicator buffers.
"""

import hashlib
import hmac
import logging
import time
from typing import Optional

import requests

from models import Candle

logger = logging.getLogger(__name__)

GRANULARITY_MAP = {
    "1":    "ONE_MINUTE",
    "5":    "FIVE_MINUTE",
    "15":   "FIFTEEN_MINUTE",
    "30":   "THIRTY_MINUTE",
    "60":   "ONE_HOUR",
    "120":  "TWO_HOUR",
    "360":  "SIX_HOUR",
    "1440": "ONE_DAY",
}

_SECONDS_PER_CANDLE = {
    "1": 60, "5": 300, "15": 900, "30": 1800,
    "60": 3600, "120": 7200, "360": 21600, "1440": 86400,
}

_COINBASE_HARD_LIMIT = 350  # Coinbase enforces this regardless of what we ask for


def parse_candles(raw: list, symbol: str) -> list:
    """Parse raw Coinbase candle dicts into Candle objects, sorted ascending."""
    candles = [
        Candle(
            timestamp=int(c["start"]),
            open=float(c["open"]),
            high=float(c["high"]),
            low=float(c["low"]),
            close=float(c["close"]),
            volume=float(c["volume"]),
            symbol=symbol,
        )
        for c in raw
    ]
    return sorted(candles, key=lambda c: c.timestamp)


class CoinbaseBackfill:
    def __init__(self, api_key: str, api_secret: str, base_url: str):
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")

    def _auth_headers(self, method: str, path: str) -> dict:
        ts = str(int(time.time()))
        message = ts + method.upper() + path
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            message.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        return {
            "CB-ACCESS-KEY": self._api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }

    def _fetch_chunk(
        self, symbol: str, granularity: str, start: int, end: int
    ) -> list:
        path = f"/api/v3/brokerage/products/{symbol}/candles"
        params = f"start={start}&end={end}&granularity={granularity}"
        full_path = f"{path}?{params}"
        headers = self._auth_headers("GET", full_path)
        url = self._base_url + full_path
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            raise RuntimeError(
                f"Coinbase API error {response.status_code}: {response.text}"
            )
        return response.json().get("candles", [])

    def fetch(
        self, symbol: str, timeframe: str, count: int, max_per_request: int = 300
    ) -> list:
        """
        Fetch `count` historical candles for `symbol` at `timeframe` (minutes).
        max_per_request comes from config.yaml backfill.max_per_request.
        Makes multiple requests if count > max_per_request.
        Returns candles sorted oldest -> newest.
        """
        granularity = GRANULARITY_MAP[timeframe]
        candle_seconds = _SECONDS_PER_CANDLE[timeframe]
        chunk_limit = min(max_per_request, _COINBASE_HARD_LIMIT)
        now = int(time.time())
        all_candles = []

        remaining = count
        end_ts = now
        while remaining > 0:
            chunk_size = min(remaining, chunk_limit)
            start_ts = end_ts - chunk_size * candle_seconds
            raw = self._fetch_chunk(symbol, granularity, start_ts, end_ts)
            chunk = parse_candles(raw, symbol)
            all_candles = chunk + all_candles
            end_ts = start_ts
            remaining -= chunk_size

        # Deduplicate and sort
        seen = set()
        unique = []
        for c in sorted(all_candles, key=lambda x: x.timestamp):
            if c.timestamp not in seen:
                seen.add(c.timestamp)
                unique.append(c)

        logger.info(f"Backfilled {len(unique)} candles for {symbol}")
        return unique

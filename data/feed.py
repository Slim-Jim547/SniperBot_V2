"""
data/feed.py

WebSocket connection to Coinbase Advanced Trade.
Subscribes to market_trades channel.
Aggregates individual trades into OHLCV candles.
Calls on_candle_close(candle) whenever a candle period completes.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

import websockets

from models import Candle

logger = logging.getLogger(__name__)


def parse_trade_message(msg: dict) -> list:
    """
    Extract trade dicts from a Coinbase market_trades WebSocket message.
    Returns empty list for non-trade messages.
    """
    if msg.get("channel") != "market_trades":
        return []
    trades = []
    for event in msg.get("events", []):
        for trade in event.get("trades", []):
            trades.append({
                "price": float(trade["price"]),
                "size": float(trade["size"]),
                "side": trade["side"],
                "time": trade["time"],
            })
    return trades


def _candle_bucket(timestamp: int, timeframe_seconds: int) -> int:
    """Return the start of the candle period containing this timestamp."""
    return (timestamp // timeframe_seconds) * timeframe_seconds


class CandleBuilder:
    """
    Aggregates individual trade ticks into OHLCV candles.

    on_candle_close is called with the completed Candle when a new
    timeframe period begins.
    """

    def __init__(
        self,
        symbol: str,
        timeframe_minutes: int,
        on_candle_close: Callable,
    ):
        self._symbol = symbol
        self._tf_seconds = timeframe_minutes * 60
        self._on_close = on_candle_close
        self._bucket: Optional[int] = None
        self.current_open: Optional[float] = None
        self.current_high: Optional[float] = None
        self.current_low: Optional[float] = None
        self.current_close: Optional[float] = None
        self.current_volume: float = 0.0

    def process_trade(self, price: float, size: float, timestamp: int):
        """Process a single trade. Fires callback if candle period rolled over."""
        bucket = _candle_bucket(timestamp, self._tf_seconds)

        if self._bucket is None:
            # First trade ever
            self._start_new_candle(bucket, price, size)
            return

        if bucket > self._bucket:
            # New candle period — close current and start fresh
            self._close_candle()
            self._start_new_candle(bucket, price, size)
        else:
            # Same period — update running OHLCV
            self.current_high = max(self.current_high, price)
            self.current_low = min(self.current_low, price)
            self.current_close = price
            self.current_volume += size

    def _start_new_candle(self, bucket: int, price: float, size: float):
        self._bucket = bucket
        self.current_open = price
        self.current_high = price
        self.current_low = price
        self.current_close = price
        self.current_volume = size

    def _close_candle(self):
        if self.current_open is None:
            return
        candle = Candle(
            timestamp=self._bucket,
            open=self.current_open,
            high=self.current_high,
            low=self.current_low,
            close=self.current_close,
            volume=self.current_volume,
            symbol=self._symbol,
        )
        logger.debug(f"Candle closed: {candle}")
        self._on_close(candle)


class CoinbaseFeed:
    """
    Manages the WebSocket connection to Coinbase Advanced Trade.
    Reconnects automatically on disconnect.
    """

    def __init__(
        self,
        ws_url: str,
        symbol: str,
        timeframe_minutes: int,
        on_candle_close: Callable,
    ):
        self._ws_url = ws_url
        self._symbol = symbol
        self._builder = CandleBuilder(symbol, timeframe_minutes, on_candle_close)

    async def run(self):
        """Connect and stream forever. Reconnects on error."""
        while True:
            try:
                await self._connect()
            except Exception as exc:
                logger.error(f"WebSocket error: {exc}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def _connect(self):
        logger.info(f"Connecting to {self._ws_url}")
        async with websockets.connect(self._ws_url) as ws:
            subscribe_msg = json.dumps({
                "type": "subscribe",
                "product_ids": [self._symbol],
                "channel": "market_trades",
            })
            await ws.send(subscribe_msg)
            logger.info(f"Subscribed to market_trades for {self._symbol}")

            async for raw in ws:
                msg = json.loads(raw)
                for trade in parse_trade_message(msg):
                    ts = int(
                        datetime.fromisoformat(
                            trade["time"].replace("Z", "+00:00")
                        ).timestamp()
                    )
                    self._builder.process_trade(trade["price"], trade["size"], ts)

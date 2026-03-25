"""
data/feed.py

WebSocket connection to Kraken public market data.
Subscribes to the ohlc channel for a trading pair.
Emits a completed Candle when a new candle period begins.

Kraken sends continuous OHLC updates for the current candle. When beginTime
changes in a new message, the previous candle is complete and gets emitted.
No authentication required.
"""

import asyncio
import json
import logging
from typing import Callable, Optional

import websockets

from models import Candle

logger = logging.getLogger(__name__)


def parse_ohlc_message(msg) -> Optional[dict]:
    """
    Parse a Kraken WebSocket message and extract OHLC data if present.

    Kraken OHLC message format:
    [channelID, [beginTime, endTime, open, high, low, close, vwap, volume, count], "ohlc-5", "ATOM/USD"]

    Dict messages are events (heartbeat, subscriptionStatus, systemStatus) — ignored.
    Returns a dict with OHLC fields, or None for non-OHLC messages.
    """
    # Event dicts (heartbeat, subscriptionStatus, etc.) — skip
    if isinstance(msg, dict):
        return None

    # OHLC data arrives as a 4-element list
    if not isinstance(msg, list) or len(msg) != 4:
        return None

    channel_name = msg[2]
    if not isinstance(channel_name, str) or not channel_name.startswith("ohlc"):
        return None

    ohlc = msg[1]
    return {
        "begin_time": float(ohlc[0]),
        "end_time":   float(ohlc[1]),
        "open":       float(ohlc[2]),
        "high":       float(ohlc[3]),
        "low":        float(ohlc[4]),
        "close":      float(ohlc[5]),
        "vwap":       float(ohlc[6]),
        "volume":     float(ohlc[7]),
        "pair":       msg[3],
    }


class KrakenFeed:
    """
    Manages the WebSocket connection to Kraken public market data.
    Subscribes to the ohlc channel and emits complete Candle objects.

    A candle is considered complete when the next OHLC update carries a
    different beginTime — at that point the previous candle is emitted.
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
        self._symbol = symbol               # e.g. "ATOM/USD"
        self._interval = timeframe_minutes
        self._on_close = on_candle_close

        # Current candle state
        self._last_begin_time: Optional[float] = None
        self._current: Optional[dict] = None

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
                "event": "subscribe",
                "pair": [self._symbol],
                "subscription": {"name": "ohlc", "interval": self._interval},
            })
            await ws.send(subscribe_msg)
            logger.info(f"Subscribed to ohlc-{self._interval} for {self._symbol}")

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                ohlc = parse_ohlc_message(msg)
                if ohlc is None:
                    continue

                self._process_ohlc(ohlc)

    def _process_ohlc(self, ohlc: dict):
        """Process an OHLC update. Emits the previous candle when the period rolls over."""
        begin_time = ohlc["begin_time"]

        if self._last_begin_time is None:
            # First update — initialise state, nothing to emit yet
            self._last_begin_time = begin_time
            self._current = ohlc
            return

        if begin_time != self._last_begin_time:
            # New candle period started — emit the just-completed candle
            self._emit_candle()
            self._last_begin_time = begin_time

        # Store the latest update for the current period (overwrites in-progress candle)
        self._current = ohlc

    def _emit_candle(self):
        if self._current is None:
            return
        candle = Candle(
            timestamp=int(self._last_begin_time),
            open=self._current["open"],
            high=self._current["high"],
            low=self._current["low"],
            close=self._current["close"],
            volume=self._current["volume"],
            symbol=self._symbol,
        )
        logger.debug(f"Candle closed: {candle}")
        self._on_close(candle)

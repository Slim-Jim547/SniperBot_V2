"""
core/trade_manager.py

Manages the ATR trailing stop for an open position.
The stop level is set when the trade opens and only moves UP on each candle close.

Hard Rule 6: stop level updates on candle close ONLY — never intra-candle.
Call update() once per candle close when IN_TRADE, then call is_stopped()
to determine whether the position should be exited.
"""


class TradeManager:
    def __init__(self):
        self._stop_price: float = 0.0
        self._is_active: bool = False

    @property
    def stop_price(self) -> float:
        """Current trailing stop price."""
        return self._stop_price

    @property
    def is_active(self) -> bool:
        """True when a trade is open and the stop is tracking."""
        return self._is_active

    def open_trade(self, entry_price: float, atr: float, multiplier: float) -> None:
        """Set initial stop when a trade opens. stop = entry_price - multiplier * atr."""
        self._stop_price = entry_price - multiplier * atr
        self._is_active = True

    def update(self, candle_close: float, atr: float, multiplier: float) -> None:
        """
        Update stop on candle close. Only ever moves the stop UP.
        Call once per closed candle while IN_TRADE.
        """
        if not self._is_active:
            return
        candidate = candle_close - multiplier * atr
        if candidate > self._stop_price:
            self._stop_price = candidate

    def is_stopped(self, candle_close: float) -> bool:
        """True if candle_close has fallen to or below the trailing stop."""
        return self._is_active and candle_close <= self._stop_price

    def close_trade(self) -> None:
        """Reset after trade closes."""
        self._stop_price = 0.0
        self._is_active = False

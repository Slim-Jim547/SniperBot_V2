"""
core/state_machine.py

Manages trade lifecycle. No strategy logic lives here.
The main loop evaluates strategies and passes signals via on_entry_signal()
and on_exit_signal(). This module only handles state transitions.

States:
    IDLE      → watching for first entry signal
    WATCHING  → signal detected; waiting for same-strategy confirmation
    IN_TRADE  → position is open
    CLOSING   → exit order placed (transient; resolves to IDLE instantly in paper mode)
"""

import logging
from enum import Enum
from typing import Optional
from models import Candle

logger = logging.getLogger(__name__)


class TradeState(Enum):
    IDLE     = "IDLE"
    WATCHING = "WATCHING"
    IN_TRADE = "IN_TRADE"
    CLOSING  = "CLOSING"


class StateMachine:
    # TODO: move to cfg["strategies"]["confirmation_candles"] — CLAUDE.md requires no hardcoded values
    MAX_WATCH_CANDLES = 3  # auto-cancel WATCHING after this many ticks with no confirmation

    def __init__(self):
        self.state: TradeState = TradeState.IDLE
        self._strategy_name: Optional[str] = None
        self._watch_count: int = 0
        self.trade_id: Optional[int] = None

    @property
    def active_strategy_name(self) -> Optional[str]:
        return self._strategy_name

    def on_entry_signal(
        self,
        strategy_name: str,
        candle: Candle,
        broker,
        db,
        cfg: dict,
        symbol: str,
        regime_label: str,
    ) -> bool:
        """
        Call when a strategy's should_enter() returns True.
        Returns True only when a trade is actually opened (confirmation candle).
        """
        if self.state == TradeState.IDLE:
            self.state = TradeState.WATCHING
            self._strategy_name = strategy_name
            self._watch_count = 0
            return False

        if self.state == TradeState.WATCHING and self._strategy_name == strategy_name:
            # Confirmation — open the trade
            if candle.close <= 0:
                raise ValueError(f"candle.close must be positive, got {candle.close}")
            size = cfg["risk"]["notional_size"] / candle.close
            broker.set_fill_price(candle.close, candle.timestamp)
            result = broker.place_order(symbol, "buy", size, "market")
            self.trade_id = db.insert_trade(
                symbol=symbol,
                strategy=strategy_name,
                regime=regime_label,
                side="buy",
                entry_price=result.fill_price,
                size=result.size,
                entry_time=candle.timestamp,
            )
            self.state = TradeState.IN_TRADE
            self._watch_count = 0
            return True

        # Different strategy while WATCHING — ignore
        return False

    def on_exit_signal(
        self,
        candle: Candle,
        broker,
        db,
        symbol: str,
    ) -> None:
        """
        Call when the active strategy's should_exit() returns True.
        Closes the position and returns to IDLE.
        """
        if self.state != TradeState.IN_TRADE or self.trade_id is None:
            return

        self.state = TradeState.CLOSING
        position = broker.get_position(symbol)
        if position is None:
            logger.error(
                "on_exit_signal called but no position found for %s — "
                "trade %s will remain open in DB", symbol, self.trade_id
            )
        else:
            broker.set_fill_price(candle.close, candle.timestamp)
            result = broker.place_order(symbol, "sell", position.size, "market")
            pnl = (result.fill_price - position.entry_price) * position.size
            db.close_trade(self.trade_id, result.fill_price, candle.timestamp, pnl)

        self.trade_id = None
        self._strategy_name = None
        self.state = TradeState.IDLE

    def tick(self) -> None:
        """
        Call once per candle close (after signal processing).
        Advances the WATCHING timeout counter; returns to IDLE if expired.
        """
        if self.state == TradeState.WATCHING:
            self._watch_count += 1
            if self._watch_count >= self.MAX_WATCH_CANDLES:
                self.state = TradeState.IDLE
                self._strategy_name = None
                self._watch_count = 0

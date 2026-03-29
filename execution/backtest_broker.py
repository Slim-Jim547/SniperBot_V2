"""
execution/backtest_broker.py

Backtesting broker — implements BrokerBase for offline replay.
Fills at candle close price adjusted for slippage, minus fee based on order_type.

order_type="market" → taker fee
order_type="limit"  → maker fee
"""

import uuid
from typing import Optional

from execution.broker_base import BrokerBase
from models import OrderResult, Position


class BacktestBroker(BrokerBase):
    def __init__(
        self,
        initial_balance: float,
        maker_fee: float,
        taker_fee: float,
        slippage_pct: float,
    ):
        self._balance = initial_balance
        self._maker_fee = maker_fee
        self._taker_fee = taker_fee
        self._slippage_pct = slippage_pct
        self._position: Optional[Position] = None
        self._fill_price: float = 0.0
        self._fill_timestamp: int = 0

    def set_fill_price(self, price: float, timestamp: int) -> None:
        """Called by the state machine before place_order — same contract as PaperBroker."""
        self._fill_price = price
        self._fill_timestamp = timestamp

    def place_order(
        self, symbol: str, side: str, size: float, order_type: str
    ) -> OrderResult:
        fee_rate = self._taker_fee if order_type == "market" else self._maker_fee

        if side == "buy":
            fill_price = self._fill_price * (1.0 + self._slippage_pct)
            notional = fill_price * size
            fee = notional * fee_rate
            if self._balance < notional + fee:
                raise ValueError("Insufficient balance")
            self._balance -= notional + fee
            self._position = Position(
                symbol=symbol,
                side="long",
                size=size,
                entry_price=fill_price,
                entry_time=self._fill_timestamp,
            )
        else:  # sell
            if self._position is None:
                raise ValueError(f"No open position for {symbol} — cannot sell")
            fill_price = self._fill_price * (1.0 - self._slippage_pct)
            notional = fill_price * size
            fee = notional * fee_rate
            self._balance += notional - fee
            self._position = None

        return OrderResult(
            order_id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            size=size,
            fill_price=fill_price,
            timestamp=self._fill_timestamp,
        )

    def get_position(self, symbol: str) -> Optional[Position]:
        if self._position and self._position.symbol == symbol:
            return self._position
        return None

    def get_account_balance(self) -> float:
        return self._balance

    def cancel_order(self, order_id: str) -> bool:
        """Backtest fills are instant — cancellation is always a no-op."""
        return False

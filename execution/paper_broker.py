"""
execution/paper_broker.py

Simulated broker. Fills are instant at the price set by set_fill_price().
No API calls. Tracks balance and positions in memory.
"""

from typing import Optional
from models import OrderResult, Position
from execution.broker_base import BrokerBase


class PaperBroker(BrokerBase):
    def __init__(self, initial_balance: float):
        self._balance: float = initial_balance
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, OrderResult] = {}
        self._fill_price: float = 0.0
        self._fill_timestamp: int = 0
        self._order_counter: int = 0

    def set_fill_price(self, price: float, timestamp: int) -> None:
        """Call once per candle close before placing any orders."""
        self._fill_price = price
        self._fill_timestamp = timestamp

    def place_order(
        self, symbol: str, side: str, size: float, order_type: str
    ) -> OrderResult:
        # order_type is accepted for interface compatibility but ignored in paper mode —
        # all fills execute at set_fill_price() regardless of order type.
        if self._fill_price == 0.0:
            raise RuntimeError("set_fill_price() must be called before place_order()")
        self._order_counter += 1
        order_id = f"paper_{self._order_counter}"

        if side == "buy":
            cost = size * self._fill_price
            self._balance -= cost
            self._positions[symbol] = Position(
                symbol=symbol,
                side="long",
                size=size,
                entry_price=self._fill_price,
                entry_time=self._fill_timestamp,
            )
        else:  # sell
            position = self._positions.get(symbol)
            if position is None:
                raise ValueError(f"No open position for {symbol} — cannot sell")
            size = min(size, position.size)  # clamp to position size
            proceeds = size * self._fill_price
            self._balance += proceeds
            self._positions.pop(symbol, None)

        result = OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            size=size,
            fill_price=self._fill_price,
            timestamp=self._fill_timestamp,
        )
        self._orders[order_id] = result
        return result

    def get_position(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)

    def get_account_balance(self) -> float:
        return self._balance

    def cancel_order(self, order_id: str) -> bool:
        """Paper mode: removes the order record only. Balance and position are NOT
        reversed — fills are instant and cannot be undone."""
        if order_id in self._orders:
            del self._orders[order_id]
            return True
        return False

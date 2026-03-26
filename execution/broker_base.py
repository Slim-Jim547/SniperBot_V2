"""
execution/broker_base.py

Abstract broker interface. Both PaperBroker and LiveBroker implement
this exact contract. Switching from paper to live is one line in config.yaml.
"""

from abc import ABC, abstractmethod
from typing import Optional
from models import OrderResult, Position


class BrokerBase(ABC):
    @abstractmethod
    def place_order(
        self, symbol: str, side: str, size: float, order_type: str
    ) -> OrderResult:
        """
        Place a market or limit order.
        Args:
            symbol:     e.g. "ATOM/USD"
            side:       "buy" | "sell"
            size:       units to trade (not USD notional)
            order_type: "market" | "limit"
        Returns:
            OrderResult with actual fill details
        """
        ...

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Position]:
        """Return the open position for symbol, or None."""
        ...

    @abstractmethod
    def get_account_balance(self) -> float:
        """Return current USD account balance."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an unfilled order. Returns True if found and cancelled."""
        ...

    @abstractmethod
    def set_fill_price(self, price: float, timestamp: int) -> None:
        """
        Inform the broker of the current candle's close price before placing orders.
        Paper: uses this price for all fills.
        Live: may be used for slippage modeling or ignored; actual fill price
              comes back from the exchange via OrderResult.fill_price.
        """
        ...

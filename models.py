from dataclasses import dataclass


@dataclass
class Candle:
    timestamp: int    # Unix timestamp of candle open
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str

    def is_bullish(self) -> bool:
        return self.close >= self.open

    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str        # "buy" | "sell"
    size: float
    fill_price: float
    timestamp: int


@dataclass
class Position:
    symbol: str
    side: str        # "long" (Phase 2 is long-only)
    size: float
    entry_price: float
    entry_time: int

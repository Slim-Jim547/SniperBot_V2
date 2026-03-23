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

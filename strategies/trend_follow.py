"""
strategies/trend_follow.py

Entry: EMA stack aligned (fast > slow > trend) + ADX above minimum + RSI not overbought.
Exit:  Fast EMA crosses below slow EMA.

Regime filter: only enters on TRENDING.
"""

from typing import Optional
from strategies.base_strategy import BaseStrategy
from core.regime_detector import RegimeLabel
from models import Position


class TrendFollowStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "trend_follow"

    def should_enter(
        self, indicators: dict, regime: RegimeLabel, cfg: dict
    ) -> bool:
        if regime != RegimeLabel.TRENDING:
            return False

        tf_cfg = cfg["strategies"]["trend_follow"]

        if tf_cfg["ema_alignment_required"]:
            aligned = (
                indicators["ema_fast"] > indicators["ema_slow"] > indicators["ema_trend"]
            )
            if not aligned:
                return False

        if indicators["adx"] < tf_cfg["adx_min"]:
            return False

        if indicators["rsi"] >= 70:
            return False

        return True

    def should_exit(
        self,
        indicators: dict,
        regime: RegimeLabel,
        position: Optional[Position],
        cfg: dict,
    ) -> bool:
        return indicators["ema_fast"] < indicators["ema_slow"]

"""
strategies/momentum.py

Entry: Bollinger Band squeeze for N candles, then breakout above upper band.
Exit:  Price crosses back below BB middle.

Regime filter: only enters on BREAKOUT.
The strategy tracks its own bb_width_pct history because should_enter() only
receives the current scalar values, not a window of history.
"""

from collections import deque
from typing import Optional
from strategies.base_strategy import BaseStrategy
from core.regime_detector import RegimeLabel
from models import Position


class MomentumStrategy(BaseStrategy):
    def __init__(self):
        # maxlen = squeeze_periods * 3 gives comfortable headroom
        self._bb_history: deque = deque(maxlen=30)

    @property
    def name(self) -> str:
        return "momentum"

    def should_enter(
        self, indicators: dict, regime: RegimeLabel, cfg: dict
    ) -> bool:
        # Always record history first (even when regime is wrong)
        self._bb_history.append(indicators["bb_width_pct"])

        if regime != RegimeLabel.BREAKOUT:
            return False

        squeeze_periods = cfg["strategies"]["momentum"]["bb_squeeze_periods"]
        squeeze_thresh = cfg["regime"]["bb_squeeze_threshold"]

        # Need current candle + squeeze_periods candles before it
        if len(self._bb_history) < squeeze_periods + 1:
            return False

        # Check the N candles BEFORE the current one were all in squeeze
        pre_current = list(self._bb_history)[-(squeeze_periods + 1):-1]
        if not all(w < squeeze_thresh for w in pre_current):
            return False

        # Price must break above upper band by at least atr_mult * ATR
        atr_mult = cfg["strategies"]["momentum"]["breakout_atr_multiplier"]
        return indicators["close"] > indicators["bb_upper"] + atr_mult * indicators["atr"]

    def should_exit(
        self,
        indicators: dict,
        regime: RegimeLabel,
        position: Optional[Position],
        cfg: dict,
    ) -> bool:
        return indicators["close"] < indicators["bb_middle"]

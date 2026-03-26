"""
strategies/base_strategy.py

Abstract base class for all trading strategies.
Strategies receive pre-computed indicator scalars and the current regime.
They return a boolean — no order placement, no DB access, no broker calls.
"""

from abc import ABC, abstractmethod
from typing import Optional
from core.regime_detector import RegimeLabel
from models import Position


class BaseStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique lowercase identifier used in logging and DB records."""
        ...

    @abstractmethod
    def should_enter(
        self, indicators: dict, regime: RegimeLabel, cfg: dict
    ) -> bool:
        """
        Return True when an entry signal fires.
        Args:
            indicators: scalar dict from compute_all() with "close" added by main loop
            regime:     current RegimeLabel
            cfg:        full config dict
        """
        ...

    @abstractmethod
    def should_exit(
        self,
        indicators: dict,
        regime: RegimeLabel,
        position: Optional[Position],
        cfg: dict,
    ) -> bool:
        """
        Return True when the open position should be closed.
        Args:
            indicators: same format as should_enter
            regime:     current RegimeLabel
            position:   the open Position (may be None if called defensively)
            cfg:        full config dict
        """
        ...

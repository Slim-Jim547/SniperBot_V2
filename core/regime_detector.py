"""
core/regime_detector.py

Classifies the current market regime from pre-computed indicator scalars.
Input: indicator dict (from compute_all) + full cfg dict.
Output: RegimeLabel enum.

Priority order (most specific first):
  BREAKOUT  — high ADX + wide BB + volume surge
  TRENDING  — moderate-to-high ADX
  CHOPPY    — low ADX (below both thresholds) + squeezed BB
  RANGING   — low ADX + normal BB width
"""

from enum import Enum


class RegimeLabel(Enum):
    BREAKOUT = "BREAKOUT"
    TRENDING = "TRENDING"
    RANGING  = "RANGING"
    CHOPPY   = "CHOPPY"


class RegimeDetector:
    def classify(self, indicators: dict, cfg: dict) -> RegimeLabel:
        """
        Args:
            indicators: scalar dict from compute_all() — must contain
                        adx, bb_width_pct, volume_ratio
            cfg: full config dict (uses cfg["regime"] sub-section)
        Returns:
            RegimeLabel

        Note: Caller must guarantee adx, bb_width_pct, and volume_ratio keys
              are present (warm-up must be complete before calling).
        """
        adx       = indicators["adx"]
        bb_w      = indicators["bb_width_pct"]
        vol_ratio = indicators["volume_ratio"]
        rcfg      = cfg["regime"]

        # BREAKOUT: all three signals must fire
        if (adx >= rcfg["adx_breakout_threshold"]
                and bb_w > rcfg["bb_squeeze_threshold"]
                and vol_ratio >= rcfg["volume_surge_ratio"]):
            return RegimeLabel.BREAKOUT

        # TRENDING: directional momentum present
        if adx >= rcfg["adx_trending_threshold"]:
            return RegimeLabel.TRENDING

        # Low ADX — differentiate by BB width
        if bb_w <= rcfg["bb_squeeze_threshold"]:
            return RegimeLabel.CHOPPY

        return RegimeLabel.RANGING

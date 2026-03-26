import pytest
from core.regime_detector import RegimeDetector, RegimeLabel


CFG = {
    "regime": {
        "adx_trending_threshold": 25,
        "adx_breakout_threshold": 30,
        "bb_squeeze_threshold": 0.02,
        "volume_surge_ratio": 1.5,
    }
}


def _inds(adx, bb_width_pct, volume_ratio):
    return {"adx": adx, "bb_width_pct": bb_width_pct, "volume_ratio": volume_ratio}


class TestRegimeDetector:
    def setup_method(self):
        self.detector = RegimeDetector()

    def test_breakout_all_conditions_met(self):
        # ADX >= 30, wide BB, volume surge
        inds = _inds(32, 0.05, 2.0)
        assert self.detector.classify(inds, CFG) == RegimeLabel.BREAKOUT

    def test_breakout_requires_volume_surge(self):
        # ADX >= 30 + wide BB but no surge → TRENDING
        inds = _inds(32, 0.05, 1.0)
        assert self.detector.classify(inds, CFG) == RegimeLabel.TRENDING

    def test_breakout_requires_wide_bb(self):
        # ADX >= 30 + volume surge but BB in squeeze → TRENDING
        inds = _inds(32, 0.01, 2.0)
        assert self.detector.classify(inds, CFG) == RegimeLabel.TRENDING

    def test_trending_moderate_adx(self):
        # ADX >= 25 but not breakout
        inds = _inds(27, 0.05, 1.0)
        assert self.detector.classify(inds, CFG) == RegimeLabel.TRENDING

    def test_trending_at_threshold(self):
        # Exactly at adx_trending_threshold
        inds = _inds(25, 0.05, 1.0)
        assert self.detector.classify(inds, CFG) == RegimeLabel.TRENDING

    def test_breakout_at_adx_threshold(self):
        # ADX exactly at breakout threshold with all conditions → BREAKOUT
        inds = _inds(30, 0.05, 2.0)
        assert self.detector.classify(inds, CFG) == RegimeLabel.BREAKOUT

    def test_ranging_low_adx_wide_bb(self):
        # ADX < 25, BB not squeezed
        inds = _inds(15, 0.05, 1.0)
        assert self.detector.classify(inds, CFG) == RegimeLabel.RANGING

    def test_choppy_low_adx_squeezed_bb(self):
        # ADX < 25, BB squeezed
        inds = _inds(10, 0.01, 1.0)
        assert self.detector.classify(inds, CFG) == RegimeLabel.CHOPPY

    def test_choppy_at_squeeze_boundary(self):
        # bb_width_pct exactly at threshold → squeeze (<=)
        inds = _inds(10, 0.02, 1.0)
        assert self.detector.classify(inds, CFG) == RegimeLabel.CHOPPY

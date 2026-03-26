import pytest
from strategies.momentum import MomentumStrategy
from core.regime_detector import RegimeLabel
from models import Position


CFG = {
    "regime": {"bb_squeeze_threshold": 0.02},
    "strategies": {
        "momentum": {
            "bb_squeeze_periods": 3,
            "breakout_atr_multiplier": 0.5,
        }
    },
}


def _inds(bb_width=0.01, close=7.20, bb_upper=7.0, bb_middle=6.5, atr=0.1):
    return {
        "bb_width_pct": bb_width,
        "close": close,
        "bb_upper": bb_upper,
        "bb_middle": bb_middle,
        "atr": atr,
    }


class TestMomentumStrategy:
    def setup_method(self):
        self.strategy = MomentumStrategy()

    def _fill_squeeze_history(self, n=3):
        """Call should_enter n times with squeeze BB and RANGING regime."""
        for _ in range(n):
            self.strategy.should_enter(
                _inds(bb_width=0.01, close=6.50, bb_upper=7.0, bb_middle=6.5),
                RegimeLabel.RANGING,
                CFG,
            )

    def test_no_signal_without_enough_history(self):
        # Need squeeze_periods+1 total calls; with only 2 RANGING + 1 BREAKOUT = 3 < 4
        self._fill_squeeze_history(2)
        result = self.strategy.should_enter(
            _inds(bb_width=0.01, close=7.11, bb_upper=7.0, bb_middle=6.5, atr=0.1),
            RegimeLabel.BREAKOUT,
            CFG,
        )
        assert result is False

    def test_enter_after_squeeze_and_breakout(self):
        # 3 squeeze candles, then breakout:
        # close=7.11 > bb_upper(7.0) + 0.5*atr(0.1) = 7.05 → True
        self._fill_squeeze_history(3)
        result = self.strategy.should_enter(
            _inds(bb_width=0.01, close=7.11, bb_upper=7.0, bb_middle=6.5, atr=0.1),
            RegimeLabel.BREAKOUT,
            CFG,
        )
        assert result is True

    def test_no_entry_wrong_regime(self):
        self._fill_squeeze_history(3)
        result = self.strategy.should_enter(
            _inds(bb_width=0.01, close=7.11, bb_upper=7.0, bb_middle=6.5, atr=0.1),
            RegimeLabel.TRENDING,
            CFG,
        )
        assert result is False

    def test_no_entry_if_squeeze_history_broken(self):
        # One wide candle in the history window breaks the squeeze requirement
        self.strategy.should_enter(_inds(bb_width=0.01), RegimeLabel.RANGING, CFG)
        self.strategy.should_enter(_inds(bb_width=0.05), RegimeLabel.RANGING, CFG)  # wide BB
        self.strategy.should_enter(_inds(bb_width=0.01), RegimeLabel.RANGING, CFG)
        result = self.strategy.should_enter(
            _inds(bb_width=0.01, close=7.11, bb_upper=7.0, bb_middle=6.5, atr=0.1),
            RegimeLabel.BREAKOUT,
            CFG,
        )
        assert result is False

    def test_no_entry_price_not_above_upper(self):
        self._fill_squeeze_history(3)
        # close=7.04, need > 7.0 + 0.5*0.1 = 7.05
        result = self.strategy.should_enter(
            _inds(bb_width=0.01, close=7.04, bb_upper=7.0, bb_middle=6.5, atr=0.1),
            RegimeLabel.BREAKOUT,
            CFG,
        )
        assert result is False

    def test_exit_below_bb_middle(self):
        pos = Position("ATOM/USD", "long", 10.0, 7.0, 1_000)
        inds = _inds(close=6.40, bb_middle=6.50)
        assert self.strategy.should_exit(inds, RegimeLabel.RANGING, pos, CFG) is True

    def test_no_exit_above_bb_middle(self):
        pos = Position("ATOM/USD", "long", 10.0, 7.0, 1_000)
        inds = _inds(close=6.60, bb_middle=6.50)
        assert self.strategy.should_exit(inds, RegimeLabel.RANGING, pos, CFG) is False

    def test_strategy_name(self):
        assert self.strategy.name == "momentum"


from strategies.trend_follow import TrendFollowStrategy


TF_CFG = {
    "strategies": {
        "trend_follow": {
            "ema_alignment_required": True,
            "adx_min": 25,
            "rsi_overbought": 70,
        }
    }
}


def _tf_inds(ema_fast=10.0, ema_slow=9.0, ema_trend=8.0, adx=30.0, rsi=60.0):
    return {
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "ema_trend": ema_trend,
        "adx": adx,
        "rsi": rsi,
    }


class TestTrendFollowStrategy:
    def setup_method(self):
        self.strategy = TrendFollowStrategy()

    def test_enter_with_all_conditions_met(self):
        inds = _tf_inds(ema_fast=10, ema_slow=9, ema_trend=8, adx=30, rsi=60)
        assert self.strategy.should_enter(inds, RegimeLabel.TRENDING, TF_CFG) is True

    def test_no_entry_wrong_regime(self):
        inds = _tf_inds()
        assert self.strategy.should_enter(inds, RegimeLabel.BREAKOUT, TF_CFG) is False

    def test_no_entry_fast_below_slow(self):
        inds = _tf_inds(ema_fast=8, ema_slow=9, ema_trend=7)  # fast < slow
        assert self.strategy.should_enter(inds, RegimeLabel.TRENDING, TF_CFG) is False

    def test_no_entry_slow_below_trend(self):
        inds = _tf_inds(ema_fast=10, ema_slow=7, ema_trend=9)  # slow < trend
        assert self.strategy.should_enter(inds, RegimeLabel.TRENDING, TF_CFG) is False

    def test_no_entry_adx_too_low(self):
        inds = _tf_inds(adx=20)  # below adx_min=25
        assert self.strategy.should_enter(inds, RegimeLabel.TRENDING, TF_CFG) is False

    def test_no_entry_adx_at_minimum_passes(self):
        inds = _tf_inds(adx=25)  # exactly at threshold
        assert self.strategy.should_enter(inds, RegimeLabel.TRENDING, TF_CFG) is True

    def test_no_entry_rsi_overbought(self):
        inds = _tf_inds(rsi=70)  # overbought
        assert self.strategy.should_enter(inds, RegimeLabel.TRENDING, TF_CFG) is False

    def test_entry_rsi_just_below_overbought(self):
        inds = _tf_inds(rsi=69)
        assert self.strategy.should_enter(inds, RegimeLabel.TRENDING, TF_CFG) is True

    def test_exit_when_fast_crosses_below_slow(self):
        pos = Position("ATOM/USD", "long", 10.0, 7.0, 1_000)
        inds = _tf_inds(ema_fast=8, ema_slow=9)
        assert self.strategy.should_exit(inds, RegimeLabel.TRENDING, pos, TF_CFG) is True

    def test_no_exit_when_still_aligned(self):
        pos = Position("ATOM/USD", "long", 10.0, 7.0, 1_000)
        inds = _tf_inds(ema_fast=10, ema_slow=9)
        assert self.strategy.should_exit(inds, RegimeLabel.TRENDING, pos, TF_CFG) is False

    def test_strategy_name(self):
        assert self.strategy.name == "trend_follow"

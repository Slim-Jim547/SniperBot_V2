import pytest
from core.trade_manager import TradeManager


class TestTradeManager:
    def setup_method(self):
        self.tm = TradeManager()

    # --- Initial state ---

    def test_not_active_before_open(self):
        assert not self.tm.is_active

    def test_not_stopped_before_open(self):
        assert not self.tm.is_stopped(0.0)

    # --- open_trade ---

    def test_open_sets_initial_stop(self):
        self.tm.open_trade(entry_price=100.0, atr=2.0, multiplier=2.0)
        # stop = 100.0 - 2.0 * 2.0 = 96.0
        assert self.tm.stop_price == pytest.approx(96.0)

    def test_open_marks_active(self):
        self.tm.open_trade(100.0, 2.0, 2.0)
        assert self.tm.is_active

    # --- update ---

    def test_update_raises_stop_when_close_is_higher(self):
        self.tm.open_trade(100.0, 2.0, 2.0)  # stop = 96.0
        self.tm.update(candle_close=105.0, atr=2.0, multiplier=2.0)
        # new candidate = 105 - 4 = 101 > 96 → stop raises to 101
        assert self.tm.stop_price == pytest.approx(101.0)

    def test_update_does_not_lower_stop(self):
        self.tm.open_trade(100.0, 2.0, 2.0)  # stop = 96.0
        self.tm.update(candle_close=95.0, atr=2.0, multiplier=2.0)
        # candidate = 95 - 4 = 91 < 96 → stop stays at 96
        assert self.tm.stop_price == pytest.approx(96.0)

    def test_update_is_noop_when_inactive(self):
        # No open_trade call — update should not raise
        self.tm.update(50.0, 2.0, 2.0)
        assert self.tm.stop_price == 0.0

    # --- is_stopped ---

    def test_stopped_when_close_below_stop(self):
        self.tm.open_trade(100.0, 2.0, 2.0)  # stop = 96.0
        assert self.tm.is_stopped(95.9)

    def test_stopped_when_close_equals_stop(self):
        self.tm.open_trade(100.0, 2.0, 2.0)  # stop = 96.0
        assert self.tm.is_stopped(96.0)

    def test_not_stopped_when_close_above_stop(self):
        self.tm.open_trade(100.0, 2.0, 2.0)  # stop = 96.0
        assert not self.tm.is_stopped(96.1)

    def test_not_stopped_when_inactive(self):
        assert not self.tm.is_stopped(0.0)

    # --- close_trade ---

    def test_close_resets_to_inactive(self):
        self.tm.open_trade(100.0, 2.0, 2.0)
        self.tm.close_trade()
        assert not self.tm.is_active

    def test_close_resets_stop_to_zero(self):
        self.tm.open_trade(100.0, 2.0, 2.0)
        self.tm.close_trade()
        assert self.tm.stop_price == 0.0

    def test_close_prevents_false_stop_trigger(self):
        self.tm.open_trade(100.0, 2.0, 2.0)
        self.tm.close_trade()
        assert not self.tm.is_stopped(0.0)

    # --- multi-candle trail ---

    def test_stop_trails_through_multiple_candles(self):
        self.tm.open_trade(100.0, 2.0, 2.0)  # stop = 96.0
        self.tm.update(106.0, 2.0, 2.0)       # stop = 102.0
        self.tm.update(110.0, 2.0, 2.0)       # stop = 106.0
        self.tm.update(108.0, 2.0, 2.0)       # candidate = 104, stays 106
        assert self.tm.stop_price == pytest.approx(106.0)
        assert self.tm.is_stopped(105.9)

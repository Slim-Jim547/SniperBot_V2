import time
import pytest
from storage.trade_db import TradeDB
from risk.circuit_breaker import CircuitBreaker


def make_db():
    db = TradeDB(":memory:")
    db.create_tables()
    return db


def make_cfg(max_trades=10, loss_pct=3.0, cooldown_min=30):
    return {
        "risk": {
            "max_trades_per_day": max_trades,
            "daily_loss_limit_pct": loss_pct,
            "cooldown_minutes": cooldown_min,
        }
    }


class TestCircuitBreaker:
    def setup_method(self):
        self.db = make_db()
        self.cfg = make_cfg()
        self.cb = CircuitBreaker()
        self.ts = int(time.time())

    def test_allows_by_default(self):
        allowed, reason = self.cb.check(self.db, self.cfg, 10000.0, self.ts)
        assert allowed
        assert reason is None

    def test_blocks_when_max_trades_reached(self):
        for _ in range(10):
            self.cb.record_trade(self.db, pnl=5.0, current_ts=self.ts)
        allowed, reason = self.cb.check(self.db, self.cfg, 10000.0, self.ts)
        assert not allowed
        assert "max trades" in reason

    def test_allows_one_below_max_trades(self):
        for _ in range(9):
            self.cb.record_trade(self.db, pnl=5.0, current_ts=self.ts)
        allowed, _ = self.cb.check(self.db, self.cfg, 10000.0, self.ts)
        assert allowed

    def test_blocks_when_daily_loss_exceeds_limit(self):
        # 3% of $10,000 = $300 limit; record $350 loss
        self.cb.record_trade(self.db, pnl=-350.0, current_ts=self.ts)
        allowed, reason = self.cb.check(self.db, self.cfg, 10000.0, self.ts)
        assert not allowed
        assert "daily loss" in reason

    def test_allows_when_loss_below_limit(self):
        # $250 loss < $300 limit
        self.cb.record_trade(self.db, pnl=-250.0, current_ts=self.ts)
        allowed, _ = self.cb.check(self.db, self.cfg, 10000.0, self.ts)
        assert allowed

    def test_winning_trade_does_not_set_cooldown(self):
        self.cb.record_trade(self.db, pnl=50.0, current_ts=self.ts)
        # check immediately after win
        allowed, _ = self.cb.check(self.db, self.cfg, 10000.0, self.ts + 1)
        assert allowed

    def test_blocks_in_cooldown_after_loss(self):
        self.cb.record_trade(self.db, pnl=-10.0, current_ts=self.ts)
        # 5 minutes into a 30-minute cooldown
        allowed, reason = self.cb.check(self.db, self.cfg, 10000.0, self.ts + 300)
        assert not allowed
        assert "cooldown" in reason

    def test_allows_after_cooldown_expires(self):
        self.cb.record_trade(self.db, pnl=-10.0, current_ts=self.ts)
        cooldown_secs = self.cfg["risk"]["cooldown_minutes"] * 60  # 1800
        allowed, _ = self.cb.check(self.db, self.cfg, 10000.0, self.ts + cooldown_secs + 1)
        assert allowed

    def test_cooldown_reason_includes_remaining_seconds(self):
        self.cb.record_trade(self.db, pnl=-10.0, current_ts=self.ts)
        _, reason = self.cb.check(self.db, self.cfg, 10000.0, self.ts + 60)
        assert "1740" in reason  # 1800 - 60 = 1740 seconds remaining

    def test_daily_reset_clears_trade_count(self):
        for _ in range(10):
            self.cb.record_trade(self.db, pnl=5.0, current_ts=self.ts)
        # Fake yesterday's date in db
        self.db.set_state("cb_date", "1970-01-01")
        allowed, _ = self.cb.check(self.db, self.cfg, 10000.0, self.ts)
        assert allowed

    def test_daily_reset_clears_loss(self):
        self.cb.record_trade(self.db, pnl=-350.0, current_ts=self.ts)
        self.db.set_state("cb_date", "1970-01-01")
        allowed, _ = self.cb.check(self.db, self.cfg, 10000.0, self.ts)
        assert allowed

    def test_daily_reset_clears_cooldown(self):
        self.cb.record_trade(self.db, pnl=-10.0, current_ts=self.ts)
        self.db.set_state("cb_date", "1970-01-01")
        # check immediately — cooldown should be gone after reset
        allowed, _ = self.cb.check(self.db, self.cfg, 10000.0, self.ts + 1)
        assert allowed

    def test_record_trade_increments_count(self):
        self.cb.record_trade(self.db, pnl=5.0, current_ts=self.ts)
        self.cb.record_trade(self.db, pnl=5.0, current_ts=self.ts)
        assert self.db.get_state("cb_daily_trades") == "2"

    def test_record_loss_accumulates(self):
        self.cb.record_trade(self.db, pnl=-100.0, current_ts=self.ts)
        self.cb.record_trade(self.db, pnl=-50.0, current_ts=self.ts)
        assert float(self.db.get_state("cb_daily_loss_usd")) == pytest.approx(150.0)

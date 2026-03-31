"""Tests for dashboard-specific TradeDB methods."""
import time
import pytest
from storage.trade_db import TradeDB


@pytest.fixture
def db():
    d = TradeDB(":memory:")
    d.create_tables()
    return d


def _closed_trade(db, entry_price=3000.0, exit_price=3100.0, pnl=10.0, exit_offset_secs=0):
    """Insert a closed trade with exit_time = now - exit_offset_secs."""
    now = int(time.time())
    tid = db.insert_trade("ETH/USD", "momentum", "TRENDING", "buy", entry_price, 0.1, now - 3600)
    db.close_trade(tid, exit_price, now - exit_offset_secs, pnl)
    return tid


class TestGetRecentTrades:
    def test_returns_empty_list_when_no_trades(self, db):
        assert db.get_recent_trades() == []

    def test_excludes_open_trades(self, db):
        db.insert_trade("ETH/USD", "momentum", "TRENDING", "buy", 3000.0, 0.1, int(time.time()))
        assert db.get_recent_trades() == []

    def test_returns_closed_trades_desc_by_exit_time(self, db):
        tid1 = _closed_trade(db, exit_offset_secs=100)
        tid2 = _closed_trade(db, exit_offset_secs=0)
        result = db.get_recent_trades()
        assert len(result) == 2
        assert result[0]["id"] == tid2  # most recent first
        assert result[1]["id"] == tid1

    def test_respects_limit(self, db):
        for _ in range(5):
            _closed_trade(db)
        assert len(db.get_recent_trades(limit=3)) == 3

    def test_default_limit_is_20(self, db):
        for _ in range(25):
            _closed_trade(db)
        assert len(db.get_recent_trades()) == 20


class TestGetTodaySummary:
    def test_returns_zeros_when_no_trades(self, db):
        result = db.get_today_summary()
        assert result["total_trades"] == 0
        assert result["wins"] == 0
        assert result["losses"] == 0
        assert result["total_pnl"] == 0.0

    def test_counts_wins_and_losses(self, db):
        _closed_trade(db, pnl=10.0)
        _closed_trade(db, pnl=-5.0)
        result = db.get_today_summary()
        assert result["total_trades"] == 2
        assert result["wins"] == 1
        assert result["losses"] == 1
        assert result["total_pnl"] == 5.0

    def test_excludes_old_trades(self, db):
        """Trades closed before today's UTC midnight must not appear."""
        now = int(time.time())
        tid = db.insert_trade("ETH/USD", "momentum", "TRENDING", "buy", 3000.0, 0.1, now - 90000)
        # exit_time is 25 hours ago — before midnight regardless of when the test runs
        db.close_trade(tid, 3100.0, now - 90000, 10.0)
        result = db.get_today_summary()
        assert result["total_trades"] == 0


class TestDashboardState:
    def test_write_and_read_roundtrip(self, db):
        db.write_dashboard_state("IN_TRADE", 483.21, "TRENDING", 3421.50, 1711756800)
        result = db.get_dashboard_state()
        assert result["state"] == "IN_TRADE"
        assert result["balance"] == pytest.approx(483.21)
        assert result["regime"] == "TRENDING"
        assert result["last_close"] == pytest.approx(3421.50)
        assert result["last_ts"] == 1711756800

    def test_get_returns_defaults_when_no_state(self, db):
        result = db.get_dashboard_state()
        assert result["state"] == "UNKNOWN"
        assert result["balance"] == 0.0
        assert result["regime"] == "UNKNOWN"
        assert result["last_close"] == 0.0
        assert result["last_ts"] == 0

    def test_overwrite_updates_value(self, db):
        db.write_dashboard_state("IDLE", 500.0, "RANGING", 3000.0, 1000)
        db.write_dashboard_state("IN_TRADE", 450.0, "TRENDING", 3500.0, 2000)
        result = db.get_dashboard_state()
        assert result["state"] == "IN_TRADE"
        assert result["balance"] == pytest.approx(450.0)

import pytest
from storage.trade_db import TradeDB


@pytest.fixture
def db():
    """In-memory DB — fresh for every test."""
    database = TradeDB(":memory:")
    database.create_tables()
    yield database
    database.close()


class TestCreateTables:
    def test_tables_exist(self, db):
        tables = db.list_tables()
        assert "trades" in tables
        assert "signals" in tables
        assert "daily_summary" in tables
        assert "bot_state" in tables


class TestTradeInsertQuery:
    def test_insert_and_retrieve_trade(self, db):
        trade_id = db.insert_trade(
            symbol="ATOM-USD",
            strategy="momentum",
            regime="BREAKOUT",
            side="buy",
            entry_price=10.50,
            size=100.0,
            entry_time=1700000000,
        )
        assert trade_id is not None
        trade = db.get_trade(trade_id)
        assert trade["symbol"] == "ATOM-USD"
        assert trade["strategy"] == "momentum"
        assert trade["entry_price"] == 10.50

    def test_close_trade(self, db):
        trade_id = db.insert_trade(
            symbol="ATOM-USD", strategy="momentum", regime="BREAKOUT",
            side="buy", entry_price=10.50, size=100.0, entry_time=1700000000,
        )
        db.close_trade(trade_id, exit_price=11.00, exit_time=1700003600, pnl=50.0)
        trade = db.get_trade(trade_id)
        assert trade["exit_price"] == 11.00
        assert trade["pnl"] == 50.0

    def test_get_open_trades(self, db):
        db.insert_trade("ATOM-USD", "momentum", "BREAKOUT", "buy", 10.0, 100.0, 1700000000)
        db.insert_trade("ATOM-USD", "momentum", "BREAKOUT", "buy", 10.0, 100.0, 1700001000)
        open_trades = db.get_open_trades("ATOM-USD")
        assert len(open_trades) == 2


class TestSignalInsert:
    def test_insert_signal(self, db):
        db.insert_signal(
            symbol="ATOM-USD",
            strategy="momentum",
            regime="BREAKOUT",
            signal_type="entry",
            blocked=False,
            block_reason=None,
            timestamp=1700000000,
            indicators={"rsi": 65.0, "adx": 28.0},
        )
        # No exception = pass


class TestBotState:
    def test_set_and_get_state(self, db):
        db.set_state("circuit_breaker_active", "false")
        val = db.get_state("circuit_breaker_active")
        assert val == "false"

    def test_get_missing_state_returns_none(self, db):
        assert db.get_state("nonexistent_key") is None

    def test_update_state(self, db):
        db.set_state("daily_trades", "3")
        db.set_state("daily_trades", "4")
        assert db.get_state("daily_trades") == "4"

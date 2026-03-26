import pytest
from core.state_machine import StateMachine, TradeState
from execution.paper_broker import PaperBroker
from storage.trade_db import TradeDB
from models import Candle


CFG = {"risk": {"notional_size": 100.0}}
SYMBOL = "ATOM/USD"


def make_candle(close=7.20):
    return Candle(
        timestamp=1_000, open=7.0, high=7.5,
        low=6.8, close=close, volume=100.0, symbol=SYMBOL
    )


def make_broker(close=7.20):
    b = PaperBroker(initial_balance=10_000.0)
    b.set_fill_price(close, 1_000)
    return b


def make_db():
    db = TradeDB(":memory:")
    db.create_tables()
    return db


class TestStateMachine:
    def setup_method(self):
        self.sm = StateMachine()
        self.broker = make_broker()
        self.db = make_db()
        self.candle = make_candle()

    def test_initial_state_is_idle(self):
        assert self.sm.state == TradeState.IDLE

    def test_first_signal_goes_to_watching(self):
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        assert self.sm.state == TradeState.WATCHING

    def test_first_signal_does_not_open_trade(self):
        result = self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        assert result is False
        assert self.broker.get_position(SYMBOL) is None

    def test_confirmation_signal_opens_trade(self):
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        result = self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        assert result is True
        assert self.sm.state == TradeState.IN_TRADE

    def test_trade_id_set_after_open(self):
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        assert self.sm.trade_id is not None

    def test_position_created_after_open(self):
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        assert self.broker.get_position(SYMBOL) is not None

    def test_exit_signal_closes_trade_and_resets(self):
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        self.sm.on_exit_signal(self.candle, self.broker, self.db, SYMBOL)
        assert self.sm.state == TradeState.IDLE
        assert self.sm.trade_id is None
        assert self.broker.get_position(SYMBOL) is None

    def test_trade_closed_in_db_after_exit(self):
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        trade_id = self.sm.trade_id
        self.sm.on_exit_signal(self.candle, self.broker, self.db, SYMBOL)
        record = self.db.get_trade(trade_id)
        assert record["status"] == "closed"
        assert record["exit_price"] is not None

    def test_different_strategy_ignored_while_watching(self):
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        result = self.sm.on_entry_signal("trend_follow", self.candle, self.broker, self.db, CFG, SYMBOL, "TRENDING")
        assert result is False
        assert self.sm.state == TradeState.WATCHING

    def test_watching_timeout_returns_to_idle(self):
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        assert self.sm.state == TradeState.WATCHING
        self.sm.tick()
        self.sm.tick()
        self.sm.tick()
        assert self.sm.state == TradeState.IDLE

    def test_tick_resets_strategy_on_timeout(self):
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        self.sm.tick()
        self.sm.tick()
        self.sm.tick()
        assert self.sm.active_strategy_name is None

    def test_exit_ignored_when_not_in_trade(self):
        # Should not raise, just be a no-op
        self.sm.on_exit_signal(self.candle, self.broker, self.db, SYMBOL)
        assert self.sm.state == TradeState.IDLE

    def test_exit_with_no_position_logs_error_and_resets(self, caplog):
        import logging
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        self.sm.on_entry_signal("momentum", self.candle, self.broker, self.db, CFG, SYMBOL, "BREAKOUT")
        # Manually clear the broker position to simulate inconsistency
        self.broker._positions.clear()
        with caplog.at_level(logging.ERROR, logger="core.state_machine"):
            self.sm.on_exit_signal(self.candle, self.broker, self.db, SYMBOL)
        assert self.sm.state == TradeState.IDLE  # still resets state
        assert "no position found" in caplog.text.lower()

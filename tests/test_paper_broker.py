import pytest
from execution.paper_broker import PaperBroker
from models import Position


class TestPaperBroker:
    def setup_method(self):
        self.broker = PaperBroker(initial_balance=10_000.0)
        self.broker.set_fill_price(100.0, 1_000)

    def test_initial_balance(self):
        assert self.broker.get_account_balance() == 10_000.0

    def test_no_position_before_buy(self):
        assert self.broker.get_position("ATOM/USD") is None

    def test_buy_reduces_balance(self):
        self.broker.place_order("ATOM/USD", "buy", 10.0, "market")
        # 10000 - (10 * 100) = 9000
        assert self.broker.get_account_balance() == 9_000.0

    def test_buy_creates_position(self):
        self.broker.place_order("ATOM/USD", "buy", 10.0, "market")
        pos = self.broker.get_position("ATOM/USD")
        assert pos is not None
        assert pos.size == 10.0
        assert pos.entry_price == 100.0
        assert pos.side == "long"

    def test_buy_returns_order_result(self):
        result = self.broker.place_order("ATOM/USD", "buy", 10.0, "market")
        assert result.symbol == "ATOM/USD"
        assert result.side == "buy"
        assert result.size == 10.0
        assert result.fill_price == 100.0

    def test_sell_removes_position(self):
        self.broker.place_order("ATOM/USD", "buy", 10.0, "market")
        self.broker.set_fill_price(110.0, 2_000)
        self.broker.place_order("ATOM/USD", "sell", 10.0, "market")
        assert self.broker.get_position("ATOM/USD") is None

    def test_sell_restores_balance_with_profit(self):
        self.broker.place_order("ATOM/USD", "buy", 10.0, "market")
        # balance = 9000 after buy
        self.broker.set_fill_price(110.0, 2_000)
        self.broker.place_order("ATOM/USD", "sell", 10.0, "market")
        # 9000 + (10 * 110) = 9000 + 1100 = 10100
        assert self.broker.get_account_balance() == 10_100.0

    def test_cancel_order_returns_true_if_found(self):
        result = self.broker.place_order("ATOM/USD", "buy", 10.0, "market")
        assert self.broker.cancel_order(result.order_id) is True

    def test_cancel_order_returns_false_if_missing(self):
        assert self.broker.cancel_order("nonexistent_id") is False

    def test_order_ids_are_unique(self):
        r1 = self.broker.place_order("ATOM/USD", "buy", 5.0, "market")
        self.broker.set_fill_price(100.0, 1_001)
        r2 = self.broker.place_order("ATOM/USD", "sell", 5.0, "market")
        assert r1.order_id != r2.order_id

    def test_sell_without_position_raises(self):
        with pytest.raises(ValueError, match="No open position"):
            self.broker.place_order("ATOM/USD", "sell", 10.0, "market")

    def test_place_order_before_set_fill_price_raises(self):
        broker = PaperBroker(initial_balance=10_000.0)
        with pytest.raises(RuntimeError, match="set_fill_price"):
            broker.place_order("ATOM/USD", "buy", 10.0, "market")

    def test_cancel_order_does_not_reverse_position(self):
        result = self.broker.place_order("ATOM/USD", "buy", 10.0, "market")
        self.broker.cancel_order(result.order_id)
        # Position should still exist — cancel only removes the order record
        assert self.broker.get_position("ATOM/USD") is not None

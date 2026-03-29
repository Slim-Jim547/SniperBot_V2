import pytest
from execution.backtest_broker import BacktestBroker


@pytest.fixture
def broker():
    return BacktestBroker(
        initial_balance=10000.0,
        maker_fee=0.0016,
        taker_fee=0.0026,
        slippage_pct=0.001,
    )


class TestInitialState:
    def test_initial_balance(self, broker):
        assert broker.get_account_balance() == 10000.0

    def test_no_position_initially(self, broker):
        assert broker.get_position("ATOM/USD") is None

    def test_cancel_order_always_false(self, broker):
        # Backtest fills are instant — cancellation is a no-op
        assert broker.cancel_order("any-id") is False


class TestBuyFill:
    def test_buy_fill_price_includes_slippage(self, broker):
        broker.set_fill_price(10.0, 1000)
        result = broker.place_order("ATOM/USD", "buy", 100.0, "market")
        # buy fill = close * (1 + slippage) = 10.0 * 1.001 = 10.01
        assert result.fill_price == pytest.approx(10.01)

    def test_buy_deducts_cost_and_taker_fee(self, broker):
        broker.set_fill_price(10.0, 1000)
        broker.place_order("ATOM/USD", "buy", 100.0, "market")
        # fill = 10.01, notional = 1001.0, fee = 1001.0 * 0.0026 = 2.6026
        # deducted = 1001.0 + 2.6026 = 1003.6026
        expected = 10000.0 - 10.01 * 100.0 - 10.01 * 100.0 * 0.0026
        assert broker.get_account_balance() == pytest.approx(expected)

    def test_buy_creates_position(self, broker):
        broker.set_fill_price(10.0, 1000)
        broker.place_order("ATOM/USD", "buy", 100.0, "market")
        pos = broker.get_position("ATOM/USD")
        assert pos is not None
        assert pos.size == 100.0
        assert pos.symbol == "ATOM/USD"
        assert pos.side == "long"

    def test_buy_position_entry_price_is_fill_price(self, broker):
        broker.set_fill_price(10.0, 1000)
        result = broker.place_order("ATOM/USD", "buy", 100.0, "market")
        pos = broker.get_position("ATOM/USD")
        assert pos.entry_price == pytest.approx(result.fill_price)


class TestSellFill:
    def test_sell_fill_price_includes_slippage(self, broker):
        broker.set_fill_price(10.0, 1000)
        broker.place_order("ATOM/USD", "buy", 100.0, "market")
        broker.set_fill_price(11.0, 2000)
        result = broker.place_order("ATOM/USD", "sell", 100.0, "market")
        # sell fill = close * (1 - slippage) = 11.0 * 0.999 = 10.989
        assert result.fill_price == pytest.approx(10.989)

    def test_sell_adds_proceeds_minus_taker_fee(self, broker):
        broker.set_fill_price(10.0, 1000)
        broker.place_order("ATOM/USD", "buy", 100.0, "market")
        balance_after_buy = broker.get_account_balance()
        broker.set_fill_price(11.0, 2000)
        broker.place_order("ATOM/USD", "sell", 100.0, "market")
        # sell fill = 10.989, proceeds = 10.989 * 100 = 1098.9
        # fee = 1098.9 * 0.0026 = 2.85714
        # added = 1098.9 - 2.85714 = 1096.04286
        expected = balance_after_buy + 10.989 * 100.0 - 10.989 * 100.0 * 0.0026
        assert broker.get_account_balance() == pytest.approx(expected)

    def test_sell_clears_position(self, broker):
        broker.set_fill_price(10.0, 1000)
        broker.place_order("ATOM/USD", "buy", 100.0, "market")
        broker.set_fill_price(11.0, 2000)
        broker.place_order("ATOM/USD", "sell", 100.0, "market")
        assert broker.get_position("ATOM/USD") is None


class TestGuards:
    def test_sell_without_position_raises(self, broker):
        broker.set_fill_price(10.0, 1000)
        with pytest.raises(ValueError, match="No open position"):
            broker.place_order("ATOM/USD", "sell", 100.0, "market")

    def test_buy_with_insufficient_balance_raises(self, broker):
        # Balance is 10000; try to buy an amount that exceeds it
        broker.set_fill_price(200.0, 1000)
        with pytest.raises(ValueError, match="Insufficient balance"):
            broker.place_order("ATOM/USD", "buy", 1000.0, "market")

    def test_sell_symbol_mismatch_raises(self, broker):
        # Open a position for ATOM/USD, then try to sell ETH/USD
        broker.set_fill_price(10.0, 1000)
        broker.place_order("ATOM/USD", "buy", 100.0, "market")
        broker.set_fill_price(11.0, 2000)
        with pytest.raises(ValueError, match="No open position for ETH/USD"):
            broker.place_order("ETH/USD", "sell", 100.0, "market")

    def test_duplicate_buy_raises(self, broker):
        # Open a position, then try to open another without closing first
        broker.set_fill_price(10.0, 1000)
        broker.place_order("ATOM/USD", "buy", 100.0, "market")
        broker.set_fill_price(11.0, 2000)
        with pytest.raises(ValueError, match="Position already open"):
            broker.place_order("ATOM/USD", "buy", 50.0, "market")


class TestFeeSelection:
    def test_limit_order_uses_maker_fee(self):
        broker_limit = BacktestBroker(10000.0, 0.0016, 0.0026, 0.001)
        broker_market = BacktestBroker(10000.0, 0.0016, 0.0026, 0.001)
        broker_limit.set_fill_price(10.0, 1000)
        broker_market.set_fill_price(10.0, 1000)
        broker_limit.place_order("ATOM/USD", "buy", 100.0, "limit")
        broker_market.place_order("ATOM/USD", "buy", 100.0, "market")
        # maker fee (0.0016) < taker fee (0.0026) → limit buy costs less → higher balance
        assert broker_limit.get_account_balance() > broker_market.get_account_balance()

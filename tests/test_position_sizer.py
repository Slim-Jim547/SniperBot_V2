import pytest
from risk.position_sizer import PositionSizer


def make_cfg(mode, notional=100.0, risk_pct=1.0, max_position_pct=100.0):
    return {
        "risk": {
            "mode": mode,
            "notional_size": notional,
            "risk_per_trade_pct": risk_pct,
            "max_position_pct": max_position_pct,
        }
    }


class TestPositionSizer:
    def setup_method(self):
        self.sizer = PositionSizer()

    def test_notional_mode_divides_by_price(self):
        cfg = make_cfg("notional", notional=100.0)
        size = self.sizer.calculate(cfg, price=10.0, account_balance=10_000.0)
        assert size == pytest.approx(10.0)

    def test_notional_mode_ignores_account_balance(self):
        cfg = make_cfg("notional", notional=100.0)
        size_small = self.sizer.calculate(cfg, price=10.0, account_balance=500.0)
        size_large = self.sizer.calculate(cfg, price=10.0, account_balance=50_000.0)
        assert size_small == pytest.approx(size_large)

    def test_risk_pct_mode_uses_account_balance(self):
        # 1% of $10,000 = $100 risk; $100 / $5.00 = 20 units
        cfg = make_cfg("risk_pct", risk_pct=1.0)
        size = self.sizer.calculate(cfg, price=5.0, account_balance=10_000.0)
        assert size == pytest.approx(20.0)

    def test_risk_pct_mode_scales_with_balance(self):
        cfg = make_cfg("risk_pct", risk_pct=2.0)
        size = self.sizer.calculate(cfg, price=10.0, account_balance=5_000.0)
        # 2% of $5,000 = $100; $100 / $10 = 10 units
        assert size == pytest.approx(10.0)

    def test_unsupported_mode_raises(self):
        cfg = make_cfg("fixed_units")
        with pytest.raises(ValueError, match="Unsupported risk.mode"):
            self.sizer.calculate(cfg, price=10.0, account_balance=10_000.0)

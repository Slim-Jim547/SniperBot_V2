import math
import pytest
from backtest.engine import _compute_metrics


class TestComputeMetrics:
    def test_empty_returns_zero_trades(self):
        m = _compute_metrics([], 10000.0)
        assert m["total_trades"] == 0
        assert m["win_rate"] == 0.0
        assert m["profit_factor"] == math.inf
        assert m["max_drawdown_pct"] == 0.0
        assert m["sharpe"] == 0.0

    def test_all_wins(self):
        m = _compute_metrics([100.0, 200.0, 50.0], 10000.0)
        assert m["total_trades"] == 3
        assert m["wins"] == 3
        assert m["losses"] == 0
        assert m["win_rate"] == pytest.approx(1.0)
        assert m["profit_factor"] == math.inf

    def test_all_losses(self):
        m = _compute_metrics([-100.0, -200.0], 10000.0)
        assert m["total_trades"] == 2
        assert m["wins"] == 0
        assert m["losses"] == 2
        assert m["win_rate"] == pytest.approx(0.0)
        # gross profit = 0 → profit_factor = 0
        assert m["profit_factor"] == pytest.approx(0.0)

    def test_mixed_win_rate(self):
        m = _compute_metrics([100.0, -50.0, 100.0, -50.0], 10000.0)
        assert m["win_rate"] == pytest.approx(0.5)

    def test_profit_factor(self):
        # wins = 300, losses = 100 → PF = 3.0
        m = _compute_metrics([100.0, -50.0, 200.0, -50.0], 10000.0)
        assert m["profit_factor"] == pytest.approx(3.0)

    def test_max_drawdown(self):
        # equity: 10000 → 10100 (+100) → 9900 (-200)
        # peak = 10100, trough = 9900 → dd = 200/10100 ≈ 1.98%
        m = _compute_metrics([100.0, -200.0], 10000.0)
        expected_dd = (10100 - 9900) / 10100 * 100
        assert m["max_drawdown_pct"] == pytest.approx(expected_dd, rel=1e-4)

    def test_single_trade_sharpe_is_zero(self):
        # Only one trade — std dev undefined → sharpe = 0
        m = _compute_metrics([100.0], 10000.0)
        assert m["sharpe"] == 0.0

    def test_sharpe_positive_for_consistent_wins(self):
        # All wins of equal size → positive Sharpe
        m = _compute_metrics([100.0, 100.0, 100.0, 100.0], 10000.0)
        assert m["sharpe"] > 0

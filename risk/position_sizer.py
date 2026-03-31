"""
risk/position_sizer.py

Calculates trade size from risk configuration.

Supported modes (config key: risk.mode):
  notional  — fixed USD amount per trade (risk.notional_size)
  risk_pct  — risk a percentage of account balance (risk.risk_per_trade_pct)
"""


class PositionSizer:
    def calculate(self, cfg: dict, price: float, account_balance: float) -> float:
        """
        Return the trade size (in base currency units) for an entry at `price`.

        Args:
            cfg:             Full config dict (reads cfg["risk"]).
            price:           Current candle close price (must be > 0).
            account_balance: Current broker account balance in quote currency.

        Raises:
            ValueError: If risk.mode is not a supported value.
        """
        mode = cfg["risk"]["mode"]
        if mode == "notional":
            size = cfg["risk"]["notional_size"] / price
        elif mode == "risk_pct":
            risk_amount = account_balance * cfg["risk"]["risk_per_trade_pct"] / 100.0
            size = risk_amount / price
        else:
            raise ValueError(
                f"Unsupported risk.mode: {mode!r}. Expected 'notional' or 'risk_pct'."
            )

        max_size = (account_balance * cfg["risk"]["max_position_pct"] / 100.0) / price
        size = min(size, max_size)
        return size

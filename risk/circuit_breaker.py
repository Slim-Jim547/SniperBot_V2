"""
risk/circuit_breaker.py

Blocks entry signals when any of these conditions are met:
  1. Daily trade count >= risk.max_trades_per_day
  2. Daily loss >= risk.daily_loss_limit_pct % of account balance
  3. Last trade was a loss and fewer than risk.cooldown_minutes minutes have elapsed

State is persisted in TradeDB.bot_state (4 keys: cb_date, cb_daily_trades,
cb_daily_loss_usd, cb_last_loss_ts) so it survives process restarts.
Counters reset automatically at UTC midnight.
"""

from datetime import datetime, timezone
from typing import Optional, Tuple

_KEY_DATE = "cb_date"
_KEY_TRADES = "cb_daily_trades"
_KEY_LOSS = "cb_daily_loss_usd"
_KEY_LAST_LOSS_TS = "cb_last_loss_ts"


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class CircuitBreaker:
    def check(
        self, db, cfg: dict, account_balance: float, current_ts: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Returns (allowed, reason).
        allowed=False means do NOT place an entry order.
        reason is a human-readable string explaining the block.
        """
        self._maybe_reset_day(db)
        risk = cfg["risk"]

        daily_trades = int(db.get_state(_KEY_TRADES) or "0")
        if daily_trades >= risk["max_trades_per_day"]:
            return False, f"max trades per day reached ({daily_trades})"

        daily_loss = float(db.get_state(_KEY_LOSS) or "0.0")
        loss_limit_usd = account_balance * risk["daily_loss_limit_pct"] / 100.0
        if daily_loss >= loss_limit_usd:
            return False, (
                f"daily loss limit hit "
                f"(loss={daily_loss:.2f}, limit={loss_limit_usd:.2f})"
            )

        last_loss_ts = int(db.get_state(_KEY_LAST_LOSS_TS) or "0")
        cooldown_secs = risk["cooldown_minutes"] * 60
        if last_loss_ts > 0 and last_loss_ts < current_ts:
            elapsed = current_ts - last_loss_ts
            if elapsed < cooldown_secs:
                remaining = cooldown_secs - elapsed
                return False, f"in cooldown ({remaining}s remaining)"

        return True, None

    def record_trade(self, db, pnl: float, current_ts: int) -> None:
        """Call once per closed trade (win or loss)."""
        self._maybe_reset_day(db)
        daily_trades = int(db.get_state(_KEY_TRADES) or "0") + 1
        db.set_state(_KEY_TRADES, str(daily_trades))

        if pnl < 0:
            daily_loss = float(db.get_state(_KEY_LOSS) or "0.0") + abs(pnl)
            db.set_state(_KEY_LOSS, str(daily_loss))
            db.set_state(_KEY_LAST_LOSS_TS, str(current_ts))

    def _maybe_reset_day(self, db) -> None:
        """Reset daily counters if the UTC date has changed."""
        today = _today_utc()
        if db.get_state(_KEY_DATE) != today:
            db.set_state(_KEY_DATE, today)
            db.set_state(_KEY_TRADES, "0")
            db.set_state(_KEY_LOSS, "0.0")
            db.set_state(_KEY_LAST_LOSS_TS, "0")

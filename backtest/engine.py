"""
backtest/engine.py

Offline OHLCV replay engine. Fetches historical candles from Kraken,
replays them through the same regime → strategy → trade_manager stack
used in live trading, and prints performance metrics to stdout.

Entry: python main.py --backtest
Circuit breaker is NOT active in backtest — raw strategy performance only.
"""

import logging
import math
import os
from collections import deque

import numpy as np
import pandas as pd

from data.backfill import KrakenBackfill
from data.indicators import compute_all, candles_to_series
from models import Candle
from storage.trade_db import TradeDB
from core.regime_detector import RegimeDetector
from core.state_machine import StateMachine, TradeState
from core.trade_manager import TradeManager
from execution.backtest_broker import BacktestBroker
from strategies.momentum import MomentumStrategy
from strategies.trend_follow import TrendFollowStrategy

logger = logging.getLogger(__name__)


def _compute_metrics(pnls: list, initial_capital: float) -> dict:
    """
    Compute performance metrics from a list of closed-trade PnL values.

    Args:
        pnls:            list of float — positive = win, negative = loss
        initial_capital: starting portfolio value (used for drawdown + Sharpe)

    Returns:
        dict with keys: total_trades, wins, losses, win_rate, profit_factor,
                        max_drawdown_pct, sharpe
    """
    if not pnls:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "profit_factor": math.inf,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
        }

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    win_rate = len(wins) / len(pnls)

    total_win = sum(wins) if wins else 0.0
    total_loss = abs(sum(losses)) if losses else 0.0
    if total_loss > 0:
        profit_factor = total_win / total_loss
    else:
        profit_factor = math.inf

    # Equity curve → max drawdown
    equity = initial_capital
    peak = equity
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Trade-based Sharpe: mean(returns) / std(returns) * sqrt(n)
    # Note: scaled by sqrt(N trades), not annualised — not directly comparable to conventional Sharpe
    returns = [p / initial_capital for p in pnls]
    if len(returns) > 1:
        mean_r = float(np.mean(returns))
        std_r = float(np.std(returns, ddof=1))
        if std_r > 0:
            sharpe = mean_r / std_r * math.sqrt(len(returns))
        elif mean_r > 0:
            sharpe = math.inf
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    return {
        "total_trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_dd * 100,
        "sharpe": sharpe,
    }


def _print_results(
    metrics: dict,
    replayed: int,
    warmup: int,
    initial_capital: float,
    final_balance: float,
) -> None:
    total = metrics["total_trades"]
    pf = metrics["profit_factor"]
    pf_str = f"{pf:.2f}" if pf != math.inf else "∞"
    pnl_pct = (final_balance - initial_capital) / initial_capital * 100

    # Note: win/loss metrics use DB PnL (includes slippage, excludes fees).
    # Final balance reflects fees deducted by BacktestBroker.
    logger.info("\n=== Backtest Results ===")
    logger.info("Candles replayed : %s  (warm-up: %s)", replayed, warmup)
    logger.info("Trades           : %s", total)

    if total == 0:
        logger.info("No trades fired — check strategy thresholds or increase backtest.candle_count.")
        logger.info("=======================")
        return

    logger.info("Win rate         : %.1f%%", metrics["win_rate"] * 100)
    logger.info("Profit factor    : %s", pf_str)
    logger.info("Max drawdown     : -%.1f%%", metrics["max_drawdown_pct"])
    logger.info("Sharpe (trade)   : %.2f", metrics["sharpe"])
    logger.info("Final balance    : $%s  (%+.1f%%)", f"{final_balance:,.2f}", pnl_pct)
    logger.info("=======================")

    if metrics["win_rate"] > 0.9:
        logger.warning("WARNING: suspiciously high win rate — check for lookahead bias")
    if pf != math.inf and pf > 10:
        logger.warning("WARNING: suspiciously high profit factor")
    if total < 10:
        logger.warning("WARNING: too few trades for reliable statistics")


class BacktestEngine:
    def __init__(self, cfg: dict):
        self._cfg = cfg

    def run(self) -> None:
        cfg = self._cfg
        symbol = cfg["symbols"][0]
        timeframe = cfg["timeframe"]
        bcfg = cfg["backtest"]
        warmup = cfg["backfill"]["candle_count"]
        multiplier = cfg["risk"]["atr_stop_multiplier"]

        # ── Fetch candles ─────────────────────────────────────────────────
        backfill = KrakenBackfill(base_url=cfg["exchange"]["base_url"])
        total = bcfg["candle_count"]
        logger.info("Fetching %d candles for backtest...", total)
        candles = backfill.fetch(
            symbol=symbol,
            timeframe=timeframe,
            count=total,
            max_per_request=cfg["backfill"]["max_per_request"],
        )

        if len(candles) <= warmup:
            logger.error(
                "Not enough candles for warm-up. Got %s, need > %s. "
                "Increase backtest.candle_count in config.yaml.",
                len(candles), warmup,
            )
            return

        # ── Storage ───────────────────────────────────────────────────────
        db_path = cfg["database"]["backtest_path"]
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        db = TradeDB(db_path)
        db.create_tables()

        # ── Fresh components per run ──────────────────────────────────────
        regime_detector = RegimeDetector()
        state_machine = StateMachine(
            max_watch_candles=cfg["strategies"]["confirmation_candles"]
        )
        trade_manager = TradeManager()
        broker = BacktestBroker(
            initial_balance=bcfg["initial_capital"],
            maker_fee=bcfg["maker_fee"],
            taker_fee=bcfg["taker_fee"],
            slippage_pct=bcfg["slippage_pct"],
        )
        strategies = [MomentumStrategy(), TrendFollowStrategy()]

        # ── Warm-up buffer ────────────────────────────────────────────────
        buffer = deque(candles[:warmup], maxlen=warmup + 200)
        replay_candles = candles[warmup:]
        logger.info(
            "Warm-up: %d candles. Replaying: %d candles.", warmup, len(replay_candles)
        )

        # ── Replay loop ───────────────────────────────────────────────────
        last_candle = None
        try:
            for candle in replay_candles:
                last_candle = candle
                buffer.append(candle)
                opens, highs, lows, closes, volumes = candles_to_series(list(buffer))
                inds = compute_all(opens, highs, lows, closes, volumes, cfg["indicators"])
                inds["close"] = candle.close

                regime = regime_detector.classify(inds, cfg)
                state_machine.tick()

                if state_machine.state in (TradeState.IDLE, TradeState.WATCHING):
                    for strategy in strategies:
                        if strategy.should_enter(inds, regime, cfg):
                            opened = state_machine.on_entry_signal(
                                strategy.name, candle, broker, db, cfg, symbol, regime.value
                            )
                            if opened:
                                trade_manager.open_trade(candle.close, inds["atr"], multiplier)
                            break

                elif state_machine.state == TradeState.IN_TRADE:
                    trade_manager.update(candle.close, inds["atr"], multiplier)
                    position = broker.get_position(symbol)
                    exit_reason = None

                    if trade_manager.is_stopped(candle.close):
                        exit_reason = "atr_stop"
                    else:
                        active_name = state_machine.active_strategy_name
                        for strategy in strategies:
                            if strategy.name == active_name:
                                if strategy.should_exit(inds, regime, position, cfg):
                                    exit_reason = "strategy_exit"
                                break

                    if exit_reason and position is not None:
                        state_machine.on_exit_signal(candle, broker, db, symbol)
                        trade_manager.close_trade()

            # ── Force-close any open position at end of replay ────────────────
            if replay_candles and state_machine.state == TradeState.IN_TRADE:
                logger.warning("Replay ended with open position — force-closing at last candle close")
                state_machine.on_exit_signal(last_candle, broker, db, symbol)
                trade_manager.close_trade()

            # ── Metrics ───────────────────────────────────────────────────────
            closed_trades = db.get_closed_trades()
        finally:
            db.close()

        pnls = [t["pnl"] for t in closed_trades if t.get("pnl") is not None]
        metrics = _compute_metrics(pnls, bcfg["initial_capital"])
        _print_results(
            metrics,
            replayed=len(replay_candles),
            warmup=warmup,
            initial_capital=bcfg["initial_capital"],
            final_balance=broker.get_account_balance(),
        )

"""
main.py — Phase 3 entry point

Wires: config → backfill → feed → indicators → regime → strategies
       → circuit_breaker → state_machine → paper_broker → trade_manager
       → circuit_breaker.record → notifier → storage
"""

import asyncio
import logging
import os
from collections import deque

import yaml
import pandas as pd

from data.backfill import KrakenBackfill
from data.feed import KrakenFeed
from data.indicators import compute_all
from models import Candle
from storage.trade_db import TradeDB
from core.regime_detector import RegimeDetector
from core.state_machine import StateMachine, TradeState
from core.trade_manager import TradeManager
from risk.circuit_breaker import CircuitBreaker
from execution.paper_broker import PaperBroker
from strategies.momentum import MomentumStrategy
from strategies.trend_follow import TrendFollowStrategy
from alerts.notifier import Notifier


def load_config(path: str = "config/config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def setup_logging(cfg: dict):
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, cfg["logging"]["level"]),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(cfg["logging"]["file"]),
        ],
    )


def candles_to_series(candles: list) -> tuple:
    """Convert list of Candles to separate pandas Series for indicator functions."""
    opens   = pd.Series([c.open   for c in candles])
    highs   = pd.Series([c.high   for c in candles])
    lows    = pd.Series([c.low    for c in candles])
    closes  = pd.Series([c.close  for c in candles])
    volumes = pd.Series([c.volume for c in candles])
    return opens, highs, lows, closes, volumes


def run(config_path: str = "config/config.yaml"):
    cfg = load_config(config_path)
    setup_logging(cfg)
    logger = logging.getLogger("main")

    symbol = cfg["symbols"][0]
    timeframe = cfg["timeframe"]

    # ── Storage ──────────────────────────────────────────────────────────
    db_path = cfg["database"]["path"]
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    db = TradeDB(db_path)
    db.create_tables()
    logger.info("Database initialised")

    # ── Phase 2 components ────────────────────────────────────────────────
    regime_detector = RegimeDetector()
    state_machine = StateMachine(max_watch_candles=cfg["strategies"]["confirmation_candles"])
    paper_broker = PaperBroker(initial_balance=cfg["paper"]["initial_balance"])
    strategies = [MomentumStrategy(), TrendFollowStrategy()]
    logger.info(
        "Paper broker initialised | balance=$%.2f", paper_broker.get_account_balance()
    )

    # ── Phase 3 components ────────────────────────────────────────────────
    trade_manager = TradeManager()
    circuit_breaker = CircuitBreaker()
    notifier = Notifier.from_secrets("secrets/secrets.yaml")
    multiplier = cfg["risk"]["atr_stop_multiplier"]
    logger.info("Phase 3 components initialised (TradeManager, CircuitBreaker, Notifier)")

    # ── Backfill ──────────────────────────────────────────────────────────
    backfill = KrakenBackfill(base_url=cfg["exchange"]["base_url"])
    logger.info("Backfilling %d candles for %s...", cfg["backfill"]["candle_count"], symbol)
    history = backfill.fetch(
        symbol=symbol,
        timeframe=timeframe,
        count=cfg["backfill"]["candle_count"],
        max_per_request=cfg["backfill"]["max_per_request"],
    )
    candle_buffer = deque(history, maxlen=cfg["backfill"]["candle_count"] + 200)
    logger.info("Backfill complete: %d candles loaded", len(candle_buffer))

    # ── Live feed ─────────────────────────────────────────────────────────
    def on_candle_close(candle: Candle):
        candle_buffer.append(candle)
        opens, highs, lows, closes, volumes = candles_to_series(list(candle_buffer))
        inds = compute_all(opens, highs, lows, closes, volumes, cfg["indicators"])
        inds["close"] = candle.close

        regime = regime_detector.classify(inds, cfg)

        # Advance WATCHING timeout counter before signal evaluation
        state_machine.tick()

        blocked = False
        block_reason = None

        # ── Entry signals ─────────────────────────────────────────────────
        if state_machine.state in (TradeState.IDLE, TradeState.WATCHING):
            allowed, block_reason = circuit_breaker.check(
                db, cfg, paper_broker.get_account_balance(), candle.timestamp
            )
            if not allowed:
                blocked = True
                logger.info("CIRCUIT BREAK | %s", block_reason)
                notifier.send_circuit_break(block_reason)
            else:
                for strategy in strategies:
                    if strategy.should_enter(inds, regime, cfg):
                        opened = state_machine.on_entry_signal(
                            strategy.name, candle, paper_broker, db, cfg, symbol, regime.value
                        )
                        if opened:
                            trade_manager.open_trade(candle.close, inds["atr"], multiplier)
                            notifier.send_trade_opened(
                                symbol, strategy.name, regime.value,
                                candle.close, trade_manager.stop_price,
                            )
                            logger.info(
                                "TRADE OPENED | strategy=%s regime=%s price=%.4f "
                                "stop=%.4f balance=$%.2f",
                                strategy.name, regime.value, candle.close,
                                trade_manager.stop_price, paper_broker.get_account_balance(),
                            )
                        break

        # ── Exit signals ──────────────────────────────────────────────────
        elif state_machine.state == TradeState.IN_TRADE:
            # Update trailing stop first (Hard Rule 6: candle close only)
            trade_manager.update(candle.close, inds["atr"], multiplier)

            exit_reason = None
            position = paper_broker.get_position(symbol)

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
                exit_pnl = state_machine.on_exit_signal(candle, paper_broker, db, symbol) or 0.0
                trade_manager.close_trade()
                circuit_breaker.record_trade(db, exit_pnl, candle.timestamp)
                notifier.send_trade_closed(symbol, exit_pnl, candle.close, exit_reason)
                logger.info(
                    "TRADE CLOSED | reason=%s price=%.4f pnl=%.2f balance=$%.2f",
                    exit_reason, candle.close, exit_pnl,
                    paper_broker.get_account_balance(),
                )

        # ── Log signal to DB ──────────────────────────────────────────────
        db.insert_signal(
            symbol=symbol,
            strategy=state_machine.active_strategy_name or "none",
            regime=regime.value,
            signal_type="candle_close",
            blocked=blocked,
            block_reason=block_reason,
            timestamp=candle.timestamp,
            indicators=inds,
        )

        logger.info(
            "[%s] close=%.4f regime=%s state=%s stop=%.4f adx=%.1f rsi=%.1f "
            "bb_w=%.4f balance=$%.2f",
            symbol, candle.close, regime.value, state_machine.state.value,
            trade_manager.stop_price, inds["adx"], inds["rsi"],
            inds["bb_width_pct"], paper_broker.get_account_balance(),
        )

    feed = KrakenFeed(
        ws_url=cfg["exchange"]["ws_url"],
        symbol=symbol,
        timeframe_minutes=int(timeframe),
        on_candle_close=on_candle_close,
    )

    logger.info("Starting live feed. Press Ctrl+C to stop.")
    try:
        asyncio.run(feed.run())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        db.close()
        logger.info("Database closed.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SniperBot V2")
    parser.add_argument("--backtest", action="store_true", help="Run backtest instead of live feed")
    args = parser.parse_args()

    if args.backtest:
        from backtest.engine import BacktestEngine
        BacktestEngine(load_config()).run()
    else:
        run()

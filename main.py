"""
main.py — Phase 2 entry point

Wires: config → backfill → feed → indicators → regime → strategies → state machine → paper broker → storage
On each candle close: classifies regime, checks entry/exit signals, opens/closes paper trades, logs all.
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
from execution.paper_broker import PaperBroker
from strategies.momentum import MomentumStrategy
from strategies.trend_follow import TrendFollowStrategy


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
    state_machine = StateMachine()
    paper_broker = PaperBroker(initial_balance=cfg["paper"]["initial_balance"])
    strategies = [MomentumStrategy(), TrendFollowStrategy()]
    logger.info(
        f"Paper broker initialised | balance=${paper_broker.get_account_balance():.2f}"
    )

    # ── Backfill ──────────────────────────────────────────────────────────
    backfill = KrakenBackfill(base_url=cfg["exchange"]["base_url"])
    logger.info(f"Backfilling {cfg['backfill']['candle_count']} candles for {symbol}...")
    history = backfill.fetch(
        symbol=symbol,
        timeframe=timeframe,
        count=cfg["backfill"]["candle_count"],
        max_per_request=cfg["backfill"]["max_per_request"],
    )
    candle_buffer = deque(history, maxlen=cfg["backfill"]["candle_count"] + 200)
    logger.info(f"Backfill complete: {len(candle_buffer)} candles loaded")

    # ── Live feed ─────────────────────────────────────────────────────────
    def on_candle_close(candle: Candle):
        candle_buffer.append(candle)
        opens, highs, lows, closes, volumes = candles_to_series(list(candle_buffer))
        inds = compute_all(opens, highs, lows, closes, volumes, cfg["indicators"])
        inds["close"] = candle.close  # strategies need current close price

        regime = regime_detector.classify(inds, cfg)

        # ── Entry signals ─────────────────────────────────────────────────
        if state_machine.state in (TradeState.IDLE, TradeState.WATCHING):
            for strategy in strategies:
                if strategy.should_enter(inds, regime, cfg):
                    opened = state_machine.on_entry_signal(
                        strategy.name, candle, paper_broker, db, cfg, symbol, regime.value
                    )
                    if opened:
                        logger.info(
                            f"TRADE OPENED | strategy={strategy.name} "
                            f"regime={regime.value} price={candle.close:.4f} "
                            f"balance=${paper_broker.get_account_balance():.2f}"
                        )
                    break  # only one strategy triggers per candle

        # ── Exit signals ──────────────────────────────────────────────────
        elif state_machine.state == TradeState.IN_TRADE:
            active_name = state_machine.active_strategy_name
            for strategy in strategies:
                if strategy.name == active_name:
                    position = paper_broker.get_position(symbol)
                    if strategy.should_exit(inds, regime, position, cfg):
                        state_machine.on_exit_signal(candle, paper_broker, db, symbol)
                        logger.info(
                            f"TRADE CLOSED | strategy={active_name} "
                            f"regime={regime.value} price={candle.close:.4f} "
                            f"balance=${paper_broker.get_account_balance():.2f}"
                        )
                    break

        state_machine.tick()

        # ── Log signal to DB ──────────────────────────────────────────────
        db.insert_signal(
            symbol=symbol,
            strategy=state_machine.active_strategy_name or "none",
            regime=regime.value,
            signal_type="candle_close",
            blocked=False,
            block_reason=None,
            timestamp=candle.timestamp,
            indicators=inds,
        )

        logger.info(
            f"[{symbol}] close={candle.close:.4f} regime={regime.value} "
            f"state={state_machine.state.value} adx={inds['adx']:.1f} "
            f"rsi={inds['rsi']:.1f} bb_w={inds['bb_width_pct']:.4f} "
            f"ema_fast={inds['ema_fast']:.4f} ema_slow={inds['ema_slow']:.4f} "
            f"balance=${paper_broker.get_account_balance():.2f}"
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
    run()

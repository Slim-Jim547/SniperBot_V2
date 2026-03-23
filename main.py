"""
main.py — Phase 1 entry point

Wires: config -> backfill -> feed -> indicators -> storage
On each candle close: computes all indicators, logs to DB, prints summary.
Nothing trades in Phase 1.
"""

import asyncio
import logging
import os
from collections import deque

import yaml
import pandas as pd

from data.backfill import CoinbaseBackfill
from data.feed import CoinbaseFeed
from data.indicators import compute_all
from models import Candle
from storage.trade_db import TradeDB


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
    os.makedirs("data", exist_ok=True)
    db = TradeDB(cfg["database"]["path"])
    db.create_tables()
    logger.info("Database initialised")

    # ── Backfill ──────────────────────────────────────────────────────────
    backfill = CoinbaseBackfill(
        api_key=cfg["exchange"]["api_key"],
        api_secret=cfg["exchange"]["api_secret"],
        base_url=cfg["exchange"]["base_url"],
    )
    logger.info(f"Backfilling {cfg['backfill']['candle_count']} candles for {symbol}...")
    history = backfill.fetch(
        symbol=symbol,
        timeframe=timeframe,
        count=cfg["backfill"]["candle_count"],
        max_per_request=cfg["backfill"]["max_per_request"],
    )
    candle_buffer = deque(history, maxlen=cfg["backfill"]["candle_count"] + 200)
    logger.info(f"Backfill complete: {len(candle_buffer)} candles loaded")

    # Print indicators from backfill data
    opens, highs, lows, closes, volumes = candles_to_series(list(candle_buffer))
    indicators = compute_all(opens, highs, lows, closes, volumes, cfg["indicators"])
    logger.info("=== Indicators on last backfilled candle ===")
    for name, value in indicators.items():
        logger.info(f"  {name:15s}: {value:.4f}")

    # ── Live feed ─────────────────────────────────────────────────────────
    def on_candle_close(candle: Candle):
        candle_buffer.append(candle)
        opens, highs, lows, closes, volumes = candles_to_series(list(candle_buffer))
        inds = compute_all(opens, highs, lows, closes, volumes, cfg["indicators"])

        print(
            f"[{symbol}] close={candle.close:.4f} "
            f"ema_fast={inds['ema_fast']:.4f} "
            f"ema_slow={inds['ema_slow']:.4f} "
            f"rsi={inds['rsi']:.1f} "
            f"adx={inds['adx']:.1f} "
            f"atr={inds['atr']:.4f} "
            f"bb_w={inds['bb_width_pct']:.4f}"
        )

        db.insert_signal(
            symbol=symbol,
            strategy="none",
            regime="unknown",
            signal_type="candle_close",
            blocked=False,
            block_reason=None,
            timestamp=candle.timestamp,
            indicators=inds,
        )

    feed = CoinbaseFeed(
        ws_url=cfg["exchange"]["ws_url"],
        symbol=symbol,
        timeframe_minutes=int(timeframe),
        on_candle_close=on_candle_close,
    )

    logger.info("Starting live feed. Press Ctrl+C to stop.")
    asyncio.run(feed.run())


if __name__ == "__main__":
    run()

# Phase 4 — Backtest Engine Design

**Date:** 2026-03-26
**Status:** Approved

---

## Goal

Replay historical OHLCV data through the same regime → strategy → trade_manager stack used in live trading. Produce a performance summary (total trades, win rate, profit factor, max drawdown, Sharpe) printed to stdout. Triggered via `python main.py --backtest`.

---

## Decisions

| Question | Decision |
|----------|----------|
| Data source | Fetch from Kraken at runtime via `KrakenBackfill` |
| Fee model | Configurable per order type: market → taker fee, limit → maker fee |
| Circuit breaker | Disabled in backtest |
| Output | stdout only |
| Entry point | `python main.py --backtest` |
| Architecture | `BacktestEngine` class with its own candle loop |

---

## Files

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `backtest/__init__.py` | Empty package marker |
| Create | `backtest/engine.py` | `BacktestEngine` — owns the replay loop and metrics |
| Create | `execution/backtest_broker.py` | `BacktestBroker` — `BrokerBase` impl with fee/slippage fills |
| Modify | `config/config.yaml` | Add `backtest.candle_count` key |
| Modify | `main.py` | Add `argparse --backtest` flag; delegate to `BacktestEngine` |
| Create | `tests/test_backtest_broker.py` | Fill price, fee, slippage, position tracking |
| Create | `tests/test_backtest_engine.py` | Metrics math (win rate, profit factor, drawdown, Sharpe) |

`backtest.db` is written by the engine using the existing `TradeDB` pointed at `cfg["database"]["backtest_path"]` (already in `config.yaml`). No new storage module needed.

---

## BacktestBroker

Implements `BrokerBase` exactly so strategies, state machine, and trade manager work unchanged.

**Fill model — `place_order(symbol, side, size, order_type)`:**
- `order_type="market"` → taker fee (`cfg["backtest"]["taker_fee"]`)
- `order_type="limit"` → maker fee (`cfg["backtest"]["maker_fee"]`)
- Fill price: buys at `close * (1 + slippage_pct)`, sells at `close * (1 - slippage_pct)`
- `set_fill_price(price, timestamp)` is called by the state machine before `place_order` (same as `PaperBroker`) — no engine-level call needed
- In practice the state machine always passes `order_type="market"`, so both entry and exit use taker fee; the maker path is available for future use

**Balance & position:** single long-only position per symbol, balance updated on fills — same contract as `PaperBroker`.

**PnL:** `(exit_fill - entry_fill) * size - entry_fee - exit_fee`

---

## BacktestEngine loop

`BacktestEngine(cfg).run()`:

1. **Fetch** — `KrakenBackfill.fetch()` for `cfg["backtest"]["candle_count"]` candles (same symbol + timeframe as live)
2. **Warm-up** — first `cfg["backfill"]["candle_count"]` candles build indicator state only; no trades fire
3. **Replay** — for each post-warm-up candle:
   - Append to deque buffer
   - `compute_all()` → indicators
   - `regime_detector.classify()` → regime
   - `state_machine.tick()`
   - Entry/exit logic identical to `on_candle_close` in `main.py` (state machine calls `set_fill_price` internally)
   - Circuit breaker: not instantiated — no `check()` or `record_trade()` calls
   - Writes trades to `backtest.db` via `TradeDB`
4. **Metrics** — computed from `backtest.db` trades table, printed to stdout
5. **Fresh state** — new `RegimeDetector`, `StateMachine`, `TradeManager`, `BacktestBroker` per `run()` call

---

## Metrics

Computed from the closed trades in `backtest.db` after the loop:

| Metric | Formula |
|--------|---------|
| Total trades | Count of closed trades |
| Win rate | `wins / total_trades` |
| Profit factor | `sum(pnl > 0) / abs(sum(pnl < 0))` — `∞` if no losses |
| Max drawdown | Peak-to-trough in running equity curve from `initial_capital` |
| Sharpe (trade) | `mean(trade_returns) / std(trade_returns) * sqrt(total_trades)` |

**Sanity warnings** printed if:
- Win rate > 90% → lookahead bias suspicion
- Profit factor > 10 → suspiciously high
- Total trades < 10 → too few for reliable statistics

**Sample output:**
```
=== Backtest Results ===
Candles replayed : 2000  (warm-up: 500)
Trades           : 47
Win rate         : 59.6%
Profit factor    : 1.82
Max drawdown     : -4.3%
Sharpe (trade)   : 0.74
Final balance    : $10 847.22  (+8.5%)
=======================
```

---

## main.py changes

Add `argparse` at the `__main__` block only — `run()` is untouched:

```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", action="store_true")
    args = parser.parse_args()

    if args.backtest:
        from backtest.engine import BacktestEngine
        BacktestEngine(load_config()).run()
    else:
        run()
```

Add `candle_count` to `config.yaml` under the existing `backtest:` section:

```yaml
backtest:
  candle_count: 2000        # total candles to fetch (warm-up + replay)
  data_path: "data/historical"
  initial_capital: 10000.0
  maker_fee: 0.0016
  taker_fee: 0.0026
  slippage_pct: 0.001
```

---

## Out of scope

- CSV data source (Phase 4 uses Kraken live fetch only)
- Circuit breaker enabled in backtest
- Multi-symbol replay
- Optimisation / parameter sweep
- `risk/portfolio_manager.py` (Phase 5)

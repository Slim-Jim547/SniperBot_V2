# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

> **All commands assume CWD = `C:/projects/SniperBot_V2`.** In Bash tool calls, prefix each command with `cd C:/projects/SniperBot_V2 &&`. The flat package layout requires the project root on `sys.path` — running from a subdirectory causes `ImportError`.

```bash
# Run the bot
venv/Scripts/python main.py   # Windows (or activate venv first)

# Run the dashboard (separate terminal, reads same DB file)
venv/Scripts/python dashboard/app.py   # opens http://localhost:5000

# Run all tests
venv/Scripts/pytest -v        # Windows

# Run a single test file
venv/Scripts/pytest tests/test_indicators.py

# Run a single test
venv/Scripts/pytest tests/test_indicators.py::TestEMA::test_fast_ema_above_slow_in_uptrend

# Install dependencies
venv/Scripts/pip install -r requirements.txt
```

## Architecture

**Flat package layout** — `SniperBot_V2/` is the package root. Modules import each other directly (e.g. `from data.indicators import compute_all`). No top-level package wrapping.

**Directory structure (Phases 1–5 complete):**
```
├── config/config.yaml          # All parameters — nothing hardcoded in Python
├── secrets/                    # Credentials only — never committed to git
│   └── secrets.yaml            # Exchange API key/secret (Phase 6 only), Discord webhook, Telegram token
├── core/
│   ├── state_machine.py        # IDLE → WATCHING → IN_TRADE → CLOSING
│   ├── regime_detector.py      # ADX + BB + volume → RegimeLabel enum
│   └── trade_manager.py        # Entry, exit, ATR trailing stop
├── strategies/
│   ├── base_strategy.py        # Abstract base class
│   ├── momentum.py             # BB squeeze + breakout entry logic
│   └── trend_follow.py         # EMA stack + ADX entry logic
├── data/
│   ├── feed.py                 # WebSocket → tick → candle builder
│   ├── backfill.py             # REST API historical candle fetch on startup
│   └── indicators.py           # ALL technical indicator calculations live here
├── risk/
│   ├── position_sizer.py       # Notional and risk-based sizing
│   ├── portfolio_manager.py    # Multi-symbol wallet % allocation  ← Phase 6+ (not yet implemented)
│   └── circuit_breaker.py      # Daily loss, max trades, cooldowns
├── execution/
│   ├── broker_base.py          # Abstract broker interface (shared contract)
│   ├── paper_broker.py         # Simulated fills — reads config, no API calls
│   └── live_broker.py          # Kraken REST API order placement  ← Phase 6 (not yet implemented)
├── storage/trade_db.py         # SQLite — all reads and writes go through here
├── alerts/notifier.py          # Discord + Telegram behind one interface
├── dashboard/app.py            # Local Flask app — reads SQLite, auto-refreshes
├── dashboard/templates/index.html  # Single-page dark-themed dashboard, vanilla JS polling
├── backtest/engine.py          # Offline historical replay against OHLCV data
├── logs/                       # Created at runtime by logging setup
├── models.py                   # Candle dataclass (shared, root level)
└── main.py                     # Entry point — wires everything, runs the loop
```

**Data flow on startup (Phase 1):**
```
config.yaml → KrakenBackfill (REST, no auth) → deque[Candle] → compute_all() → TradeDB.insert_signal()
                                                                ↑
config.yaml → KrakenFeed (WebSocket, no auth) → on_candle_close() (each 15m candle)
```

**Per-candle-close flow (Phase 2+):**
```
on_candle_close → compute_all() → regime_detector → strategy → state_machine → broker → trade_manager → trade_db
```

## Hard Rules

1. **Indicators only in `data/indicators.py`** — never compute EMA, RSI, ATR, etc. anywhere else. This was the root cause of V1 bugs.
2. **SQLite only through `storage/trade_db.py`** — no raw `sqlite3` calls outside this module.
3. **No hardcoded values** — every parameter comes from `config/config.yaml`; every credential comes from `secrets/secrets.yaml`.
4. **`secrets/` is never committed** — it must be in `.gitignore`. `config/config.yaml` holds only non-sensitive params (no API keys, no tokens).
5. **`regime_detector` takes pre-computed indicator values as input** — it does not call `compute_all()` itself. The main loop computes indicators once, then passes the dict to the regime detector and strategies.
6. **ATR trailing stop updates on candle close only** — never intra-candle.

## Key Module Contracts

**`core/regime_detector.py`** — input: indicator dict (ADX, BB width pct, EMA values, volume ratio); output: `RegimeLabel` enum with values `BREAKOUT | TRENDING | RANGING | CHOPPY`.

**`execution/broker_base.py`** — both `paper_broker.py` and `live_broker.py` implement this exact interface:
```python
place_order(symbol, side, size, order_type) → OrderResult
get_position(symbol) → Position | None
get_account_balance() → float
cancel_order(order_id) → bool
```
Switching paper → live is one line in `config.yaml` (`broker.mode: live`). Zero code changes.

**`core/trade_manager.py`** — ATR trailing stop for the open position (Hard Rule 6: update on candle close only):
- `open_trade(entry_price, atr, multiplier)` → sets initial stop = entry_price - multiplier * atr
- `update(candle_close, atr, multiplier)` → trails stop upward only; no-op when inactive
- `is_stopped(candle_close)` → True if active AND close <= stop
- `close_trade()` → resets to inactive; call after `on_exit_signal()`

**`risk/circuit_breaker.py`** — gates entry signals; state persisted in `bot_state` via TradeDB:
- `check(db, cfg, account_balance, current_ts)` → `(bool, Optional[str])` — False = blocked
- `record_trade(db, pnl, current_ts)` → call once per closed trade
- **Design:** tracks cumulative gross losses; wins do NOT offset losses. Intentional — prevents chasing losses after a bad series.

**`alerts/notifier.py`** — Discord + Telegram behind one interface; credentials from `secrets/secrets.yaml`:
- `Notifier.from_secrets(path)` → silent no-op notifier if file missing or malformed (catches `OSError`, `yaml.YAMLError`)
- `send_trade_opened()`, `send_trade_closed()`, `send_circuit_break()` — never raise on network error
- Exception logging uses `type(exc).__name__` only — never logs full exception (would leak webhook URL / bot token)

**`core/state_machine.py`** — manages trade lifecycle only, no strategy logic:
- `IDLE` → `WATCHING` (signal detected)
- `WATCHING` → `IN_TRADE` (confirmed) or → `IDLE` (signal faded)
- `IN_TRADE` → `CLOSING` (exit triggered)
- `CLOSING` → `IDLE` (fill confirmed)
- `on_exit_signal()` → `Optional[float]` — returns PnL from broker fill price (or None if no position found); use this value for circuit breaker and notifier, do not recompute independently

**`storage/trade_db.py`** — core tables: `trades` (entry/exit/P&L/strategy/regime), `signals` (all signals including blocked ones), `daily_summary` (dashboard stats), `bot_state` (circuit breaker state persisted across restarts).
- Dashboard methods: `write_dashboard_state(state, balance, regime, last_close, last_ts)` / `get_dashboard_state()` — uses `bot_state` table with `dash_*` key prefix.
- `get_today_summary()` counts `wins` as `pnl > 0`, `losses` as `pnl < 0` (flat trades not counted as losses).
- Uses `threading.local()` connections — safe for Flask multi-threaded requests. Do not revert to a single shared `self._conn`.

**`backtest/engine.py`** — replays historical OHLCV through the same regime → strategy → trade_manager stack used live. Logs to a separate `backtest.db`. Outputs: total trades, win rate, profit factor, max drawdown, Sharpe.

## Configuration

**`config/config.yaml`** — all non-sensitive parameters:
- `broker.mode: paper | live` — switching to live requires only this line change
- `indicators.*` — all periods for EMA/RSI/BB/ATR/ADX/volume indicators
- `backfill.candle_count` — warm-up history size on startup
- `timeframe` — candle size in minutes

**`secrets/secrets.yaml`** — all credentials (gitignored, never committed):
- `exchange.api_key` / `exchange.api_secret` — Kraken API keys (Phase 6 live trading only)
- `alerts.discord_webhook`
- `alerts.telegram_bot_token` / `alerts.telegram_chat_id`

## Exchange: Kraken

Public endpoints — zero auth needed for Phases 1–5.

- REST base: `https://api.kraken.com/0/public/`
- WebSocket: `wss://ws.kraken.com`
- Symbol format: `ETHUSD` for REST params, `ETH/USD` for WebSocket pair names
- Phase 6 live trading uses HMAC-SHA512 auth; keys go in `secrets/secrets.yaml`

Full wire protocol detail (subscribe messages, response schemas, candle-close detection): see `docs/kraken-api-notes.md`.

## Build Phases

Each phase must be fully validated before starting the next. Any `pytest FAILED` = stop and fix before continuing.

| Phase | Goal | Validation |
|-------|------|------------|
| 1 ✅ | Foundation — config, indicators, backfill, feed, SQLite | Bot starts, backfills, prints indicators on each close, logs to DB |
| 1.5 ✅ | Secrets — create `secrets/secrets.yaml`, move all credentials out of `config.yaml`, add `secrets/` to `.gitignore` | No credentials in `config.yaml`; `secrets/` not tracked by git |
| 1.6 ✅ | **Kraken pivot** — rewrite `data/backfill.py` and `data/feed.py` for Kraken public API (no auth) | Bot starts, backfills 500 candles from Kraken, prints indicators on each live close |
| 2 ✅ | Regime detector + strategies + paper broker + state machine | Signals fire in correct regimes only; paper trades open/close; all logged |
| 3 ✅ | Risk & exits — ATR trailing stop, position sizer, circuit breaker, alerts | Trailing stop trails correctly on candle close; circuit breakers fire; Discord alerts working |
| 4 ✅ | Backtest engine — offline OHLCV replay | Backtest completes without errors; results are believable (90%+ win rate = bug) |
| 5 ✅ | Dashboard — Flask on port 5000, auto-refresh 30s | Loads at localhost:5000; shows current state, open position, today's summary, last 20 trades |
| 6 | Live broker | Only after Phase 4 shows consistent positive expectancy over 100+ paper trades |

**Do not rush to Phase 6.** A bot that is not profitable on paper will not be profitable live. The market adds costs and slippage that make paper results optimistic.

## Testing Notes

`pytest.ini` sets `asyncio_mode = auto` — async tests work without `@pytest.mark.asyncio`. Use in-memory SQLite (`":memory:"`) for `TradeDB` tests. Mock HTTP with `unittest.mock.patch` for backfill tests (avoid real API calls in tests).

**Backfill test mocking (Kraken):** No JWT — only mock `data.backfill.requests.get`. Provide a response matching Kraken's OHLC format:
```python
@patch("data.backfill.requests.get")
def test_foo(self, mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "error": [],
        "result": {"ETHUSD": [[1616148000,"7.21","7.30","7.19","7.26","7.24","100.0",10]], "last": 1616148000}
    }
```

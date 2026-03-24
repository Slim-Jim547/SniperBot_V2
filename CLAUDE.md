# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the bot (must run from project root — config path is relative)
venv/Scripts/python main.py   # Windows (or activate venv first)

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

**Planned directory structure (all 6 phases):**
```
├── config/config.yaml          # All parameters — nothing hardcoded in Python
├── secrets/                    # Credentials only — never committed to git
│   └── secrets.yaml            # Coinbase API key/secret, Discord webhook, Telegram token
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
│   ├── portfolio_manager.py    # Multi-symbol wallet % allocation
│   └── circuit_breaker.py      # Daily loss, max trades, cooldowns
├── execution/
│   ├── broker_base.py          # Abstract broker interface (shared contract)
│   ├── paper_broker.py         # Simulated fills — reads config, no API calls
│   └── live_broker.py          # Coinbase Advanced Trade API order placement
├── storage/trade_db.py         # SQLite — all reads and writes go through here
├── alerts/notifier.py          # Discord + Telegram behind one interface
├── dashboard/app.py            # Local Flask app — reads SQLite, auto-refreshes
├── backtest/engine.py          # Offline historical replay against OHLCV data
├── models.py                   # Candle dataclass (shared, root level)
└── main.py                     # Entry point — wires everything, runs the loop
```

**Data flow on startup (Phase 1):**
```
config.yaml → CoinbaseBackfill (REST) → deque[Candle] → compute_all() → TradeDB.insert_signal()
                                                         ↑
config.yaml → CoinbaseFeed (WebSocket) → on_candle_close() (each 5m candle)
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

**`core/state_machine.py`** — manages trade lifecycle only, no strategy logic:
- `IDLE` → `WATCHING` (signal detected)
- `WATCHING` → `IN_TRADE` (confirmed) or → `IDLE` (signal faded)
- `IN_TRADE` → `CLOSING` (exit triggered)
- `CLOSING` → `IDLE` (fill confirmed)

**`storage/trade_db.py`** — core tables: `trades` (entry/exit/P&L/strategy/regime), `signals` (all signals including blocked ones), `daily_summary` (dashboard stats), `bot_state` (circuit breaker state persisted across restarts).

**`backtest/engine.py`** — replays historical OHLCV through the same regime → strategy → trade_manager stack used live. Logs to a separate `backtest.db`. Outputs: total trades, win rate, profit factor, max drawdown, Sharpe.

## Configuration

Two files, strict separation:

**`config/config.yaml`** — all non-sensitive parameters:
- `broker.mode: paper | live` — switching to live requires only this line change
- `indicators.*` — all periods for EMA/RSI/BB/ATR/ADX/volume indicators
- `backfill.candle_count` — warm-up history size on startup
- `timeframe` — candle size in minutes (default `"5"`)

**`secrets/secrets.yaml`** — all credentials (gitignored, never committed):
- `exchange.api_key` / `exchange.api_secret` — Coinbase CDP keys
- `alerts.discord_webhook`
- `alerts.telegram_bot_token` / `alerts.telegram_chat_id`

## API Authentication

Coinbase uses **CDP JWT authentication** (ES256, not legacy HMAC). `CoinbaseBackfill._auth_headers()` builds JWT tokens signed with the EC private key from `exchange.api_secret` (loaded from `secrets/secrets.yaml` after Phase 1.5). The WebSocket feed (`CoinbaseFeed`) does not require auth for `market_trades` subscription.

**Credential location (Phase 1):** `config/config.yaml` holds credentials and is gitignored. `secrets/secrets.yaml` is the Phase 1.5 target — does not exist yet.

**Unresolved (March 2026):** CDP portal "Secret API Keys" are 36-char key + 88-char secret (alphanumeric, no dashes, no PEM). Auth format for this key type is unknown — needs investigation. The `organizations/.../apiKeys/...` + PEM format (used by official `coinbase-advanced-py` SDK) could not be located in the CDP portal by the user.

## Build Phases

Each phase must be fully validated before starting the next.

| Phase | Goal | Validation |
|-------|------|------------|
| 1 ✅ | Foundation — config, indicators, backfill, feed, SQLite | Bot starts, backfills, prints indicators on each close, logs to DB |
| 1.5 | Secrets — create `secrets/secrets.yaml`, move all credentials out of `config.yaml`, add `secrets/` to `.gitignore` | Bot still starts; no credentials in `config.yaml`; `secrets/` not tracked by git |
| 2 | Regime detector + strategies + paper broker + state machine | Signals fire in correct regimes only; paper trades open/close; all logged |
| 3 | Risk & exits — ATR trailing stop, position sizer, circuit breaker, alerts | Trailing stop trails correctly on candle close; circuit breakers fire; Discord alerts working |
| 4 | Backtest engine — offline OHLCV replay | Backtest completes without errors; results are believable (90%+ win rate = bug) |
| 5 | Dashboard — Flask on port 5000, auto-refresh 30s | Loads at localhost:5000; shows current state, open position, today's summary, last 20 trades |
| 6 | Live broker | Only after Phase 4 shows consistent positive expectancy over 100+ paper trades |

**Do not rush to Phase 6.** A bot that is not profitable on paper will not be profitable live. The market adds costs and slippage that make paper results optimistic.

## Testing Notes

`pytest.ini` sets `asyncio_mode = auto` — async tests work without `@pytest.mark.asyncio`. Use in-memory SQLite (`":memory:"`) for `TradeDB` tests. Mock HTTP with `unittest.mock.patch` for backfill tests (avoid real API calls in tests).

**Backfill test mocking:** Mock both `data.backfill.jwt.encode` AND `data.backfill.requests.get` — JWT signing runs before the HTTP call, so tests fail with a PEM error if only requests is mocked:
```python
@patch("data.backfill.jwt.encode", return_value="fake_token")
@patch("data.backfill.requests.get")
def test_foo(self, mock_get, mock_jwt): ...
```

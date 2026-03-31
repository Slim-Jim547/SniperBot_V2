# Code Review Fix Plan — 2026-03-30

Generated from a comprehensive dual-review (python-reviewer + codex-reviewer) of the full SniperBot V2 codebase after Phase 5 completion.

**Overall verdict: WARNING** — No CRITICAL security issues. Several HIGH/MEDIUM bugs to fix before Phase 6.

---

## HIGH — Fix Before Phase 6

### H1 — TradeDB thread connection leak
**File:** `storage/trade_db.py:30`
**Issue:** `TradeDB.close()` only closes the calling thread's connection. Flask request threads' connections are never closed → SQLite file handle leak (especially bad on Windows with file locking).
**Fix:** Track all created connections in a list under a `threading.Lock` inside `_get_conn()`, then iterate and close all of them in `close()`.

### H2 — Phantom candle emitted on WebSocket reconnect
**File:** `data/feed.py:_connect()`
**Issue:** `_last_begin_time` and `_current` are NOT reset when `_connect()` re-runs. On reconnect, the first incoming message has a different `begin_time` than the stale `_last_begin_time`, triggering `_emit_candle()` with old (pre-disconnect) partial candle data.
**Fix:** Add `self._last_begin_time = None` and `self._current = None` at the top of `_connect()`, before the WebSocket connection is opened.

### H3 — Overly broad except in reconnect loop
**File:** `data/feed.py:92`
**Issue:** `except Exception` catches programming errors in `on_candle_close`. A bug in the callback causes the bot to spin-reconnect forever at 5s intervals without surfacing the real error.
**Fix:** Narrow to `except (websockets.ConnectionClosed, OSError, asyncio.TimeoutError) as exc`.

### H4 — max_position_pct silently unenforced
**File:** `risk/position_sizer.py`
**Issue:** `max_position_pct` is present in `config.yaml` under `risk` but is never read or applied in `PositionSizer.calculate()`. The bot can over-size any position without limit.
**Fix:** After computing `size`, apply the cap: `max_size = (account_balance * cfg["risk"]["max_position_pct"] / 100.0) / price` then `size = min(size, max_size)`.

### H5 — Backtest DB connection leaked on exception
**File:** `backtest/engine.py`
**Issue:** No `try/finally` around the replay loop. If `compute_all()` raises mid-replay, the backtest SQLite connection is never closed.
**Fix:** Wrap the replay loop in `try: ... finally: db.close()`.

---

## MEDIUM — Address Soon

### M1 — `candle` variable implicitly relied upon after for-loop
**File:** `backtest/engine.py:251`
**Issue:** The force-close block after the replay loop uses the `candle` loop variable implicitly. Guarded by `if replay_candles`, so unbound risk is near-zero — but fragile if the guard ever changes.
**Fix:** Add `last_candle = candle` inside the loop body, or use `replay_candles[-1]` explicitly after the loop.

### M2 — Circuit break alert fires every candle while WATCHING
**File:** `main.py:119`
**Issue:** If the circuit breaker trips while the state machine is in WATCHING state, `notifier.send_circuit_break()` fires on every candle (up to `confirmation_candles` = 3 times) until the state resets.
**Fix:** Gate the notification with a per-signal flag — only send the alert the first time the circuit breaker blocks in a given WATCHING window.

### M3 — Dashboard exposed on all network interfaces
**File:** `dashboard/app.py:92`
**Issue:** `host="0.0.0.0"` exposes the dashboard to the entire LAN. Shows open positions, P&L, trade history.
**Fix:** Change to `host="127.0.0.1"`. Add a `dashboard.host` config key if LAN access is ever needed.

### M4 — `--backtest` mode ignores config path
**File:** `main.py:229`
**Issue:** The backtest branch calls `load_config()` with no argument (defaults to `"config/config.yaml"`). There is no `--config` CLI argument at all. A custom config path is silently ignored.
**Fix:** Add `--config` to `argparse` and thread the path through both live and backtest branches.

### M5 — No config schema validation at startup
**File:** `main.py:33–35`
**Issue:** `load_config()` returns a raw dict with no type or key validation. A missing/mistyped key produces an opaque `KeyError` deep in a trading loop.
**Fix:** Add a lightweight validation step — check required keys exist and are the right type for critical numeric fields.

### M6 — Daily loss limit uses live balance, not start-of-day balance
**File:** `risk/circuit_breaker.py:44`
**Issue:** `loss_limit_usd = account_balance * pct / 100` uses the current balance at check time. As losses accumulate, the USD limit shrinks (compounding conservatism). After wins, it expands.
**Fix:** Persist the balance at day-start (reset daily alongside `_KEY_LOSS`) and use that as the denominator.

### M7 — f-strings in logging calls (eager evaluation)
**File:** `data/feed.py:93,97,105,149` / `data/backfill.py:122`
**Issue:** `logger.error(f"WebSocket error: {exc}...")` evaluates eagerly even when log level would suppress output.
**Fix:** Use `logger.error("WebSocket error: %s...", exc)` lazy formatting throughout `feed.py` and `backfill.py`.

---

## LOW — Quality / Cleanup

| # | File | Issue | Fix |
|---|------|-------|-----|
| L1 | `config/config.yaml:16` | Comment says "ATOMUSD" but symbol is ETH/USD — stale from ATOM days | Update comment |
| L2 | `core/state_machine.py:21` | `_sizer = PositionSizer()` module-level singleton — stateless today but fragile | Instantiate inside `on_entry_signal()` or inject via `__init__` |
| L3 | `main.py:189` | `stop=0.0000` logged every candle even when no trade open | Only log stop when `state == IN_TRADE` |
| L4 | `core/state_machine.py:130` | No log when WATCHING times out back to IDLE — silent signal abandonment | Add `logger.info(...)` on timeout transition |
| L5 | `main.py:50` / `backtest/engine.py:34` | `candles_to_series()` duplicated verbatim in both files | Move to `data/indicators.py` or `data/utils.py`, import in both |
| L6 | `backtest/engine.py:91` | Sharpe uses `sqrt(N)` (trade-count) scaling — not comparable to conventional Sharpe | Document the convention or remove scaling |
| L7 | `backtest/engine.py:129` | `print()` used for results output instead of `logging` | Replace with `logger.info()` |
| L8 | `models.py` | `Candle`, `OrderResult`, `Position` are mutable dataclasses — can be accidentally mutated | Add `frozen=True` to `@dataclass` decorators |
| L9 | `tests/test_strategies.py:107` | Import between two test classes violates PEP 8 E402 | Move import to top of file |
| L10 | `data/backfill.py:86` | `_SECONDS_PER_CANDLE[timeframe]` raises bare `KeyError` for unsupported timeframes | Use `.get()` with a descriptive `ValueError` |

---

## Test Gaps

| # | File | Issue |
|---|------|-------|
| T1 | `backtest/engine.py` | `BacktestEngine.run()` is never tested — only `_compute_metrics()` has a unit test |
| T2 | `main.py` | No integration test for the full `on_candle_close` pipeline end-to-end |
| T3 | `risk/position_sizer.py` | `max_position_pct` is untested (and unenforced — see H4) |

---

## Recommended Fix Order

1. **H4** — max_position_pct unenforced (risk management gap — highest priority)
2. **H2** — phantom candle on reconnect (data correctness)
3. **H1** — TradeDB connection leak (resource management, especially on Windows)
4. **H3** — broad except in feed (error visibility)
5. **H5** — backtest DB leak (resource management)
6. **M2** — alert spam on circuit break
7. **M3** — dashboard network exposure
8. **M1** — candle variable after loop
9. Remaining MEDIUM items (M4–M7)
10. LOW items as time permits

---

## What's Confirmed Good (Don't Touch)

- All SQLite queries use parameterized `?` placeholders — no injection risk
- `yaml.safe_load` used everywhere — no unsafe deserialization
- `secrets/` is gitignored; no credentials in `config.yaml`
- `threading.local()` in `TradeDB` is the correct pattern for Flask + main loop sharing a DB
- `Notifier` silently no-ops on missing secrets file — correct resilience
- Test suite covers all individual components with good edge cases
- Broker interface contract (`broker_base.py`) is clean — live/paper swap is truly one line

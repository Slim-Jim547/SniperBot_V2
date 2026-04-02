# Discord Message Cleanup — Design Spec

**Date:** 2026-04-01  
**Status:** Approved

## Problem

Discord notifications contain too much content per message, and the circuit break alert fires
repeatedly causing noise. The user wants quick, scannable signals — not a status report.

## Changes

### TRADE OPENED — unchanged

```
TRADE OPENED
Symbol:   ETHUSD
Strategy: momentum
Regime:   BREAKOUT
Entry:    3421.5000
Stop:     3380.0000
```

All five fields are kept. Entry + Stop together give immediate trailing stop context.

### TRADE CLOSED — drop Symbol

```
TRADE CLOSED
Exit:   3421.5000
P&L:    +15.32
Reason: atr_stop
```

Symbol is dropped — the bot is a single-symbol operation so it adds no information.
Exit price is kept because it gives quick insight into where the trailing stop triggered.

### CIRCUIT BREAK — removed entirely

The circuit break alert is removed from Discord. The dashboard already shows circuit break state.
Removing it eliminates the primary source of repeated noise.

## Code Changes

| File | Change |
|---|---|
| `alerts/notifier.py` | Remove `symbol` param from `send_trade_closed`; remove `send_circuit_break` method |
| `main.py` | Update `send_trade_closed` call (drop symbol arg); remove `send_circuit_break` call and `_cb_alerted` flag |
| `tests/test_notifier.py` | Update `send_trade_closed` tests; remove `send_circuit_break` tests |

## What Is Not Changed

- `send_trade_opened` signature and content — no changes
- Discord/Telegram delivery logic — no changes
- Dashboard circuit break display — no changes
- Logging — circuit break still logged to file at INFO level

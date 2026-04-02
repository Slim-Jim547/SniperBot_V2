# Discord Message Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove symbol from TRADE CLOSED messages and eliminate circuit break Discord alerts entirely.

**Architecture:** Three-file change — tests first (TDD), then notifier, then main. The `send_circuit_break` method and the `_cb_alerted` de-dup flag in main.py are both removed. The `send_trade_closed` signature loses its `symbol` parameter.

**Tech Stack:** Python, pytest, unittest.mock

---

## File Map

| Action | File | What changes |
|---|---|---|
| Modify | `tests/test_notifier.py` | Update `send_trade_closed` calls (drop symbol); remove `test_send_circuit_break_includes_reason` |
| Modify | `alerts/notifier.py` | Drop `symbol` from `send_trade_closed`; remove `send_circuit_break` |
| Modify | `main.py` | Update `send_trade_closed` call; remove `send_circuit_break` call and `_cb_alerted` flag |

---

### Task 1: Update tests to match new signatures

**Files:**
- Modify: `tests/test_notifier.py:137-167`

- [ ] **Step 1: Update `test_send_trade_closed_includes_pnl`**

Replace the test at line 137 with:

```python
def test_send_trade_closed_includes_key_fields(self):
    notifier = Notifier("https://discord.example/wh", None, None)
    captured = []
    with patch("alerts.notifier.requests.post") as mock_post:
        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.side_effect = lambda url, json, timeout: captured.append(json["content"]) or MagicMock(raise_for_status=MagicMock())
        notifier.send_trade_closed(15.32, 7.37, "atr_stop")
    msg = captured[0]
    assert "+15.32" in msg
    assert "7.3700" in msg
    assert "atr_stop" in msg
    assert "ATOM/USD" not in msg
```

- [ ] **Step 2: Update `test_send_trade_closed_shows_negative_pnl`**

Replace the test at line 148 with:

```python
def test_send_trade_closed_shows_negative_pnl(self):
    notifier = Notifier("https://discord.example/wh", None, None)
    captured = []
    with patch("alerts.notifier.requests.post") as mock_post:
        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.side_effect = lambda url, json, timeout: captured.append(json["content"]) or MagicMock(raise_for_status=MagicMock())
        notifier.send_trade_closed(-8.50, 7.10, "strategy_exit")
    msg = captured[0]
    assert "-8.50" in msg
```

- [ ] **Step 3: Delete `test_send_circuit_break_includes_reason`**

Remove the entire test at lines 158-167:

```python
def test_send_circuit_break_includes_reason(self):
    ...
```

- [ ] **Step 4: Run tests to confirm they fail with current code**

```
cd C:/projects/SniperBot_V2 && venv/Scripts/pytest tests/test_notifier.py -v
```

Expected: failures on the two updated `send_trade_closed` tests (wrong number of args). All other tests pass.

- [ ] **Step 5: Commit failing tests**

```bash
git add tests/test_notifier.py
git commit -m "test: update notifier tests for Discord cleanup"
```

---

### Task 2: Update `alerts/notifier.py`

**Files:**
- Modify: `alerts/notifier.py:69-83`

- [ ] **Step 1: Remove `symbol` from `send_trade_closed`**

Replace the `send_trade_closed` method (lines 69-80):

```python
def send_trade_closed(
    self, pnl: float, exit_price: float, reason: str
) -> None:
    sign = "+" if pnl >= 0 else ""
    msg = (
        f"TRADE CLOSED\n"
        f"Exit:   {exit_price:.4f}\n"
        f"P&L:    {sign}{pnl:.2f}\n"
        f"Reason: {reason}"
    )
    self.send(msg)
```

- [ ] **Step 2: Remove `send_circuit_break`**

Delete the entire `send_circuit_break` method (lines 82-83):

```python
def send_circuit_break(self, reason: str) -> None:
    self.send(f"CIRCUIT BREAK\n{reason}")
```

- [ ] **Step 3: Run notifier tests — all must pass**

```
cd C:/projects/SniperBot_V2 && venv/Scripts/pytest tests/test_notifier.py -v
```

Expected: all tests pass, no failures.

- [ ] **Step 4: Commit**

```bash
git add alerts/notifier.py
git commit -m "feat: remove symbol from trade closed message; remove circuit break alert"
```

---

### Task 3: Update `main.py`

**Files:**
- Modify: `main.py:121,144-150,193`

- [ ] **Step 1: Remove `_cb_alerted` flag declaration**

On line 121, delete:

```python
_cb_alerted = False  # tracks whether circuit-break alert fired for current WATCHING window
```

- [ ] **Step 2: Remove the circuit break alert block and `_cb_alerted` resets**

In `on_candle_close`, the entry signal block currently reads (lines 139-169):

```python
if state_machine.state in (TradeState.IDLE, TradeState.WATCHING):
    allowed, block_reason = circuit_breaker.check(
        db, cfg, paper_broker.get_account_balance(), candle.timestamp
    )
    if not allowed:
        blocked = True
        if not _cb_alerted:
            logger.info("CIRCUIT BREAK | %s", block_reason)
            notifier.send_circuit_break(block_reason)
            _cb_alerted = True
    else:
        _cb_alerted = False  # reset when circuit breaker clears
        for strategy in strategies:
            if strategy.should_enter(inds, regime, cfg):
                _cb_alerted = False  # fresh signal window; reset flag
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
```

Replace it with:

```python
if state_machine.state in (TradeState.IDLE, TradeState.WATCHING):
    allowed, block_reason = circuit_breaker.check(
        db, cfg, paper_broker.get_account_balance(), candle.timestamp
    )
    if not allowed:
        blocked = True
        logger.info("CIRCUIT BREAK | %s", block_reason)
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
```

- [ ] **Step 3: Update `send_trade_closed` call**

Find line 193:

```python
notifier.send_trade_closed(symbol, exit_pnl, candle.close, exit_reason)
```

Replace with:

```python
notifier.send_trade_closed(exit_pnl, candle.close, exit_reason)
```

- [ ] **Step 4: Run full test suite**

```
cd C:/projects/SniperBot_V2 && venv/Scripts/pytest -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: remove circuit break Discord alert and _cb_alerted flag from main"
```

---

## Self-Review

**Spec coverage:**
- TRADE OPENED unchanged — no tasks needed, confirmed
- TRADE CLOSED drops symbol — Task 2 step 1 covers notifier, Task 3 step 3 covers main, Task 1 covers tests
- CIRCUIT BREAK removed — Task 2 step 2 removes method, Task 3 step 2 removes call and flag, Task 1 step 3 removes test

**Placeholder scan:** None found.

**Type consistency:** `send_trade_closed(pnl, exit_price, reason)` used consistently across Task 1, 2, and 3.

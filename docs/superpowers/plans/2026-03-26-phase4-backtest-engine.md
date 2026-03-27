# Phase 4 — Backtest Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline OHLCV replay engine that runs historical Kraken candles through the existing regime → strategy → trade_manager stack and prints performance metrics to stdout via `python main.py --backtest`.

**Architecture:** `BacktestEngine` owns the full replay loop and is cleanly isolated from the live path — `main.py` delegates to it only when `--backtest` is passed. `BacktestBroker` implements the existing `BrokerBase` interface with fee/slippage-aware fills, so all live components (strategies, state machine, trade manager) work unchanged. The circuit breaker is not instantiated in the backtest path.

**Tech Stack:** Python stdlib (`os`, `argparse`, `collections.deque`), `numpy` (already a dependency), `pandas` (already a dependency), `requests` (already a dependency via `KrakenBackfill`), `PyYAML` (already a dependency)

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `backtest/__init__.py` | Empty package marker |
| Create | `backtest/engine.py` | `BacktestEngine.run()`, `_compute_metrics()`, `_print_results()` |
| Create | `execution/backtest_broker.py` | `BacktestBroker` — `BrokerBase` impl with slippage + per-order-type fees |
| Modify | `storage/trade_db.py` | Add `get_closed_trades()` method |
| Modify | `config/config.yaml` | Add `backtest.candle_count` key |
| Modify | `main.py` | Add `argparse --backtest` flag; delegate to `BacktestEngine` |
| Create | `tests/test_backtest_broker.py` | Fill price, fee selection, slippage, position/balance tracking |
| Modify | `tests/test_trade_db.py` | Test `get_closed_trades()` |
| Create | `tests/test_backtest_engine.py` | `_compute_metrics()` unit tests |

**Note on PnL accounting:** The state machine stores `pnl = (exit_fill_price - entry_fill_price) * size` in the DB. Fill prices already include slippage, so DB PnL reflects slippage but not fees. Fees are deducted directly from `BacktestBroker` balance. `_print_results` uses DB PnL for win/loss metrics and `broker.get_account_balance()` for the final balance — consistent with how PaperBroker works.

---

## Task 1: BacktestBroker

**Files:**
- Create: `execution/backtest_broker.py`
- Create: `tests/test_backtest_broker.py`

- [ ] **Step 1: Write the failing tests**

  Create `tests/test_backtest_broker.py`:

  ```python
  import pytest
  from execution.backtest_broker import BacktestBroker


  @pytest.fixture
  def broker():
      return BacktestBroker(
          initial_balance=10000.0,
          maker_fee=0.0016,
          taker_fee=0.0026,
          slippage_pct=0.001,
      )


  class TestInitialState:
      def test_initial_balance(self, broker):
          assert broker.get_account_balance() == 10000.0

      def test_no_position_initially(self, broker):
          assert broker.get_position("ATOM/USD") is None

      def test_cancel_order_always_false(self, broker):
          # Backtest fills are instant — cancellation is a no-op
          assert broker.cancel_order("any-id") is False


  class TestBuyFill:
      def test_buy_fill_price_includes_slippage(self, broker):
          broker.set_fill_price(10.0, 1000)
          result = broker.place_order("ATOM/USD", "buy", 100.0, "market")
          # buy fill = close * (1 + slippage) = 10.0 * 1.001 = 10.01
          assert result.fill_price == pytest.approx(10.01)

      def test_buy_deducts_cost_and_taker_fee(self, broker):
          broker.set_fill_price(10.0, 1000)
          broker.place_order("ATOM/USD", "buy", 100.0, "market")
          # fill = 10.01, notional = 1001.0, fee = 1001.0 * 0.0026 = 2.6026
          # deducted = 1001.0 + 2.6026 = 1003.6026
          expected = 10000.0 - 10.01 * 100.0 - 10.01 * 100.0 * 0.0026
          assert broker.get_account_balance() == pytest.approx(expected)

      def test_buy_creates_position(self, broker):
          broker.set_fill_price(10.0, 1000)
          broker.place_order("ATOM/USD", "buy", 100.0, "market")
          pos = broker.get_position("ATOM/USD")
          assert pos is not None
          assert pos.size == 100.0
          assert pos.symbol == "ATOM/USD"
          assert pos.side == "long"

      def test_buy_position_entry_price_is_fill_price(self, broker):
          broker.set_fill_price(10.0, 1000)
          result = broker.place_order("ATOM/USD", "buy", 100.0, "market")
          pos = broker.get_position("ATOM/USD")
          assert pos.entry_price == pytest.approx(result.fill_price)


  class TestSellFill:
      def test_sell_fill_price_includes_slippage(self, broker):
          broker.set_fill_price(10.0, 1000)
          broker.place_order("ATOM/USD", "buy", 100.0, "market")
          broker.set_fill_price(11.0, 2000)
          result = broker.place_order("ATOM/USD", "sell", 100.0, "market")
          # sell fill = close * (1 - slippage) = 11.0 * 0.999 = 10.989
          assert result.fill_price == pytest.approx(10.989)

      def test_sell_adds_proceeds_minus_taker_fee(self, broker):
          broker.set_fill_price(10.0, 1000)
          broker.place_order("ATOM/USD", "buy", 100.0, "market")
          balance_after_buy = broker.get_account_balance()
          broker.set_fill_price(11.0, 2000)
          broker.place_order("ATOM/USD", "sell", 100.0, "market")
          # sell fill = 10.989, proceeds = 10.989 * 100 = 1098.9
          # fee = 1098.9 * 0.0026 = 2.85714
          # added = 1098.9 - 2.85714 = 1096.04286
          expected = balance_after_buy + 10.989 * 100.0 - 10.989 * 100.0 * 0.0026
          assert broker.get_account_balance() == pytest.approx(expected)

      def test_sell_clears_position(self, broker):
          broker.set_fill_price(10.0, 1000)
          broker.place_order("ATOM/USD", "buy", 100.0, "market")
          broker.set_fill_price(11.0, 2000)
          broker.place_order("ATOM/USD", "sell", 100.0, "market")
          assert broker.get_position("ATOM/USD") is None


  class TestFeeSelection:
      def test_limit_order_uses_maker_fee(self):
          broker_limit = BacktestBroker(10000.0, 0.0016, 0.0026, 0.001)
          broker_market = BacktestBroker(10000.0, 0.0016, 0.0026, 0.001)
          broker_limit.set_fill_price(10.0, 1000)
          broker_market.set_fill_price(10.0, 1000)
          broker_limit.place_order("ATOM/USD", "buy", 100.0, "limit")
          broker_market.place_order("ATOM/USD", "buy", 100.0, "market")
          # maker fee (0.0016) < taker fee (0.0026) → limit buy costs less → higher balance
          assert broker_limit.get_account_balance() > broker_market.get_account_balance()
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```
  venv/Scripts/pytest tests/test_backtest_broker.py -v
  ```

  Expected: `ModuleNotFoundError: No module named 'execution.backtest_broker'`

- [ ] **Step 3: Create `execution/backtest_broker.py`**

  ```python
  """
  execution/backtest_broker.py

  Backtesting broker — implements BrokerBase for offline replay.
  Fills at candle close price adjusted for slippage, minus fee based on order_type.

  order_type="market" → taker fee
  order_type="limit"  → maker fee
  """

  import uuid
  from typing import Optional

  from execution.broker_base import BrokerBase
  from models import OrderResult, Position


  class BacktestBroker(BrokerBase):
      def __init__(
          self,
          initial_balance: float,
          maker_fee: float,
          taker_fee: float,
          slippage_pct: float,
      ):
          self._balance = initial_balance
          self._maker_fee = maker_fee
          self._taker_fee = taker_fee
          self._slippage_pct = slippage_pct
          self._position: Optional[Position] = None
          self._fill_price: float = 0.0
          self._fill_timestamp: int = 0

      def set_fill_price(self, price: float, timestamp: int) -> None:
          """Called by the state machine before place_order — same contract as PaperBroker."""
          self._fill_price = price
          self._fill_timestamp = timestamp

      def place_order(
          self, symbol: str, side: str, size: float, order_type: str
      ) -> OrderResult:
          fee_rate = self._taker_fee if order_type == "market" else self._maker_fee

          if side == "buy":
              fill_price = self._fill_price * (1.0 + self._slippage_pct)
              notional = fill_price * size
              fee = notional * fee_rate
              self._balance -= notional + fee
              self._position = Position(
                  symbol=symbol,
                  side="long",
                  size=size,
                  entry_price=fill_price,
                  entry_time=self._fill_timestamp,
              )
          else:  # sell
              fill_price = self._fill_price * (1.0 - self._slippage_pct)
              notional = fill_price * size
              fee = notional * fee_rate
              self._balance += notional - fee
              self._position = None

          return OrderResult(
              order_id=str(uuid.uuid4()),
              symbol=symbol,
              side=side,
              size=size,
              fill_price=fill_price,
              timestamp=self._fill_timestamp,
          )

      def get_position(self, symbol: str) -> Optional[Position]:
          if self._position and self._position.symbol == symbol:
              return self._position
          return None

      def get_account_balance(self) -> float:
          return self._balance

      def cancel_order(self, order_id: str) -> bool:
          """Backtest fills are instant — cancellation is always a no-op."""
          return False
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```
  venv/Scripts/pytest tests/test_backtest_broker.py -v
  ```

  Expected: all tests PASS

- [ ] **Step 5: Commit**

  ```bash
  git add execution/backtest_broker.py tests/test_backtest_broker.py
  git commit -m "feat: add BacktestBroker with slippage and per-order-type fees (Phase 4)"
  ```

---

## Task 2: TradeDB — get_closed_trades()

**Files:**
- Modify: `storage/trade_db.py`
- Modify: `tests/test_trade_db.py`

- [ ] **Step 1: Add failing test to `tests/test_trade_db.py`**

  Append this class to the existing file (after the last class):

  ```python
  class TestGetClosedTrades:
      def test_returns_empty_when_no_trades(self, db):
          assert db.get_closed_trades() == []

      def test_returns_only_closed_trades(self, db):
          # open trade — should NOT appear
          db.insert_trade("ATOM/USD", "momentum", "BREAKOUT", "buy", 10.0, 100.0, 1000)
          # closed trade — should appear
          trade_id = db.insert_trade("ATOM/USD", "trend_follow", "TRENDING", "buy", 10.0, 100.0, 2000)
          db.close_trade(trade_id, 11.0, 3000, 100.0)

          closed = db.get_closed_trades()
          assert len(closed) == 1
          assert closed[0]["id"] == trade_id
          assert closed[0]["pnl"] == pytest.approx(100.0)

      def test_returns_trades_ordered_by_exit_time(self, db):
          id1 = db.insert_trade("ATOM/USD", "momentum", "BREAKOUT", "buy", 10.0, 100.0, 1000)
          id2 = db.insert_trade("ATOM/USD", "momentum", "BREAKOUT", "buy", 10.0, 100.0, 2000)
          db.close_trade(id1, 11.0, 5000, 100.0)
          db.close_trade(id2, 11.0, 3000, 100.0)  # earlier exit time

          closed = db.get_closed_trades()
          assert closed[0]["id"] == id2  # exit_time=3000 comes first
          assert closed[1]["id"] == id1  # exit_time=5000 comes second
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```
  venv/Scripts/pytest tests/test_trade_db.py::TestGetClosedTrades -v
  ```

  Expected: `AttributeError: 'TradeDB' object has no attribute 'get_closed_trades'`

- [ ] **Step 3: Add `get_closed_trades()` to `storage/trade_db.py`**

  Add this method after `get_open_trades()` (around line 130):

  ```python
  def get_closed_trades(self) -> list:
      """Return all closed trades ordered by exit_time ascending."""
      conn = self._get_conn()
      rows = conn.execute(
          "SELECT * FROM trades WHERE status='closed' ORDER BY exit_time ASC"
      ).fetchall()
      return [dict(r) for r in rows]
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```
  venv/Scripts/pytest tests/test_trade_db.py -v
  ```

  Expected: all tests PASS

- [ ] **Step 5: Commit**

  ```bash
  git add storage/trade_db.py tests/test_trade_db.py
  git commit -m "feat: add TradeDB.get_closed_trades() for backtest metrics (Phase 4)"
  ```

---

## Task 3: BacktestEngine and metrics

**Files:**
- Create: `backtest/__init__.py`
- Create: `backtest/engine.py`
- Create: `tests/test_backtest_engine.py`

- [ ] **Step 1: Write failing tests for `_compute_metrics`**

  Create `tests/test_backtest_engine.py`:

  ```python
  import math
  import pytest
  from backtest.engine import _compute_metrics


  class TestComputeMetrics:
      def test_empty_returns_zero_trades(self):
          m = _compute_metrics([], 10000.0)
          assert m["total_trades"] == 0
          assert m["win_rate"] == 0.0
          assert m["profit_factor"] == math.inf
          assert m["max_drawdown_pct"] == 0.0
          assert m["sharpe"] == 0.0

      def test_all_wins(self):
          m = _compute_metrics([100.0, 200.0, 50.0], 10000.0)
          assert m["total_trades"] == 3
          assert m["wins"] == 3
          assert m["losses"] == 0
          assert m["win_rate"] == pytest.approx(1.0)
          assert m["profit_factor"] == math.inf

      def test_all_losses(self):
          m = _compute_metrics([-100.0, -200.0], 10000.0)
          assert m["total_trades"] == 2
          assert m["wins"] == 0
          assert m["losses"] == 2
          assert m["win_rate"] == pytest.approx(0.0)
          # gross profit = 0 → profit_factor = 0
          assert m["profit_factor"] == pytest.approx(0.0)

      def test_mixed_win_rate(self):
          m = _compute_metrics([100.0, -50.0, 100.0, -50.0], 10000.0)
          assert m["win_rate"] == pytest.approx(0.5)

      def test_profit_factor(self):
          # wins = 300, losses = 100 → PF = 3.0
          m = _compute_metrics([100.0, -50.0, 200.0, -50.0], 10000.0)
          assert m["profit_factor"] == pytest.approx(3.0)

      def test_max_drawdown(self):
          # equity: 10000 → 10100 (+100) → 9900 (-200)
          # peak = 10100, trough = 9900 → dd = 200/10100 ≈ 1.98%
          m = _compute_metrics([100.0, -200.0], 10000.0)
          expected_dd = (10100 - 9900) / 10100 * 100
          assert m["max_drawdown_pct"] == pytest.approx(expected_dd, rel=1e-4)

      def test_single_trade_sharpe_is_zero(self):
          # Only one trade — std dev undefined → sharpe = 0
          m = _compute_metrics([100.0], 10000.0)
          assert m["sharpe"] == 0.0

      def test_sharpe_positive_for_consistent_wins(self):
          # All wins of equal size → positive Sharpe
          m = _compute_metrics([100.0, 100.0, 100.0, 100.0], 10000.0)
          assert m["sharpe"] > 0
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```
  venv/Scripts/pytest tests/test_backtest_engine.py -v
  ```

  Expected: `ModuleNotFoundError: No module named 'backtest'`

- [ ] **Step 3: Create `backtest/__init__.py`**

  Create an empty file at `backtest/__init__.py`.

- [ ] **Step 4: Create `backtest/engine.py`**

  ```python
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
  from data.indicators import compute_all
  from models import Candle
  from storage.trade_db import TradeDB
  from core.regime_detector import RegimeDetector
  from core.state_machine import StateMachine, TradeState
  from core.trade_manager import TradeManager
  from execution.backtest_broker import BacktestBroker
  from strategies.momentum import MomentumStrategy
  from strategies.trend_follow import TrendFollowStrategy

  logger = logging.getLogger(__name__)


  def _candles_to_series(candles: list) -> tuple:
      opens   = pd.Series([c.open   for c in candles])
      highs   = pd.Series([c.high   for c in candles])
      lows    = pd.Series([c.low    for c in candles])
      closes  = pd.Series([c.close  for c in candles])
      volumes = pd.Series([c.volume for c in candles])
      return opens, highs, lows, closes, volumes


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
      returns = [p / initial_capital for p in pnls]
      if len(returns) > 1:
          mean_r = float(np.mean(returns))
          std_r = float(np.std(returns, ddof=1))
          sharpe = (mean_r / std_r * math.sqrt(len(returns))) if std_r > 0 else 0.0
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

      print("\n=== Backtest Results ===")
      print(f"Candles replayed : {replayed}  (warm-up: {warmup})")
      print(f"Trades           : {total}")

      if total == 0:
          print("No trades fired — check strategy thresholds or increase backtest.candle_count.")
          print("=======================\n")
          return

      print(f"Win rate         : {metrics['win_rate'] * 100:.1f}%")
      print(f"Profit factor    : {pf_str}")
      print(f"Max drawdown     : -{metrics['max_drawdown_pct']:.1f}%")
      print(f"Sharpe (trade)   : {metrics['sharpe']:.2f}")
      print(f"Final balance    : ${final_balance:,.2f}  ({pnl_pct:+.1f}%)")
      print("=======================\n")

      if metrics["win_rate"] > 0.9:
          print("WARNING: suspiciously high win rate — check for lookahead bias")
      if pf != math.inf and pf > 10:
          print("WARNING: suspiciously high profit factor")
      if total < 10:
          print("WARNING: too few trades for reliable statistics")


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
              print(
                  f"ERROR: Not enough candles for warm-up. "
                  f"Got {len(candles)}, need > {warmup}. "
                  f"Increase backtest.candle_count in config.yaml."
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
          for candle in replay_candles:
              buffer.append(candle)
              opens, highs, lows, closes, volumes = _candles_to_series(list(buffer))
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

          # ── Metrics ───────────────────────────────────────────────────────
          closed_trades = db.get_closed_trades()
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
  ```

- [ ] **Step 5: Run tests to verify they pass**

  ```
  venv/Scripts/pytest tests/test_backtest_engine.py -v
  ```

  Expected: all tests PASS

- [ ] **Step 6: Run full test suite to check for regressions**

  ```
  venv/Scripts/pytest -v
  ```

  Expected: all tests PASS

- [ ] **Step 7: Commit**

  ```bash
  git add backtest/__init__.py backtest/engine.py tests/test_backtest_engine.py
  git commit -m "feat: add BacktestEngine with replay loop and performance metrics (Phase 4)"
  ```

---

## Task 4: Config key + main.py wiring

**Files:**
- Modify: `config/config.yaml`
- Modify: `main.py`

- [ ] **Step 1: Add `candle_count` to `config/config.yaml`**

  Find the existing `backtest:` section (near bottom of file) and add `candle_count`:

  ```yaml
  # Phase 4 — Backtest Engine
  backtest:
    candle_count: 2000            # total candles to fetch (warm-up + replay)
    data_path: "data/historical"      # local CSV cache directory
    initial_capital: 10000.0          # starting portfolio value in USD
    maker_fee: 0.0016                 # Kraken maker fee (0.16%)
    taker_fee: 0.0026                 # Kraken taker fee (0.26%)
    slippage_pct: 0.001               # 0.1% slippage model
  ```

- [ ] **Step 2: Replace the `__main__` block in `main.py`**

  Find this block at the bottom of `main.py`:

  ```python
  if __name__ == "__main__":
      run()
  ```

  Replace it with:

  ```python
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
  ```

- [ ] **Step 3: Run full test suite to verify nothing broke**

  ```
  venv/Scripts/pytest -v
  ```

  Expected: all tests PASS

- [ ] **Step 4: Smoke-test the backtest flag parses correctly**

  ```
  venv/Scripts/python main.py --help
  ```

  Expected output includes:
  ```
  optional arguments:
    --backtest   Run backtest instead of live feed
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add config/config.yaml main.py
  git commit -m "feat: wire --backtest flag into main.py, add backtest.candle_count config (Phase 4)"
  ```

---

## Self-Review

**Spec coverage:**
- ✅ Fetch from Kraken at runtime — `KrakenBackfill` used in `BacktestEngine.run()`
- ✅ Configurable per order type fees — `BacktestBroker` selects maker/taker by `order_type`
- ✅ Circuit breaker disabled — not instantiated in engine
- ✅ stdout only — `_print_results()` prints, no file writes
- ✅ `python main.py --backtest` entry point — Task 4
- ✅ Metrics: total trades, win rate, profit factor, max drawdown, Sharpe — `_compute_metrics()`
- ✅ Sanity warnings — in `_print_results()`
- ✅ Logs to `backtest.db` — `TradeDB(cfg["database"]["backtest_path"])`
- ✅ Fresh state per run — all components instantiated inside `run()`
- ✅ Warm-up — first `backfill.candle_count` candles seed buffer only

**Type consistency check:**
- `BacktestBroker.__init__` takes `initial_balance, maker_fee, taker_fee, slippage_pct` — used identically in engine and tests ✅
- `_compute_metrics(pnls: list, initial_capital: float)` — called from `run()` and tested with same signature ✅
- `db.get_closed_trades()` — added to `TradeDB`, called in engine ✅
- `set_fill_price(price, timestamp)` — matches `BrokerBase` contract ✅

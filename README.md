# SniperBot V2

> All commands must be run from `C:/projects/SniperBot_V2`.

## Run the Bot

```bash
# Paper trading (default)
venv/Scripts/python main.py

# Backtest mode — replays historical data, no live feed
venv/Scripts/python main.py --backtest

# Custom config file
venv/Scripts/python main.py --config path/to/config.yaml
```

## Run the Dashboard

```bash
# Open in a separate terminal while the bot is running
# Accessible at http://localhost:5000
venv/Scripts/python dashboard/app.py
```

## Run Tests

```bash
# All tests
venv/Scripts/pytest -v

# Single test file
venv/Scripts/pytest tests/test_indicators.py

# Single test
venv/Scripts/pytest tests/test_indicators.py::TestEMA::test_fast_ema_above_slow_in_uptrend
```

## Install Dependencies

```bash
venv/Scripts/pip install -r requirements.txt
```

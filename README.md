# SniperBot V2

> All commands must be run from the project root. Use `venv/Scripts/python` on Windows or `venv/bin/python` on Linux/macOS.

## Setup: Credentials

The bot reads all credentials from `secrets/secrets.yaml`, which is gitignored and never committed. A template is included in the repo.

**First-time setup (run once after cloning):**

```bash
# Linux / macOS
cp secrets/secrets.yaml.example secrets/secrets.yaml

# Windows
copy secrets\secrets.yaml.example secrets\secrets.yaml
```

Then open `secrets/secrets.yaml` and fill in your values:

| Key | Required | Description |
|-----|----------|-------------|
| `alerts.discord_webhook` | Optional | Paste your Discord webhook URL to enable trade alerts |
| `alerts.telegram_bot_token` | Optional | Telegram bot token for Telegram alerts |
| `alerts.telegram_chat_id` | Optional | Telegram chat ID for Telegram alerts |
| `exchange.api_key` | Phase 6 only | Kraken API key (not needed for paper trading) |
| `exchange.api_secret` | Phase 6 only | Kraken API secret (not needed for paper trading) |

The bot runs fine without credentials — alerts are silently skipped if the webhook is blank.

---

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

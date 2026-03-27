"""
alerts/notifier.py

Sends trade and alert messages to Discord and/or Telegram.
Both channels are optional — missing or empty credentials are silently skipped.
Network errors are caught and logged; notification failure never crashes the bot.

Credentials come from secrets/secrets.yaml under the `alerts:` key:
    alerts:
      discord_webhook: "https://discord.com/api/webhooks/..."
      telegram_bot_token: "1234567890:ABC..."
      telegram_chat_id: "123456789"
"""

import logging
from typing import Optional

import requests
import yaml

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(
        self,
        discord_webhook: Optional[str],
        telegram_token: Optional[str],
        telegram_chat_id: Optional[str],
    ):
        self._discord_webhook: str = discord_webhook or ""
        self._telegram_token: str = telegram_token or ""
        self._telegram_chat_id: str = telegram_chat_id or ""

    @classmethod
    def from_secrets(cls, secrets_path: str = "secrets/secrets.yaml") -> "Notifier":
        """Load credentials from secrets.yaml. Returns a silent notifier on any error."""
        try:
            with open(secrets_path) as f:
                secrets = yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning("secrets.yaml not found at %s — alerts disabled", secrets_path)
            return cls(None, None, None)
        alerts = secrets.get("alerts") or {}
        return cls(
            discord_webhook=alerts.get("discord_webhook"),
            telegram_token=alerts.get("telegram_bot_token"),
            telegram_chat_id=alerts.get("telegram_chat_id"),
        )

    def send(self, message: str) -> None:
        """Send a raw message to all configured channels."""
        self._send_discord(message)
        self._send_telegram(message)

    def send_trade_opened(
        self, symbol: str, strategy: str, regime: str, price: float, stop: float
    ) -> None:
        msg = (
            f"TRADE OPENED\n"
            f"Symbol:   {symbol}\n"
            f"Strategy: {strategy}\n"
            f"Regime:   {regime}\n"
            f"Entry:    {price:.4f}\n"
            f"Stop:     {stop:.4f}"
        )
        self.send(msg)

    def send_trade_closed(
        self, symbol: str, pnl: float, exit_price: float, reason: str
    ) -> None:
        sign = "+" if pnl >= 0 else ""
        msg = (
            f"TRADE CLOSED\n"
            f"Symbol: {symbol}\n"
            f"Exit:   {exit_price:.4f}\n"
            f"P&L:    {sign}{pnl:.2f}\n"
            f"Reason: {reason}"
        )
        self.send(msg)

    def send_circuit_break(self, reason: str) -> None:
        self.send(f"CIRCUIT BREAK\n{reason}")

    def _send_discord(self, message: str) -> None:
        if not self._discord_webhook:
            return
        try:
            resp = requests.post(
                self._discord_webhook, json={"content": message}, timeout=5
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Discord notification failed: %s", exc)

    def _send_telegram(self, message: str) -> None:
        if not self._telegram_token or not self._telegram_chat_id:
            return
        try:
            url = f"https://api.telegram.org/bot{self._telegram_token}/sendMessage"
            resp = requests.post(
                url,
                json={"chat_id": self._telegram_chat_id, "text": message},
                timeout=5,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Telegram notification failed: %s", exc)

import pytest
from unittest.mock import patch, MagicMock
from alerts.notifier import Notifier


class TestNotifier:

    # --- Discord ---

    def test_send_posts_to_discord_webhook(self):
        notifier = Notifier(discord_webhook="https://discord.example/wh",
                            telegram_token=None, telegram_chat_id=None)
        with patch("alerts.notifier.requests.post") as mock_post:
            mock_post.return_value.raise_for_status = MagicMock()
            notifier.send("hello")
        mock_post.assert_called_once_with(
            "https://discord.example/wh",
            json={"content": "hello"},
            timeout=5,
        )

    def test_discord_failure_does_not_raise(self):
        notifier = Notifier("https://discord.example/wh", None, None)
        with patch("alerts.notifier.requests.post", side_effect=Exception("timeout")):
            notifier.send("hello")  # must not raise

    def test_discord_http_error_does_not_raise(self):
        notifier = Notifier("https://discord.example/wh", None, None)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("403 Forbidden")
        with patch("alerts.notifier.requests.post", return_value=mock_resp):
            notifier.send("hello")  # must not raise

    # --- Telegram ---

    def test_send_posts_to_telegram_api(self):
        notifier = Notifier(discord_webhook=None,
                            telegram_token="tok123", telegram_chat_id="chat456")
        with patch("alerts.notifier.requests.post") as mock_post:
            mock_post.return_value.raise_for_status = MagicMock()
            notifier.send("hello")
        mock_post.assert_called_once_with(
            "https://api.telegram.org/bottok123/sendMessage",
            json={"chat_id": "chat456", "text": "hello"},
            timeout=5,
        )

    def test_telegram_failure_does_not_raise(self):
        notifier = Notifier(None, "tok123", "chat456")
        with patch("alerts.notifier.requests.post", side_effect=Exception("timeout")):
            notifier.send("hello")  # must not raise

    def test_telegram_missing_chat_id_skips_call(self):
        notifier = Notifier(None, "tok123", None)
        with patch("alerts.notifier.requests.post") as mock_post:
            notifier.send("hello")
        mock_post.assert_not_called()

    # --- No credentials ---

    def test_no_credentials_makes_no_requests(self):
        notifier = Notifier(None, None, None)
        with patch("alerts.notifier.requests.post") as mock_post:
            notifier.send("hello")
        mock_post.assert_not_called()

    def test_empty_string_credentials_make_no_requests(self):
        notifier = Notifier("", "", "")
        with patch("alerts.notifier.requests.post") as mock_post:
            notifier.send("hello")
        mock_post.assert_not_called()

    # --- Both channels ---

    def test_send_calls_both_discord_and_telegram(self):
        notifier = Notifier("https://discord.example/wh", "tok123", "chat456")
        with patch("alerts.notifier.requests.post") as mock_post:
            mock_post.return_value.raise_for_status = MagicMock()
            notifier.send("hello")
        assert mock_post.call_count == 2

    # --- from_secrets ---

    def test_from_secrets_loads_all_fields(self, tmp_path):
        secrets_file = tmp_path / "secrets.yaml"
        secrets_file.write_text(
            "alerts:\n"
            "  discord_webhook: https://discord.example/wh\n"
            "  telegram_bot_token: tok999\n"
            "  telegram_chat_id: '777'\n"
        )
        n = Notifier.from_secrets(str(secrets_file))
        assert n._discord_webhook == "https://discord.example/wh"
        assert n._telegram_token == "tok999"
        assert n._telegram_chat_id == "777"

    def test_from_secrets_missing_file_returns_silent_notifier(self):
        n = Notifier.from_secrets("/nonexistent/path.yaml")
        # Should not raise; returned notifier makes no requests
        with patch("alerts.notifier.requests.post") as mock_post:
            n.send("hello")
        mock_post.assert_not_called()

    def test_from_secrets_empty_alerts_section_returns_silent_notifier(self, tmp_path):
        secrets_file = tmp_path / "secrets.yaml"
        secrets_file.write_text("exchange:\n  api_key: x\n")
        n = Notifier.from_secrets(str(secrets_file))
        with patch("alerts.notifier.requests.post") as mock_post:
            n.send("hello")
        mock_post.assert_not_called()

    def test_from_secrets_malformed_yaml_returns_silent_notifier(self, tmp_path):
        secrets_file = tmp_path / "secrets.yaml"
        secrets_file.write_text(": this is: not valid yaml: [\n")
        n = Notifier.from_secrets(str(secrets_file))
        with patch("alerts.notifier.requests.post") as mock_post:
            n.send("hello")
        mock_post.assert_not_called()

    # --- Message content ---

    def test_send_trade_opened_includes_key_fields(self):
        notifier = Notifier("https://discord.example/wh", None, None)
        captured = []
        with patch("alerts.notifier.requests.post") as mock_post:
            mock_post.return_value.raise_for_status = MagicMock()
            mock_post.side_effect = lambda url, json, timeout: captured.append(json["content"]) or MagicMock(raise_for_status=MagicMock())
            notifier.send_trade_opened("ATOM/USD", "momentum", "BREAKOUT", 7.25, 6.81)
        assert captured
        msg = captured[0]
        assert "ATOM/USD" in msg
        assert "momentum" in msg
        assert "7.2500" in msg
        assert "6.8100" in msg
        assert "BREAKOUT" in msg

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

    def test_send_trade_closed_shows_negative_pnl(self):
        notifier = Notifier("https://discord.example/wh", None, None)
        captured = []
        with patch("alerts.notifier.requests.post") as mock_post:
            mock_post.return_value.raise_for_status = MagicMock()
            mock_post.side_effect = lambda url, json, timeout: captured.append(json["content"]) or MagicMock(raise_for_status=MagicMock())
            notifier.send_trade_closed(-8.50, 7.10, "strategy_exit")
        msg = captured[0]
        assert "-8.50" in msg


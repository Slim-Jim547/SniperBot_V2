"""Tests for the dashboard Flask app."""
import time
import pytest
from storage.trade_db import TradeDB
from dashboard.app import create_app


@pytest.fixture
def db():
    d = TradeDB(":memory:")
    d.create_tables()
    return d


@pytest.fixture
def cfg():
    return {"symbols": ["ETH/USD"], "dashboard": {"refresh_seconds": 30}}


@pytest.fixture
def client(db, cfg):
    app = create_app(db, cfg)
    return app.test_client()


class TestApiStatus:
    def test_returns_200(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200

    def test_shape_with_empty_db(self, client):
        data = client.get("/api/status").get_json()
        assert "bot" in data
        assert "open_position" in data
        assert "today" in data
        assert data["open_position"] is None
        assert data["today"]["total_trades"] == 0

    def test_bot_state_keys(self, client):
        data = client.get("/api/status").get_json()
        bot = data["bot"]
        assert set(bot.keys()) == {"state", "balance", "regime", "last_close", "last_ts"}

    def test_open_position_populated(self, db, cfg):
        now = int(time.time())
        db.write_dashboard_state("IN_TRADE", 450.0, "TRENDING", 3500.0, now)
        db.insert_trade("ETH/USD", "momentum", "TRENDING", "buy", 3400.0, 0.015, now - 3600)
        client = create_app(db, cfg).test_client()

        data = client.get("/api/status").get_json()
        pos = data["open_position"]
        assert pos is not None
        assert pos["entry_price"] == pytest.approx(3400.0)
        assert pos["size"] == pytest.approx(0.015)
        assert pos["strategy"] == "momentum"
        assert pos["unrealized_pnl"] == pytest.approx((3500.0 - 3400.0) * 0.015, abs=0.01)

    def test_open_position_none_when_no_open_trades(self, db, cfg):
        now = int(time.time())
        tid = db.insert_trade("ETH/USD", "momentum", "TRENDING", "buy", 3000.0, 0.1, now - 7200)
        db.close_trade(tid, 3100.0, now - 3600, 10.0)
        client = create_app(db, cfg).test_client()
        data = client.get("/api/status").get_json()
        assert data["open_position"] is None


class TestApiTrades:
    def test_returns_empty_list(self, client):
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_returns_closed_trades(self, db, cfg):
        now = int(time.time())
        tid = db.insert_trade("ETH/USD", "trend_follow", "TRENDING", "buy", 3000.0, 0.1, now - 3600)
        db.close_trade(tid, 3100.0, now, 10.0)
        client = create_app(db, cfg).test_client()
        data = client.get("/api/trades").get_json()
        assert len(data) == 1
        assert data[0]["pnl"] == pytest.approx(10.0)
        assert data[0]["strategy"] == "trend_follow"


class TestIndex:
    def test_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_contains_refresh_interval(self, client):
        resp = client.get("/")
        assert b"30" in resp.data

    def test_contains_brand(self, client):
        resp = client.get("/")
        assert b"SniperBot" in resp.data

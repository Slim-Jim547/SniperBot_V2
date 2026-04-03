"""
dashboard/app.py

Flask dashboard for SniperBot V2.

Usage (standalone):
    venv/Scripts/python dashboard/app.py

Routes:
    GET /            — HTML page with auto-refresh
    GET /api/status  — JSON: bot state, open position, today's summary
    GET /api/trades  — JSON: last 20 closed trades
"""

import os
import sys
import yaml

# Ensure project root is on sys.path so sibling packages (storage, etc.) can be imported
# regardless of which directory Python was launched from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, render_template
from storage.trade_db import TradeDB


def create_app(db: TradeDB, cfg: dict) -> Flask:
    """
    Factory that creates the Flask app with an injected TradeDB.
    Keeping db as a parameter makes the app trivially testable with
    an in-memory database.
    """
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    )
    refresh_seconds = cfg["dashboard"]["refresh_seconds"]
    symbol = cfg["symbols"][0]

    @app.route("/")
    def index():
        return render_template("index.html", refresh_seconds=refresh_seconds)

    @app.route("/api/status")
    def api_status():
        bot_state = db.get_dashboard_state()
        open_trades = db.get_open_trades(symbol)
        today = db.get_today_summary()

        open_position = None
        if open_trades:
            t = open_trades[0]
            last_close = bot_state["last_close"]
            unrealized_pnl = (
                round((last_close - t["entry_price"]) * t["size"], 2)
                if last_close > 0
                else None
            )
            open_position = {
                "symbol":        t["symbol"],
                "strategy":      t["strategy"],
                "regime":        t["regime"],
                "entry_price":   t["entry_price"],
                "size":          t["size"],
                "entry_time":    t["entry_time"],
                "unrealized_pnl": unrealized_pnl,
            }

        return jsonify({
            "bot":           bot_state,
            "open_position": open_position,
            "today":         today,
        })

    @app.route("/api/trades")
    def api_trades():
        return jsonify(db.get_recent_trades(20))

    return app


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SniperBot V2 Dashboard")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    db_path = cfg["database"]["path"]
    db = TradeDB(db_path)
    db.create_tables()

    port = cfg["dashboard"]["port"]
    app = create_app(db, cfg)
    print(f"Dashboard running at http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)

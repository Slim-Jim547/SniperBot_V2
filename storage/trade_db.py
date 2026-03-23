"""
storage/trade_db.py

Single module for all SQLite reads and writes.
No other module touches the database directly.
"""

import sqlite3
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TradeDB:
    def __init__(self, db_path: str):
        self._path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def create_tables(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT NOT NULL,
                strategy    TEXT NOT NULL,
                regime      TEXT NOT NULL,
                side        TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price  REAL,
                size        REAL NOT NULL,
                pnl         REAL,
                entry_time  INTEGER NOT NULL,
                exit_time   INTEGER,
                status      TEXT NOT NULL DEFAULT 'open'
            );

            CREATE TABLE IF NOT EXISTS signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT NOT NULL,
                strategy    TEXT NOT NULL,
                regime      TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                blocked     INTEGER NOT NULL DEFAULT 0,
                block_reason TEXT,
                timestamp   INTEGER NOT NULL,
                indicators  TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_summary (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT NOT NULL UNIQUE,
                total_trades INTEGER DEFAULT 0,
                wins        INTEGER DEFAULT 0,
                losses      INTEGER DEFAULT 0,
                total_pnl   REAL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS bot_state (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL
            );
        """)
        conn.commit()

    def list_tables(self) -> list:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return [row["name"] for row in rows]

    # ── Trades ────────────────────────────────────────────────────────────

    def insert_trade(
        self,
        symbol: str,
        strategy: str,
        regime: str,
        side: str,
        entry_price: float,
        size: float,
        entry_time: int,
    ) -> int:
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO trades (symbol, strategy, regime, side, entry_price, size, entry_time)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (symbol, strategy, regime, side, entry_price, size, entry_time),
        )
        conn.commit()
        return cursor.lastrowid

    def close_trade(
        self, trade_id: int, exit_price: float, exit_time: int, pnl: float
    ):
        conn = self._get_conn()
        conn.execute(
            """UPDATE trades SET exit_price=?, exit_time=?, pnl=?, status='closed'
               WHERE id=?""",
            (exit_price, exit_time, pnl, trade_id),
        )
        conn.commit()

    def get_trade(self, trade_id: int) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        return dict(row) if row else None

    def get_open_trades(self, symbol: str) -> list:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM trades WHERE symbol=? AND status='open'", (symbol,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Signals ───────────────────────────────────────────────────────────

    def insert_signal(
        self,
        symbol: str,
        strategy: str,
        regime: str,
        signal_type: str,
        blocked: bool,
        block_reason: Optional[str],
        timestamp: int,
        indicators: dict,
    ):
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO signals
               (symbol, strategy, regime, signal_type, blocked, block_reason, timestamp, indicators)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                symbol, strategy, regime, signal_type,
                int(blocked), block_reason, timestamp,
                json.dumps(indicators),
            ),
        )
        conn.commit()

    # ── Bot State ─────────────────────────────────────────────────────────

    def set_state(self, key: str, value: str):
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()

    def get_state(self, key: str) -> Optional[str]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value FROM bot_state WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None

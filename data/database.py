"""SQLite persistence layer for trades, signals, and equity snapshots."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import config


@dataclass
class TradeRecord:
    """Represents a single executed trade stored in the database."""

    symbol: str
    side: str
    quantity: float
    price: float
    strategy: str
    order_id: str
    timestamp: datetime
    id: Optional[int] = None


class Database:
    """SQLite database interface for persisting trading activity."""

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS trades (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol    TEXT    NOT NULL,
            side      TEXT    NOT NULL,
            quantity  REAL    NOT NULL,
            price     REAL    NOT NULL,
            strategy  TEXT    NOT NULL,
            order_id  TEXT    NOT NULL,
            timestamp TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS equity_snapshots (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            equity    REAL    NOT NULL,
            timestamp TEXT    NOT NULL
        );
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or config.DB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        """Open the database connection and create tables if they don't exist."""
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self._SCHEMA)
        self._conn.commit()

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() must be called before any operation.")
        return self._conn

    def insert_trade(self, trade: TradeRecord) -> int:
        """Persist a filled trade and return its new row id."""
        conn = self._require_conn()
        cursor = conn.execute(
            """INSERT INTO trades (symbol, side, quantity, price, strategy, order_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                trade.symbol,
                trade.side,
                trade.quantity,
                trade.price,
                trade.strategy,
                trade.order_id,
                trade.timestamp.isoformat(),
            ),
        )
        conn.commit()
        return cursor.lastrowid

    def get_trades(
        self,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        limit: int = 100,
    ) -> list[TradeRecord]:
        """Query the trades table with optional filters, ordered by timestamp desc."""
        conn = self._require_conn()
        conditions: list[str] = []
        params: list = []

        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if strategy:
            conditions.append("strategy = ?")
            params.append(strategy)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)

        rows = conn.execute(
            f"SELECT * FROM trades {where} ORDER BY timestamp DESC LIMIT ?", params
        ).fetchall()

        return [
            TradeRecord(
                id=row["id"],
                symbol=row["symbol"],
                side=row["side"],
                quantity=row["quantity"],
                price=row["price"],
                strategy=row["strategy"],
                order_id=row["order_id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
            )
            for row in rows
        ]

    def insert_equity_snapshot(self, equity: float, timestamp: datetime) -> None:
        """Save a portfolio equity snapshot for the equity curve."""
        conn = self._require_conn()
        conn.execute(
            "INSERT INTO equity_snapshots (equity, timestamp) VALUES (?, ?)",
            (equity, timestamp.isoformat()),
        )
        conn.commit()

    def get_equity_curve(self) -> list[dict]:
        """Return all equity snapshots ordered by timestamp ascending."""
        conn = self._require_conn()
        rows = conn.execute(
            "SELECT equity, timestamp FROM equity_snapshots ORDER BY timestamp ASC"
        ).fetchall()
        return [{"equity": row["equity"], "timestamp": row["timestamp"]} for row in rows]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

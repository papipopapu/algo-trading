"""Tests for data/database.py — uses an in-memory SQLite database."""

import pytest
from datetime import datetime, timezone

from data.database import Database, TradeRecord


@pytest.fixture
def db():
    """Fresh in-memory database for each test."""
    database = Database(db_path=":memory:")
    database.connect()
    yield database
    database.close()


def _trade(**kwargs) -> TradeRecord:
    defaults = dict(
        symbol="AAPL",
        side="buy",
        quantity=10.0,
        price=150.0,
        strategy="sma_crossover",
        order_id="order-001",
        timestamp=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return TradeRecord(**defaults)


# ── connect ──────────────────────────────────────────────────────────────────

def test_connect_creates_tables(db):
    tables = db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {row[0] for row in tables}
    assert "trades" in names
    assert "equity_snapshots" in names


# ── insert_trade ──────────────────────────────────────────────────────────────

def test_insert_trade_returns_id(db):
    row_id = db.insert_trade(_trade())
    assert isinstance(row_id, int)
    assert row_id >= 1


def test_insert_trade_persists_data(db):
    db.insert_trade(_trade(symbol="TSLA", price=200.0, order_id="ord-42"))
    trades = db.get_trades()
    assert len(trades) == 1
    t = trades[0]
    assert t.symbol == "TSLA"
    assert t.price == 200.0
    assert t.order_id == "ord-42"


def test_insert_multiple_trades(db):
    for i in range(3):
        db.insert_trade(_trade(order_id=f"ord-{i}"))
    assert len(db.get_trades()) == 3


# ── get_trades ────────────────────────────────────────────────────────────────

def test_get_trades_returns_all(db):
    db.insert_trade(_trade(symbol="AAPL"))
    db.insert_trade(_trade(symbol="MSFT"))
    trades = db.get_trades()
    assert len(trades) == 2


def test_get_trades_filter_by_symbol(db):
    db.insert_trade(_trade(symbol="AAPL"))
    db.insert_trade(_trade(symbol="MSFT"))
    trades = db.get_trades(symbol="AAPL")
    assert len(trades) == 1
    assert trades[0].symbol == "AAPL"


def test_get_trades_filter_by_strategy(db):
    db.insert_trade(_trade(strategy="sma_crossover"))
    db.insert_trade(_trade(strategy="rsi_mean_reversion"))
    trades = db.get_trades(strategy="rsi_mean_reversion")
    assert len(trades) == 1
    assert trades[0].strategy == "rsi_mean_reversion"


def test_get_trades_filter_by_symbol_and_strategy(db):
    db.insert_trade(_trade(symbol="AAPL", strategy="sma_crossover"))
    db.insert_trade(_trade(symbol="AAPL", strategy="rsi_mean_reversion"))
    db.insert_trade(_trade(symbol="MSFT", strategy="sma_crossover"))
    trades = db.get_trades(symbol="AAPL", strategy="sma_crossover")
    assert len(trades) == 1


def test_get_trades_respects_limit(db):
    for i in range(10):
        db.insert_trade(_trade(order_id=f"ord-{i}"))
    trades = db.get_trades(limit=3)
    assert len(trades) == 3


def test_get_trades_ordered_by_timestamp_desc(db):
    t1 = _trade(timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc), order_id="a")
    t2 = _trade(timestamp=datetime(2024, 6, 1, tzinfo=timezone.utc), order_id="b")
    db.insert_trade(t1)
    db.insert_trade(t2)
    trades = db.get_trades()
    assert trades[0].timestamp > trades[1].timestamp


def test_get_trades_timestamp_roundtrip(db):
    ts = datetime(2024, 3, 22, 14, 45, 30, tzinfo=timezone.utc)
    db.insert_trade(_trade(timestamp=ts))
    trades = db.get_trades()
    assert trades[0].timestamp == ts


def test_get_trades_empty(db):
    assert db.get_trades() == []


# ── equity snapshots ──────────────────────────────────────────────────────────

def test_insert_equity_snapshot(db):
    db.insert_equity_snapshot(100_000.0, datetime(2024, 1, 1, tzinfo=timezone.utc))
    curve = db.get_equity_curve()
    assert len(curve) == 1
    assert curve[0]["equity"] == 100_000.0


def test_get_equity_curve_ordered_asc(db):
    db.insert_equity_snapshot(100_000.0, datetime(2024, 1, 1, tzinfo=timezone.utc))
    db.insert_equity_snapshot(105_000.0, datetime(2024, 6, 1, tzinfo=timezone.utc))
    db.insert_equity_snapshot(98_000.0, datetime(2024, 3, 1, tzinfo=timezone.utc))
    curve = db.get_equity_curve()
    equities = [c["equity"] for c in curve]
    assert equities == [100_000.0, 98_000.0, 105_000.0]


def test_get_equity_curve_empty(db):
    assert db.get_equity_curve() == []


# ── error handling ────────────────────────────────────────────────────────────

def test_operations_without_connect_raise():
    db = Database(db_path=":memory:")
    with pytest.raises(RuntimeError, match="connect()"):
        db.insert_trade(_trade())


def test_close_is_idempotent(db):
    db.close()
    db.close()  # should not raise

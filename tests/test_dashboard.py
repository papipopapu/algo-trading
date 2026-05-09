"""Tests for dashboard/api.py — Alpaca client and database are fully mocked."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import dashboard.api as dashboard_module
from dashboard.api import app
from data.database import Database, TradeRecord
from execution.alpaca_client import AlpacaClient


# ── fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    mock_client = MagicMock(spec=AlpacaClient)
    mock_db = MagicMock(spec=Database)
    monkeypatch.setattr("dashboard.api._client", mock_client)
    monkeypatch.setattr("dashboard.api._db", mock_db)
    monkeypatch.setattr("dashboard.api._latest_ticks", {})
    return TestClient(app), mock_client, mock_db


def _trade(symbol="AAPL", side="buy", price=150.0, strategy="sma"):
    return TradeRecord(
        id=1, symbol=symbol, side=side, quantity=1.0, price=price,
        strategy=strategy, order_id="ord-1",
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
    )


# ── GET / ─────────────────────────────────────────────────────────────────────

def test_dashboard_returns_html(client):
    tc, _, _ = client
    r = tc.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Algo Trading Dashboard" in r.text


def test_dashboard_contains_chart_js(client):
    tc, _, _ = client
    r = tc.get("/")
    assert "chart.js" in r.text.lower()


def test_dashboard_contains_refresh_interval(client):
    tc, _, _ = client
    r = tc.get("/")
    assert "setInterval" in r.text
    assert "10000" in r.text


# ── GET /account ──────────────────────────────────────────────────────────────

def test_get_account_returns_data(client):
    tc, mock_c, _ = client
    mock_c.get_account.return_value = {
        "id": "acc-1", "equity": 10000.0, "buying_power": 5000.0,
        "cash": 5000.0, "portfolio_value": 10000.0, "status": "ACTIVE",
    }
    r = tc.get("/account")
    assert r.status_code == 200
    data = r.json()
    assert data["equity"] == 10000.0
    assert data["status"] == "ACTIVE"


def test_get_account_returns_503_on_error(client):
    tc, mock_c, _ = client
    mock_c.get_account.side_effect = RuntimeError("not connected")
    r = tc.get("/account")
    assert r.status_code == 503


# ── GET /positions ────────────────────────────────────────────────────────────

def test_get_positions_returns_list(client):
    tc, mock_c, _ = client
    mock_c.get_positions.return_value = [
        {"symbol": "AAPL", "qty": 10.0, "side": "long",
         "market_value": 1500.0, "unrealized_pl": 50.0, "avg_entry_price": 145.0},
    ]
    r = tc.get("/positions")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["symbol"] == "AAPL"


def test_get_positions_empty_list(client):
    tc, mock_c, _ = client
    mock_c.get_positions.return_value = []
    r = tc.get("/positions")
    assert r.status_code == 200
    assert r.json() == []


def test_get_positions_returns_503_on_error(client):
    tc, mock_c, _ = client
    mock_c.get_positions.side_effect = RuntimeError("not connected")
    r = tc.get("/positions")
    assert r.status_code == 503


# ── GET /trades ───────────────────────────────────────────────────────────────

def test_get_trades_returns_serialized_records(client):
    tc, _, mock_db = client
    mock_db.get_trades.return_value = [_trade()]
    r = tc.get("/trades")
    assert r.status_code == 200
    trades = r.json()
    assert len(trades) == 1
    assert trades[0]["symbol"] == "AAPL"
    assert trades[0]["side"] == "buy"
    assert trades[0]["price"] == 150.0
    assert "timestamp" in trades[0]


def test_get_trades_timestamp_is_iso_string(client):
    tc, _, mock_db = client
    mock_db.get_trades.return_value = [_trade()]
    r = tc.get("/trades")
    ts = r.json()[0]["timestamp"]
    # must be parseable as ISO datetime
    datetime.fromisoformat(ts)


def test_get_trades_passes_symbol_filter(client):
    tc, _, mock_db = client
    mock_db.get_trades.return_value = []
    tc.get("/trades?symbol=AAPL")
    mock_db.get_trades.assert_called_once_with(symbol="AAPL", strategy=None, limit=50)


def test_get_trades_passes_strategy_filter(client):
    tc, _, mock_db = client
    mock_db.get_trades.return_value = []
    tc.get("/trades?strategy=sma_crossover")
    mock_db.get_trades.assert_called_once_with(symbol=None, strategy="sma_crossover", limit=50)


def test_get_trades_passes_limit(client):
    tc, _, mock_db = client
    mock_db.get_trades.return_value = []
    tc.get("/trades?limit=10")
    mock_db.get_trades.assert_called_once_with(symbol=None, strategy=None, limit=10)


def test_get_trades_empty_returns_empty_list(client):
    tc, _, mock_db = client
    mock_db.get_trades.return_value = []
    r = tc.get("/trades")
    assert r.status_code == 200
    assert r.json() == []


# ── GET /equity ───────────────────────────────────────────────────────────────

def test_get_equity_curve_returns_list(client):
    tc, _, mock_db = client
    mock_db.get_equity_curve.return_value = [
        {"equity": 10000.0, "timestamp": "2024-01-01T00:00:00"},
        {"equity": 10200.0, "timestamp": "2024-01-02T00:00:00"},
    ]
    r = tc.get("/equity")
    assert r.status_code == 200
    pts = r.json()
    assert len(pts) == 2
    assert pts[1]["equity"] == 10200.0


def test_get_equity_curve_empty(client):
    tc, _, mock_db = client
    mock_db.get_equity_curve.return_value = []
    r = tc.get("/equity")
    assert r.status_code == 200
    assert r.json() == []


# ── GET /tickers ──────────────────────────────────────────────────────────────

def test_get_tickers_returns_empty_dict_by_default(client):
    tc, _, _ = client
    r = tc.get("/tickers")
    assert r.status_code == 200
    assert r.json() == {}


def test_get_tickers_returns_populated_data(monkeypatch):
    mock_client = MagicMock(spec=AlpacaClient)
    mock_db = MagicMock(spec=Database)
    ticks = {
        "TSLA": {"price": 215.30, "size": 50, "timestamp": "2024-01-15T14:30:00+00:00"},
        "NVDA": {"price": 600.10, "size": 100, "timestamp": "2024-01-15T14:30:01+00:00"},
    }
    monkeypatch.setattr("dashboard.api._client", mock_client)
    monkeypatch.setattr("dashboard.api._db", mock_db)
    monkeypatch.setattr("dashboard.api._latest_ticks", ticks)

    tc = TestClient(app)
    r = tc.get("/tickers")
    assert r.status_code == 200
    data = r.json()
    assert data["TSLA"]["price"] == 215.30
    assert data["NVDA"]["price"] == 600.10


# ── HTML tickers tab ──────────────────────────────────────────────────────────

def test_dashboard_contains_tickers_tab(client):
    tc, _, _ = client
    r = tc.get("/")
    assert r.status_code == 200
    assert "tickers" in r.text.lower()


def test_dashboard_contains_refresh_tickers_function(client):
    tc, _, _ = client
    r = tc.get("/")
    assert "refreshTickers" in r.text

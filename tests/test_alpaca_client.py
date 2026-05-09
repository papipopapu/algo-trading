"""Tests for execution/alpaca_client.py — Alpaca SDK calls are fully mocked."""

import pytest
import pandas as pd
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

from execution.alpaca_client import AlpacaClient


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_client() -> AlpacaClient:
    client = AlpacaClient()
    client.api_key = "test-key"
    client.secret_key = "test-secret"
    return client


def _connected_client() -> tuple[AlpacaClient, MagicMock, MagicMock]:
    """Return a client with mocked _trading and _data internals."""
    client = _make_client()
    mock_trading = MagicMock()
    mock_data = MagicMock()
    client._trading = mock_trading
    client._data = mock_data
    return client, mock_trading, mock_data


# ── connect ───────────────────────────────────────────────────────────────────

def test_connect_initializes_trading_client():
    client = _make_client()
    with patch("execution.alpaca_client.TradingClient") as MockTrading, \
         patch("execution.alpaca_client.StockHistoricalDataClient"):
        client.connect()
        MockTrading.assert_called_once_with(
            api_key="test-key", secret_key="test-secret", paper=True
        )


def test_connect_initializes_data_client():
    client = _make_client()
    with patch("execution.alpaca_client.TradingClient"), \
         patch("execution.alpaca_client.StockHistoricalDataClient") as MockData:
        client.connect()
        MockData.assert_called_once_with(
            api_key="test-key", secret_key="test-secret"
        )


def test_operations_without_connect_raise():
    client = _make_client()
    with pytest.raises(RuntimeError, match="connect()"):
        client.get_account()


# ── get_account ───────────────────────────────────────────────────────────────

def test_get_account_returns_dict(mocker):
    client, mock_trading, _ = _connected_client()

    mock_account = MagicMock()
    mock_account.id = "acc-123"
    mock_account.equity = "100000.00"
    mock_account.buying_power = "50000.00"
    mock_account.cash = "50000.00"
    mock_account.portfolio_value = "100000.00"
    mock_account.status = "ACTIVE"
    mock_trading.get_account.return_value = mock_account

    result = client.get_account()

    assert result["id"] == "acc-123"
    assert result["equity"] == 100_000.0
    assert result["buying_power"] == 50_000.0
    assert result["status"] == "ACTIVE"


# ── submit_order ──────────────────────────────────────────────────────────────

def _mock_order(symbol="AAPL", qty=10, side="buy", order_type="market", limit_price=None):
    o = MagicMock()
    o.id = "ord-abc"
    o.symbol = symbol
    o.qty = str(qty)
    o.side = side
    o.type = order_type
    o.status = "accepted"
    o.limit_price = str(limit_price) if limit_price else None
    return o


def test_submit_market_order_buy(mocker):
    client, mock_trading, _ = _connected_client()
    mock_trading.submit_order.return_value = _mock_order()

    with patch("execution.alpaca_client.MarketOrderRequest") as MockReq:
        result = client.submit_order("AAPL", 10, "buy")

    assert result["id"] == "ord-abc"
    assert result["symbol"] == "AAPL"
    MockReq.assert_called_once()


def test_submit_market_order_sell(mocker):
    client, mock_trading, _ = _connected_client()
    mock_trading.submit_order.return_value = _mock_order(side="sell")

    with patch("execution.alpaca_client.MarketOrderRequest"):
        result = client.submit_order("AAPL", 5, "sell")

    assert result["status"] == "accepted"


def test_submit_limit_order(mocker):
    client, mock_trading, _ = _connected_client()
    mock_trading.submit_order.return_value = _mock_order(
        order_type="limit", limit_price=149.50
    )

    with patch("execution.alpaca_client.LimitOrderRequest") as MockReq:
        result = client.submit_order("AAPL", 10, "buy", order_type="limit", limit_price=149.50)

    MockReq.assert_called_once()
    assert result["limit_price"] == 149.50


def test_submit_limit_order_without_price_raises():
    client, _, _ = _connected_client()
    with pytest.raises(ValueError, match="limit_price"):
        client.submit_order("AAPL", 10, "buy", order_type="limit")


# ── get_positions ─────────────────────────────────────────────────────────────

def test_get_positions_returns_list():
    client, mock_trading, _ = _connected_client()

    pos = MagicMock()
    pos.symbol = "AAPL"
    pos.qty = "10"
    pos.side = "long"
    pos.market_value = "1500.00"
    pos.unrealized_pl = "50.00"
    pos.avg_entry_price = "145.00"
    mock_trading.get_all_positions.return_value = [pos]

    result = client.get_positions()

    assert len(result) == 1
    assert result[0]["symbol"] == "AAPL"
    assert result[0]["unrealized_pl"] == 50.0


def test_get_positions_empty():
    client, mock_trading, _ = _connected_client()
    mock_trading.get_all_positions.return_value = []
    assert client.get_positions() == []


# ── get_historical_bars ───────────────────────────────────────────────────────

def _mock_bars_response(symbol: str) -> MagicMock:
    """Build a mock that mimics the MultiIndex DataFrame alpaca-py returns."""
    idx = pd.MultiIndex.from_tuples(
        [(symbol, datetime(2024, 1, 2, tzinfo=timezone.utc)),
         (symbol, datetime(2024, 1, 3, tzinfo=timezone.utc))],
        names=["symbol", "timestamp"],
    )
    df = pd.DataFrame(
        {"open": [150.0, 152.0], "high": [155.0, 157.0],
         "low": [149.0, 151.0], "close": [153.0, 156.0], "volume": [1_000_000, 900_000]},
        index=idx,
    )
    mock_resp = MagicMock()
    mock_resp.df = df
    return mock_resp


@pytest.mark.parametrize("timeframe", ["1Day", "1Week", "1Month"])
def test_get_historical_bars_valid_timeframes(timeframe):
    client, _, mock_data = _connected_client()
    mock_data.get_stock_bars.return_value = _mock_bars_response("AAPL")

    df = client.get_historical_bars("AAPL", timeframe, "2024-01-01", "2024-01-31")

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2


def test_get_historical_bars_invalid_timeframe_raises():
    client, _, _ = _connected_client()
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        client.get_historical_bars("AAPL", "invalid", "2024-01-01", "2024-01-31")


def test_get_historical_bars_drops_symbol_from_index():
    client, _, mock_data = _connected_client()
    mock_data.get_stock_bars.return_value = _mock_bars_response("AAPL")

    df = client.get_historical_bars("AAPL", "1Day", "2024-01-01", "2024-01-31")

    assert df.index.name == "timestamp"
    assert not isinstance(df.index, pd.MultiIndex)


# ── cancel_order ──────────────────────────────────────────────────────────────

def test_cancel_order_calls_sdk():
    client, mock_trading, _ = _connected_client()
    client.cancel_order("ord-xyz")
    mock_trading.cancel_order_by_id.assert_called_once_with("ord-xyz")

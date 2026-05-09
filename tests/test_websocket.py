"""Tests for execution/websocket.py.

Unit tests are fully mocked; integration tests (marked 'integration') open
real WebSocket connections to the Alpaca paper-trading endpoint.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from config import config
from execution.websocket import AlpacaWebSocket


# ── shared async no-ops ───────────────────────────────────────────────────────

async def _noop_bar(bar): pass
async def _noop_tick(tick): pass
async def _noop_order(update): pass


async def _run_forever_noop():
    """Simulates _run_forever completing immediately."""


def _make_ws() -> AlpacaWebSocket:
    return AlpacaWebSocket("test-key", "test-secret")


# ── on_minute_bar / on_daily_bar ──────────────────────────────────────────────

def test_on_minute_bar_registers_handler():
    ws = _make_ws()
    ws.on_minute_bar(_noop_bar)
    assert ws._minute_bar_handler is _noop_bar


def test_on_daily_bar_registers_handler():
    ws = _make_ws()
    ws.on_daily_bar(_noop_bar)
    assert ws._daily_bar_handler is _noop_bar


def test_on_trade_registers_handler():
    ws = _make_ws()
    ws.on_trade(_noop_tick)
    assert ws._tick_handler is _noop_tick


def test_on_order_update_registers_handler():
    ws = _make_ws()
    ws.on_order_update(_noop_order)
    assert ws._order_handler is _noop_order


# ── subscribe methods ─────────────────────────────────────────────────────────

def test_subscribe_minute_bars_stores_symbols():
    ws = _make_ws()
    ws.subscribe_minute_bars(["AAPL", "TSLA"])
    assert ws._minute_symbols == ["AAPL", "TSLA"]


def test_subscribe_minute_bars_copies_list():
    ws = _make_ws()
    orig = ["AAPL"]
    ws.subscribe_minute_bars(orig)
    orig.append("TSLA")
    assert ws._minute_symbols == ["AAPL"]


def test_subscribe_daily_bars_stores_symbols():
    ws = _make_ws()
    ws.subscribe_daily_bars(["AAPL", "TSLA"])
    assert ws._daily_symbols == ["AAPL", "TSLA"]


def test_subscribe_daily_bars_copies_list():
    ws = _make_ws()
    orig = ["AAPL"]
    ws.subscribe_daily_bars(orig)
    orig.append("TSLA")
    assert ws._daily_symbols == ["AAPL"]


def test_subscribe_ticks_stores_symbols():
    ws = _make_ws()
    ws.subscribe_ticks(["TSLA", "NVDA"])
    assert ws._tick_symbols == ["TSLA", "NVDA"]


def test_subscribe_ticks_copies_list():
    ws = _make_ws()
    orig = ["TSLA"]
    ws.subscribe_ticks(orig)
    orig.append("NVDA")
    assert ws._tick_symbols == ["TSLA"]


# ── run ───────────────────────────────────────────────────────────────────────

async def test_run_creates_streams_with_correct_args():
    ws = _make_ws()
    with patch("execution.websocket.StockDataStream") as MockData, \
         patch("execution.websocket.TradingStream") as MockTrade:
        MockData.return_value._run_forever = _run_forever_noop
        MockTrade.return_value._run_forever = _run_forever_noop
        await ws.run()

    MockData.assert_called_once_with("test-key", "test-secret")
    MockTrade.assert_called_once_with("test-key", "test-secret", paper=True)


async def test_run_subscribes_daily_bars_when_handler_and_symbols_set():
    ws = _make_ws()
    ws.on_daily_bar(_noop_bar)
    ws.subscribe_daily_bars(["AAPL", "TSLA"])

    with patch("execution.websocket.StockDataStream") as MockData, \
         patch("execution.websocket.TradingStream") as MockTrade:
        mock_ds = MagicMock()
        mock_ds._run_forever = _run_forever_noop
        MockData.return_value = mock_ds
        MockTrade.return_value._run_forever = _run_forever_noop
        await ws.run()

    mock_ds.subscribe_daily_bars.assert_called_once_with(_noop_bar, "AAPL", "TSLA")


async def test_run_subscribes_minute_bars_when_handler_and_symbols_set():
    ws = _make_ws()
    ws.on_minute_bar(_noop_bar)
    ws.subscribe_minute_bars(["AAPL"])

    with patch("execution.websocket.StockDataStream") as MockData, \
         patch("execution.websocket.TradingStream") as MockTrade:
        mock_ds = MagicMock()
        mock_ds._run_forever = _run_forever_noop
        MockData.return_value = mock_ds
        MockTrade.return_value._run_forever = _run_forever_noop
        await ws.run()

    mock_ds.subscribe_bars.assert_called_once_with(_noop_bar, "AAPL")
    mock_ds.subscribe_daily_bars.assert_not_called()


async def test_run_subscribes_both_minute_and_daily_bars():
    ws = _make_ws()
    ws.on_minute_bar(_noop_bar)
    ws.subscribe_minute_bars(["AAPL"])
    ws.on_daily_bar(_noop_bar)
    ws.subscribe_daily_bars(["MSFT"])

    with patch("execution.websocket.StockDataStream") as MockData, \
         patch("execution.websocket.TradingStream") as MockTrade:
        mock_ds = MagicMock()
        mock_ds._run_forever = _run_forever_noop
        MockData.return_value = mock_ds
        MockTrade.return_value._run_forever = _run_forever_noop
        await ws.run()

    mock_ds.subscribe_bars.assert_called_once_with(_noop_bar, "AAPL")
    mock_ds.subscribe_daily_bars.assert_called_once_with(_noop_bar, "MSFT")


async def test_run_subscribes_trades_when_handler_and_tick_symbols_set():
    ws = _make_ws()
    ws.on_trade(_noop_tick)
    ws.subscribe_ticks(["TSLA", "NVDA"])

    with patch("execution.websocket.StockDataStream") as MockData, \
         patch("execution.websocket.TradingStream") as MockTrade:
        mock_ds = MagicMock()
        mock_ds._run_forever = _run_forever_noop
        MockData.return_value = mock_ds
        MockTrade.return_value._run_forever = _run_forever_noop
        await ws.run()

    mock_ds.subscribe_trades.assert_called_once_with(_noop_tick, "TSLA", "NVDA")


async def test_run_skips_trades_without_tick_handler():
    ws = _make_ws()
    ws.subscribe_ticks(["TSLA"])

    with patch("execution.websocket.StockDataStream") as MockData, \
         patch("execution.websocket.TradingStream") as MockTrade:
        mock_ds = MagicMock()
        mock_ds._run_forever = _run_forever_noop
        MockData.return_value = mock_ds
        MockTrade.return_value._run_forever = _run_forever_noop
        await ws.run()

    mock_ds.subscribe_trades.assert_not_called()


async def test_run_skips_trades_without_tick_symbols():
    ws = _make_ws()
    ws.on_trade(_noop_tick)

    with patch("execution.websocket.StockDataStream") as MockData, \
         patch("execution.websocket.TradingStream") as MockTrade:
        mock_ds = MagicMock()
        mock_ds._run_forever = _run_forever_noop
        MockData.return_value = mock_ds
        MockTrade.return_value._run_forever = _run_forever_noop
        await ws.run()

    mock_ds.subscribe_trades.assert_not_called()


async def test_run_skips_minute_bars_without_handler():
    ws = _make_ws()
    ws.subscribe_minute_bars(["AAPL"])

    with patch("execution.websocket.StockDataStream") as MockData, \
         patch("execution.websocket.TradingStream") as MockTrade:
        mock_ds = MagicMock()
        mock_ds._run_forever = _run_forever_noop
        MockData.return_value = mock_ds
        MockTrade.return_value._run_forever = _run_forever_noop
        await ws.run()

    mock_ds.subscribe_bars.assert_not_called()


async def test_run_skips_minute_bars_without_symbols():
    ws = _make_ws()
    ws.on_minute_bar(_noop_bar)

    with patch("execution.websocket.StockDataStream") as MockData, \
         patch("execution.websocket.TradingStream") as MockTrade:
        mock_ds = MagicMock()
        mock_ds._run_forever = _run_forever_noop
        MockData.return_value = mock_ds
        MockTrade.return_value._run_forever = _run_forever_noop
        await ws.run()

    mock_ds.subscribe_bars.assert_not_called()


async def test_run_skips_daily_bars_without_handler():
    ws = _make_ws()
    ws.subscribe_daily_bars(["AAPL"])

    with patch("execution.websocket.StockDataStream") as MockData, \
         patch("execution.websocket.TradingStream") as MockTrade:
        mock_ds = MagicMock()
        mock_ds._run_forever = _run_forever_noop
        MockData.return_value = mock_ds
        MockTrade.return_value._run_forever = _run_forever_noop
        await ws.run()

    mock_ds.subscribe_daily_bars.assert_not_called()


async def test_run_skips_daily_bars_without_symbols():
    ws = _make_ws()
    ws.on_daily_bar(_noop_bar)

    with patch("execution.websocket.StockDataStream") as MockData, \
         patch("execution.websocket.TradingStream") as MockTrade:
        mock_ds = MagicMock()
        mock_ds._run_forever = _run_forever_noop
        MockData.return_value = mock_ds
        MockTrade.return_value._run_forever = _run_forever_noop
        await ws.run()

    mock_ds.subscribe_daily_bars.assert_not_called()


async def test_run_subscribes_order_updates_when_handler_set():
    ws = _make_ws()
    ws.on_order_update(_noop_order)

    with patch("execution.websocket.StockDataStream") as MockData, \
         patch("execution.websocket.TradingStream") as MockTrade:
        MockData.return_value._run_forever = _run_forever_noop
        mock_ts = MagicMock()
        mock_ts._run_forever = _run_forever_noop
        MockTrade.return_value = mock_ts
        await ws.run()

    mock_ts.subscribe_trade_updates.assert_called_once_with(_noop_order)


async def test_run_skips_order_updates_without_handler():
    ws = _make_ws()

    with patch("execution.websocket.StockDataStream") as MockData, \
         patch("execution.websocket.TradingStream") as MockTrade:
        MockData.return_value._run_forever = _run_forever_noop
        mock_ts = MagicMock()
        mock_ts._run_forever = _run_forever_noop
        MockTrade.return_value = mock_ts
        await ws.run()

    mock_ts.subscribe_trade_updates.assert_not_called()


# ── close ─────────────────────────────────────────────────────────────────────

async def test_close_before_run_is_safe():
    ws = _make_ws()
    await ws.close()  # streams are None — must not raise


async def test_close_calls_stop_ws_on_both_streams():
    ws = _make_ws()
    ws._data_stream = AsyncMock()
    ws._trade_stream = AsyncMock()

    await ws.close()

    ws._data_stream.stop_ws.assert_awaited_once()
    ws._trade_stream.stop_ws.assert_awaited_once()


# ── integration ───────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_trading_stream_auth_and_close():
    """TradingStream authenticates with paper keys and shuts down cleanly."""
    ws = AlpacaWebSocket(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    ws.on_order_update(_noop_order)

    task = asyncio.create_task(ws.run())
    await asyncio.sleep(3)

    assert ws._trade_stream._running, "TradingStream should be connected after auth"

    await ws.close()
    await asyncio.wait_for(task, timeout=8)


@pytest.mark.integration
async def test_data_stream_auth_and_close():
    """StockDataStream (IEX feed) authenticates with paper keys and shuts down cleanly."""
    ws = AlpacaWebSocket(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    ws.on_daily_bar(_noop_bar)
    ws.subscribe_daily_bars(["AAPL"])

    task = asyncio.create_task(ws.run())
    await asyncio.sleep(3)

    assert ws._data_stream._running, "StockDataStream should be connected after auth"

    await ws.close()
    await asyncio.wait_for(task, timeout=8)

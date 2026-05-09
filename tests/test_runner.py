"""Tests for engine/runner.py — all dependencies are fully mocked."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from alpaca.trading.enums import TradeEvent
from data.database import Database, TradeRecord
from engine.runner import TradingRunner
from execution.alpaca_client import AlpacaClient
from execution.websocket import AlpacaWebSocket
from strategies.base import BaseStrategy, Signal


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_runner(db=None, lookback=10, bar_hook=None, tick_hook=None):
    client = MagicMock(spec=AlpacaClient)
    ws = MagicMock(spec=AlpacaWebSocket)
    ws.run = AsyncMock()
    ws.close = AsyncMock()
    return TradingRunner(client=client, ws=ws, db=db, lookback=lookback,
                         bar_hook=bar_hook, tick_hook=tick_hook)


def _make_strategy(name="strat", symbols=None, frequency="1Day"):
    s = MagicMock(spec=BaseStrategy)
    s.name = name
    s.symbols = symbols or ["AAPL"]
    s.frequency = frequency
    s.generate_signals.return_value = []
    return s


def _make_tick_strategy(name="tick_strat", symbols=None):
    s = MagicMock(spec=BaseStrategy)
    s.name = name
    s.symbols = symbols or ["TSLA"]
    s.frequency = "tick"
    s.on_tick.return_value = []
    return s


def _make_tick(symbol="TSLA", price=200.0, size=100):
    tick = MagicMock()
    tick.symbol = symbol
    tick.price = price
    tick.size = size
    tick.timestamp = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
    return tick


def _make_bar(symbol="AAPL", close=150.0, ts=None, open=149.0, high=151.0, low=148.0, volume=1_000_000):
    bar = MagicMock()
    bar.symbol = symbol
    bar.open = open
    bar.high = high
    bar.low = low
    bar.close = close
    bar.volume = volume
    bar.timestamp = ts or datetime(2024, 1, 15, tzinfo=timezone.utc)
    return bar


def _make_bars_df(n=20):
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {"open": [100.0] * n, "high": [105.0] * n,
         "low": [95.0] * n, "close": [102.0] * n, "volume": [1_000_000] * n},
        index=dates,
    )


def _make_signal(side="buy", price=None):
    return Signal(symbol="AAPL", side=side, quantity=1.0, price=price, strategy="strat")


def _make_order_update(event=TradeEvent.FILL, order_id="ord-1", filled_price=150.0, filled_qty=1.0):
    update = MagicMock()
    update.event = event
    update.order.id = order_id
    update.order.filled_avg_price = filled_price
    update.order.filled_qty = filled_qty
    return update


# ── add_strategy ──────────────────────────────────────────────────────────────

def test_add_strategy_appends():
    runner = _make_runner()
    s = _make_strategy()
    runner.add_strategy(s)
    assert runner.strategies == [s]


def test_add_multiple_strategies_preserves_order():
    runner = _make_runner()
    s1, s2 = _make_strategy("a"), _make_strategy("b")
    runner.add_strategy(s1)
    runner.add_strategy(s2)
    assert runner.strategies == [s1, s2]


# ── _on_daily_bar ─────────────────────────────────────────────────────────────

async def test_on_daily_bar_creates_bars_entry_for_symbol():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Day"))
    await runner._on_daily_bar(_make_bar())
    assert ("AAPL", "1Day") in runner._bars
    assert len(runner._bars[("AAPL", "1Day")]) == 1


async def test_on_daily_bar_appends_subsequent_bars():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Day"))
    ts1 = datetime(2024, 1, 15, tzinfo=timezone.utc)
    ts2 = datetime(2024, 1, 16, tzinfo=timezone.utc)
    await runner._on_daily_bar(_make_bar(ts=ts1))
    await runner._on_daily_bar(_make_bar(ts=ts2))
    assert len(runner._bars[("AAPL", "1Day")]) == 2


async def test_on_daily_bar_calls_generate_signals_for_1day_strategy():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["AAPL"], frequency="1Day")
    runner.add_strategy(strategy)
    await runner._on_daily_bar(_make_bar(symbol="AAPL"))
    strategy.generate_signals.assert_called_once()


async def test_on_daily_bar_skips_strategy_with_different_symbol():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["TSLA"], frequency="1Day")
    runner.add_strategy(strategy)
    await runner._on_daily_bar(_make_bar(symbol="AAPL"))
    strategy.generate_signals.assert_not_called()


async def test_on_daily_bar_submits_signals_returned_by_strategy():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["AAPL"], frequency="1Day")
    strategy.generate_signals.return_value = [_make_signal()]
    runner.add_strategy(strategy)
    runner.client.submit_order.return_value = {"id": "ord-1"}
    await runner._on_daily_bar(_make_bar(symbol="AAPL"))
    runner.client.submit_order.assert_called_once()


async def test_on_daily_bar_strategy_exception_does_not_crash():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["AAPL"], frequency="1Day")
    strategy.generate_signals.side_effect = RuntimeError("boom")
    runner.add_strategy(strategy)
    await runner._on_daily_bar(_make_bar())  # must not raise


async def test_on_daily_bar_calls_bar_hook():
    hook = MagicMock()
    runner = _make_runner(bar_hook=hook)
    bar = _make_bar()
    await runner._on_daily_bar(bar)
    hook.assert_called_once_with(bar)


async def test_on_daily_bar_skips_tick_strategy():
    runner = _make_runner()
    strategy = _make_tick_strategy(symbols=["AAPL"])
    runner.add_strategy(strategy)
    await runner._on_daily_bar(_make_bar(symbol="AAPL"))
    strategy.on_tick.assert_not_called()
    strategy.generate_signals.assert_not_called()


# ── _on_daily_bar 1Week aggregation ──────────────────────────────────────────

async def test_on_daily_bar_accumulates_weekly_buffer_mon_to_thu():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Week"))
    # 2024-01-08 Mon, 2024-01-09 Tue, 2024-01-10 Wed, 2024-01-11 Thu
    for day in range(4):
        ts = datetime(2024, 1, 8 + day, tzinfo=timezone.utc)
        await runner._on_daily_bar(_make_bar(symbol="AAPL", ts=ts))
    runner.strategies[0].generate_signals.assert_not_called()


async def test_on_daily_bar_flushes_weekly_buffer_on_friday():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["AAPL"], frequency="1Week")
    runner.add_strategy(strategy)
    # 2024-01-08 Mon → 2024-01-12 Fri
    for day in range(5):
        ts = datetime(2024, 1, 8 + day, tzinfo=timezone.utc)
        await runner._on_daily_bar(_make_bar(symbol="AAPL", ts=ts))
    strategy.generate_signals.assert_called_once()


async def test_on_daily_bar_flushes_weekly_buffer_after_5_bars():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["AAPL"], frequency="1Week")
    runner.add_strategy(strategy)
    # 5 Thursday bars → hits the >=5 safety net
    ts = datetime(2024, 1, 4, tzinfo=timezone.utc)  # Thursday
    for _ in range(5):
        await runner._on_daily_bar(_make_bar(symbol="AAPL", ts=ts))
    strategy.generate_signals.assert_called_once()


async def test_on_daily_bar_weekly_buffer_cleared_after_flush():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Week"))
    # Feed a full week (Mon–Fri)
    for day in range(5):
        ts = datetime(2024, 1, 8 + day, tzinfo=timezone.utc)
        await runner._on_daily_bar(_make_bar(symbol="AAPL", ts=ts))
    assert runner._agg_buffer.get(("AAPL", "1Week"), []) == []


# ── _on_minute_bar ────────────────────────────────────────────────────────────

async def test_on_minute_bar_dispatches_1min_immediately():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["AAPL"], frequency="1Min")
    runner.add_strategy(strategy)
    ts = datetime(2024, 1, 15, 9, 31, 0, tzinfo=timezone.utc)
    await runner._on_minute_bar(_make_bar(symbol="AAPL", ts=ts))
    strategy.generate_signals.assert_called_once()


async def test_on_minute_bar_creates_1min_bars_entry():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Min"))
    ts = datetime(2024, 1, 15, 9, 31, 0, tzinfo=timezone.utc)
    await runner._on_minute_bar(_make_bar(ts=ts))
    assert ("AAPL", "1Min") in runner._bars


async def test_on_minute_bar_aggregates_5min_on_boundary():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["AAPL"], frequency="5Min")
    runner.add_strategy(strategy)
    # minutes 30–34: boundary at minute 34 since (34+1)%5 == 0
    for minute in range(5):
        ts = datetime(2024, 1, 15, 9, 30 + minute, 0, tzinfo=timezone.utc)
        await runner._on_minute_bar(_make_bar(symbol="AAPL", ts=ts))
    strategy.generate_signals.assert_called_once()


async def test_on_minute_bar_no_dispatch_before_5min_boundary():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["AAPL"], frequency="5Min")
    runner.add_strategy(strategy)
    for minute in range(4):  # only 4 bars, boundary not reached
        ts = datetime(2024, 1, 15, 9, 30 + minute, 0, tzinfo=timezone.utc)
        await runner._on_minute_bar(_make_bar(symbol="AAPL", ts=ts))
    strategy.generate_signals.assert_not_called()


async def test_on_minute_bar_aggregates_15min_on_boundary():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["AAPL"], frequency="15Min")
    runner.add_strategy(strategy)
    # minutes 30–44: boundary at minute 44 since (44+1)%15 == 0
    for minute in range(15):
        ts = datetime(2024, 1, 15, 9, 30 + minute, 0, tzinfo=timezone.utc)
        await runner._on_minute_bar(_make_bar(symbol="AAPL", ts=ts))
    strategy.generate_signals.assert_called_once()


async def test_on_minute_bar_aggregates_30min_on_boundary():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["AAPL"], frequency="30Min")
    runner.add_strategy(strategy)
    # minute 59: (59+1)%30 == 0  (second 30-min window of the hour)
    for minute in range(30, 60):
        ts = datetime(2024, 1, 15, 9, minute, 0, tzinfo=timezone.utc)
        await runner._on_minute_bar(_make_bar(symbol="AAPL", ts=ts))
    strategy.generate_signals.assert_called_once()


async def test_on_minute_bar_aggregates_1hour_on_boundary():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["AAPL"], frequency="1Hour")
    runner.add_strategy(strategy)
    # minute 59: (59+1)%60 == 0
    for minute in range(60):
        ts = datetime(2024, 1, 15, 9, minute, 0, tzinfo=timezone.utc)
        await runner._on_minute_bar(_make_bar(symbol="AAPL", ts=ts))
    strategy.generate_signals.assert_called_once()


async def test_on_minute_bar_clears_buffer_after_aggregation():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="5Min"))
    for minute in range(5):
        ts = datetime(2024, 1, 15, 9, 30 + minute, 0, tzinfo=timezone.utc)
        await runner._on_minute_bar(_make_bar(symbol="AAPL", ts=ts))
    assert runner._agg_buffer.get(("AAPL", "5Min"), []) == []


async def test_on_minute_bar_calls_bar_hook():
    hook = MagicMock()
    runner = _make_runner(bar_hook=hook)
    bar = _make_bar(ts=datetime(2024, 1, 15, 9, 31, 0, tzinfo=timezone.utc))
    await runner._on_minute_bar(bar)
    hook.assert_called_once_with(bar)


async def test_on_minute_bar_skips_tick_strategy():
    runner = _make_runner()
    strategy = _make_tick_strategy(symbols=["AAPL"])
    runner.add_strategy(strategy)
    ts = datetime(2024, 1, 15, 9, 31, 0, tzinfo=timezone.utc)
    await runner._on_minute_bar(_make_bar(symbol="AAPL", ts=ts))
    strategy.on_tick.assert_not_called()
    strategy.generate_signals.assert_not_called()


async def test_on_minute_bar_aggregated_ohlcv_is_correct():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="5Min"))

    for i in range(5):
        b = _make_bar(
            symbol="AAPL",
            open=100.0 + i,
            high=110.0 + i,
            low=90.0 + i,
            close=105.0 + i,
            volume=1000.0 + i * 100,
            ts=datetime(2024, 1, 15, 9, 30 + i, 0, tzinfo=timezone.utc),
        )
        await runner._on_minute_bar(b)

    df = runner._bars[("AAPL", "5Min")]
    assert len(df) == 1
    assert df.iloc[0]["open"] == 100.0    # first bar's open
    assert df.iloc[0]["high"] == 114.0    # max(110,111,112,113,114)
    assert df.iloc[0]["low"] == 90.0      # min(90,91,92,93,94)
    assert df.iloc[0]["close"] == 109.0   # last bar's close
    assert df.iloc[0]["volume"] == 6000.0 # 1000+1100+1200+1300+1400


async def test_on_minute_bar_strategy_exception_does_not_crash():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["AAPL"], frequency="1Min")
    strategy.generate_signals.side_effect = RuntimeError("boom")
    runner.add_strategy(strategy)
    ts = datetime(2024, 1, 15, 9, 31, 0, tzinfo=timezone.utc)
    await runner._on_minute_bar(_make_bar(ts=ts))  # must not raise


# ── _on_tick ──────────────────────────────────────────────────────────────────

async def test_on_tick_dispatches_to_tick_strategy():
    runner = _make_runner()
    strategy = _make_tick_strategy(symbols=["TSLA"])
    runner.add_strategy(strategy)
    await runner._on_tick(_make_tick(symbol="TSLA"))
    strategy.on_tick.assert_called_once()


async def test_on_tick_skips_bar_strategy():
    runner = _make_runner()
    strategy = _make_strategy(symbols=["TSLA"], frequency="1Day")
    runner.add_strategy(strategy)
    await runner._on_tick(_make_tick(symbol="TSLA"))
    strategy.generate_signals.assert_not_called()


async def test_on_tick_skips_strategy_with_different_symbol():
    runner = _make_runner()
    strategy = _make_tick_strategy(symbols=["NVDA"])
    runner.add_strategy(strategy)
    await runner._on_tick(_make_tick(symbol="TSLA"))
    strategy.on_tick.assert_not_called()


async def test_on_tick_submits_signals_returned_by_strategy():
    runner = _make_runner()
    strategy = _make_tick_strategy(symbols=["TSLA"])
    strategy.on_tick.return_value = [
        Signal(symbol="TSLA", side="buy", quantity=1.0, price=None, strategy="tick_strat")
    ]
    runner.add_strategy(strategy)
    runner.client.submit_order.return_value = {"id": "ord-1"}
    await runner._on_tick(_make_tick(symbol="TSLA"))
    runner.client.submit_order.assert_called_once()


async def test_on_tick_calls_tick_hook():
    hook = MagicMock()
    runner = _make_runner(tick_hook=hook)
    tick = _make_tick()
    await runner._on_tick(tick)
    hook.assert_called_once_with(tick)


async def test_on_tick_strategy_exception_does_not_crash():
    runner = _make_runner()
    strategy = _make_tick_strategy(symbols=["TSLA"])
    strategy.on_tick.side_effect = RuntimeError("boom")
    runner.add_strategy(strategy)
    await runner._on_tick(_make_tick(symbol="TSLA"))  # must not raise


# ── _execute_signal ───────────────────────────────────────────────────────────

async def test_execute_signal_market_order():
    runner = _make_runner()
    runner.client.submit_order.return_value = {"id": "ord-1"}
    await runner._execute_signal(_make_signal(price=None), _make_strategy())
    runner.client.submit_order.assert_called_once_with(
        symbol="AAPL", qty=1.0, side="buy", order_type="market", limit_price=None
    )


async def test_execute_signal_limit_order():
    runner = _make_runner()
    runner.client.submit_order.return_value = {"id": "ord-2"}
    await runner._execute_signal(_make_signal(price=149.50), _make_strategy())
    runner.client.submit_order.assert_called_once_with(
        symbol="AAPL", qty=1.0, side="buy", order_type="limit", limit_price=149.50
    )


async def test_execute_signal_stores_pending():
    runner = _make_runner()
    strategy = _make_strategy()
    signal = _make_signal()
    runner.client.submit_order.return_value = {"id": "ord-99"}
    await runner._execute_signal(signal, strategy)
    assert "ord-99" in runner._pending
    assert runner._pending["ord-99"] == (signal, strategy)


async def test_execute_signal_submit_error_is_swallowed():
    runner = _make_runner()
    runner.client.submit_order.side_effect = RuntimeError("API down")
    await runner._execute_signal(_make_signal(), _make_strategy())  # must not raise
    assert runner._pending == {}


# ── _on_order_update ──────────────────────────────────────────────────────────

async def test_on_order_update_fill_calls_strategy_on_fill():
    runner = _make_runner()
    strategy = _make_strategy()
    signal = _make_signal()
    runner._pending["ord-1"] = (signal, strategy)

    await runner._on_order_update(_make_order_update(
        event=TradeEvent.FILL, order_id="ord-1", filled_price=150.0, filled_qty=1.0
    ))

    strategy.on_fill.assert_called_once_with(signal, 150.0, 1.0)


async def test_on_order_update_fill_removes_from_pending():
    runner = _make_runner()
    strategy = _make_strategy()
    runner._pending["ord-1"] = (_make_signal(), strategy)

    await runner._on_order_update(_make_order_update(event=TradeEvent.FILL, order_id="ord-1"))

    assert "ord-1" not in runner._pending


async def test_on_order_update_fill_persists_trade_to_db():
    db = MagicMock(spec=Database)
    runner = _make_runner(db=db)
    strategy = _make_strategy()
    runner._pending["ord-1"] = (_make_signal(), strategy)

    await runner._on_order_update(_make_order_update(
        event=TradeEvent.FILL, order_id="ord-1", filled_price=150.0, filled_qty=1.0
    ))

    db.insert_trade.assert_called_once()
    record: TradeRecord = db.insert_trade.call_args[0][0]
    assert record.symbol == "AAPL"
    assert record.price == 150.0
    assert record.order_id == "ord-1"


async def test_on_order_update_no_db_does_not_raise():
    runner = _make_runner(db=None)
    runner._pending["ord-1"] = (_make_signal(), _make_strategy())
    await runner._on_order_update(_make_order_update(event=TradeEvent.FILL, order_id="ord-1"))


async def test_on_order_update_non_fill_event_ignored():
    runner = _make_runner()
    strategy = _make_strategy()
    runner._pending["ord-1"] = (_make_signal(), strategy)

    await runner._on_order_update(_make_order_update(event=TradeEvent.NEW, order_id="ord-1"))

    strategy.on_fill.assert_not_called()
    assert "ord-1" in runner._pending


async def test_on_order_update_unknown_order_id_ignored():
    runner = _make_runner()
    await runner._on_order_update(_make_order_update(event=TradeEvent.FILL, order_id="unknown"))


# ── run ───────────────────────────────────────────────────────────────────────

async def test_run_seeds_historical_bars_per_symbol():
    runner = _make_runner(lookback=10)
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Day"))
    runner.client.get_historical_bars.return_value = _make_bars_df(20)

    await runner.run()

    runner.client.get_historical_bars.assert_called_once()
    assert len(runner._bars[("AAPL", "1Day")]) == 10  # tail(lookback)


async def test_run_seeds_with_correct_frequency():
    runner = _make_runner(lookback=10)
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Min"))
    runner.client.get_historical_bars.return_value = _make_bars_df(20)

    await runner.run()

    call_args = runner.client.get_historical_bars.call_args.args
    assert call_args[0] == "AAPL"
    assert call_args[1] == "1Min"


async def test_run_deduplicates_symbols_across_strategies():
    runner = _make_runner()
    runner.add_strategy(_make_strategy("s1", symbols=["AAPL"], frequency="1Day"))
    runner.add_strategy(_make_strategy("s2", symbols=["AAPL"], frequency="1Day"))
    runner.client.get_historical_bars.return_value = _make_bars_df()

    await runner.run()

    runner.client.get_historical_bars.assert_called_once()


async def test_run_seeds_different_frequencies_for_same_symbol():
    runner = _make_runner()
    runner.add_strategy(_make_strategy("s1", symbols=["AAPL"], frequency="1Day"))
    runner.add_strategy(_make_strategy("s2", symbols=["AAPL"], frequency="1Min"))
    runner.client.get_historical_bars.return_value = _make_bars_df()

    await runner.run()

    assert runner.client.get_historical_bars.call_count == 2


async def test_run_seed_failure_uses_empty_dataframe():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Day"))
    runner.client.get_historical_bars.side_effect = RuntimeError("API down")

    await runner.run()  # must not raise

    assert ("AAPL", "1Day") in runner._bars
    assert runner._bars[("AAPL", "1Day")].empty


async def test_run_registers_daily_bar_handler():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Day"))
    runner.client.get_historical_bars.return_value = _make_bars_df()

    await runner.run()

    runner.ws.on_daily_bar.assert_called_once_with(runner._on_daily_bar)


async def test_run_registers_minute_bar_handler():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Min"))
    runner.client.get_historical_bars.return_value = _make_bars_df()

    await runner.run()

    runner.ws.on_minute_bar.assert_called_once_with(runner._on_minute_bar)
    runner.ws.on_daily_bar.assert_not_called()


async def test_run_registers_order_update_handler():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Day"))
    runner.client.get_historical_bars.return_value = _make_bars_df()

    await runner.run()

    runner.ws.on_order_update.assert_called_once_with(runner._on_order_update)


async def test_run_subscribes_all_strategy_symbols():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL", "TSLA"], frequency="1Day"))
    runner.client.get_historical_bars.return_value = _make_bars_df()

    await runner.run()

    subscribed = set(runner.ws.subscribe_daily_bars.call_args[0][0])
    assert {"AAPL", "TSLA"}.issubset(subscribed)


async def test_run_subscribes_minute_bars_for_intraday_strategy():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="5Min"))
    runner.client.get_historical_bars.return_value = _make_bars_df()

    await runner.run()

    subscribed = set(runner.ws.subscribe_minute_bars.call_args[0][0])
    assert "AAPL" in subscribed


async def test_run_calls_ws_run():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Day"))
    runner.client.get_historical_bars.return_value = _make_bars_df()

    await runner.run()

    runner.ws.run.assert_awaited_once()


async def test_run_tick_only_strategy_skips_bar_seeding():
    runner = _make_runner()
    runner.add_strategy(_make_tick_strategy(symbols=["TSLA"]))

    await runner.run()

    runner.client.get_historical_bars.assert_not_called()


async def test_run_tick_only_strategy_registers_trade_handler():
    runner = _make_runner()
    runner.add_strategy(_make_tick_strategy(symbols=["TSLA"]))

    await runner.run()

    runner.ws.on_trade.assert_called_once_with(runner._on_tick)


async def test_run_tick_only_strategy_subscribes_ticks():
    runner = _make_runner()
    runner.add_strategy(_make_tick_strategy(symbols=["TSLA", "NVDA"]))

    await runner.run()

    subscribed = set(runner.ws.subscribe_ticks.call_args[0][0])
    assert {"TSLA", "NVDA"}.issubset(subscribed)


async def test_run_tick_only_strategy_skips_bar_handlers():
    runner = _make_runner()
    runner.add_strategy(_make_tick_strategy(symbols=["TSLA"]))

    await runner.run()

    runner.ws.on_daily_bar.assert_not_called()
    runner.ws.on_minute_bar.assert_not_called()
    runner.ws.subscribe_daily_bars.assert_not_called()
    runner.ws.subscribe_minute_bars.assert_not_called()


async def test_run_deduplicates_tick_symbols_across_strategies():
    runner = _make_runner()
    runner.add_strategy(_make_tick_strategy("s1", symbols=["TSLA"]))
    runner.add_strategy(_make_tick_strategy("s2", symbols=["TSLA"]))

    await runner.run()

    runner.ws.subscribe_ticks.assert_called_once()
    subscribed = runner.ws.subscribe_ticks.call_args[0][0]
    assert subscribed.count("TSLA") == 1


async def test_run_mixed_strategies_registers_both_handlers():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Day"))
    runner.add_strategy(_make_tick_strategy(symbols=["TSLA"]))
    runner.client.get_historical_bars.return_value = _make_bars_df()

    await runner.run()

    runner.ws.on_daily_bar.assert_called_once()
    runner.ws.on_trade.assert_called_once()


async def test_run_minute_and_daily_strategies_register_both_bar_handlers():
    runner = _make_runner()
    runner.add_strategy(_make_strategy(symbols=["AAPL"], frequency="1Min"))
    runner.add_strategy(_make_strategy(symbols=["MSFT"], frequency="1Day"))
    runner.client.get_historical_bars.return_value = _make_bars_df()

    await runner.run()

    runner.ws.on_minute_bar.assert_called_once()
    runner.ws.on_daily_bar.assert_called_once()


# ── stop ──────────────────────────────────────────────────────────────────────

async def test_stop_closes_websocket():
    runner = _make_runner()
    await runner.stop()
    runner.ws.close.assert_awaited_once()

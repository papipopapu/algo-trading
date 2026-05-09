"""Tests for engine/backtester.py.

Uses a mock AlpacaClient and simple stub strategies so that every assertion
targets backtester behaviour exclusively, not the strategy or the SDK.
"""

import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from engine.backtester import Backtester, BacktestResult
from strategies.base import BaseStrategy, Signal


# ── test fixtures and stubs ───────────────────────────────────────────────────

def _make_bars(opens: list, closes: list) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from parallel open/close lists."""
    n = len(opens)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    idx = pd.DatetimeIndex(
        [base + timedelta(days=i) for i in range(n)], name="timestamp"
    )
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) for o, c in zip(opens, closes)],
            "low": [min(o, c) for o, c in zip(opens, closes)],
            "close": closes,
            "volume": [100_000] * n,
        },
        index=idx,
    )


def _mock_client(bars: pd.DataFrame) -> MagicMock:
    client = MagicMock()
    client.get_historical_bars.return_value = bars
    return client


class NoSignalStrategy(BaseStrategy):
    """Never emits any signal."""
    def __init__(self):
        super().__init__("no_signal", ["AAPL"])
    def generate_signals(self, bars):
        return []


class SignalAtBar(BaseStrategy):
    """Emits a predefined signal when the strategy has seen exactly `bar_idx+1` bars."""
    def __init__(self, bar_idx: int, signal: Signal):
        super().__init__("fixed", ["AAPL"])
        self._bar_idx = bar_idx
        self._signal = signal
    def generate_signals(self, bars):
        if len(bars) == self._bar_idx + 1:
            return [self._signal]
        return []


class SignalsAtBars(BaseStrategy):
    """Emits different signals at different bar indices."""
    def __init__(self, mapping: dict[int, Signal]):
        super().__init__("multi_fixed", ["AAPL"])
        self._mapping = mapping
    def generate_signals(self, bars):
        return [self._mapping[len(bars) - 1]] if (len(bars) - 1) in self._mapping else []


def _buy(qty=1.0) -> Signal:
    return Signal("AAPL", "buy", qty, None, "test")

def _sell(qty=1.0) -> Signal:
    return Signal("AAPL", "sell", qty, None, "test")


# ── timeframe validation ──────────────────────────────────────────────────────

def test_invalid_timeframe_raises():
    bt = Backtester(_mock_client(_make_bars([100], [100])))
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        bt.run(NoSignalStrategy(), "AAPL", "1Hour", "2024-01-01", "2024-01-31")


@pytest.mark.parametrize("tf", ["1Day", "1Week", "1Month"])
def test_valid_timeframes_do_not_raise(tf):
    bars = _make_bars([100, 101], [101, 102])
    bt = Backtester(_mock_client(bars))
    result = bt.run(NoSignalStrategy(), "AAPL", tf, "2024-01-01", "2024-01-02")
    assert isinstance(result, BacktestResult)


# ── equity curve shape ────────────────────────────────────────────────────────

def test_equity_curve_same_length_as_bars():
    bars = _make_bars([100, 102, 104], [101, 103, 105])
    bt = Backtester(_mock_client(bars))
    result = bt.run(NoSignalStrategy(), "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert len(result.equity_curve) == len(bars)


def test_equity_curve_index_matches_bars_index():
    bars = _make_bars([100, 102], [101, 103])
    bt = Backtester(_mock_client(bars))
    result = bt.run(NoSignalStrategy(), "AAPL", "1Day", "2024-01-01", "2024-01-02")
    assert list(result.equity_curve.index) == list(bars.index)


# ── no signals ────────────────────────────────────────────────────────────────

def test_no_signals_preserves_capital():
    bars = _make_bars([100, 110, 120], [105, 115, 125])
    bt = Backtester(_mock_client(bars), initial_capital=10_000)
    result = bt.run(NoSignalStrategy(), "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert all(result.equity_curve == 10_000)


def test_no_signals_returns_zero_total_return():
    bars = _make_bars([100, 102], [101, 103])
    bt = Backtester(_mock_client(bars))
    result = bt.run(NoSignalStrategy(), "AAPL", "1Day", "2024-01-01", "2024-01-02")
    assert result.total_return == 0.0


def test_no_signals_empty_trades():
    bars = _make_bars([100, 102], [101, 103])
    bt = Backtester(_mock_client(bars))
    result = bt.run(NoSignalStrategy(), "AAPL", "1Day", "2024-01-01", "2024-01-02")
    assert len(result.trades) == 0


# ── buy fill mechanics ────────────────────────────────────────────────────────

def test_buy_fills_at_next_bar_open():
    # BUY signal emitted at bar 0 → filled at bar 1's open = 105
    bars = _make_bars([100, 105, 110], [102, 107, 112])
    bt = Backtester(_mock_client(bars), initial_capital=10_000)
    result = bt.run(SignalAtBar(0, _buy(qty=1)), "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert result.trades.iloc[0]["price"] == pytest.approx(105.0)


def test_buy_reduces_cash_and_increases_shares():
    # Initial capital 10 000, buy 1 share at open=105
    # equity at bar 1 close(107) = (10000 - 105) + 1*107 = 10002
    bars = _make_bars([100, 105, 110], [102, 107, 112])
    bt = Backtester(_mock_client(bars), initial_capital=10_000)
    result = bt.run(SignalAtBar(0, _buy(qty=1)), "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert result.equity_curve.iloc[1] == pytest.approx(10_000 - 105 + 107)


def test_buy_capped_by_available_cash():
    # 100 cash, share opens at 60, commission 0 → can only afford 1 share (60), not 2 (120)
    bars = _make_bars([50, 60, 70], [55, 65, 75])
    bt = Backtester(_mock_client(bars), initial_capital=100)
    result = bt.run(SignalAtBar(0, _buy(qty=2)), "AAPL", "1Day", "2024-01-01", "2024-01-03")
    filled_qty = result.trades.iloc[0]["qty"]
    assert filled_qty == pytest.approx(100 / 60)  # all cash deployed


def test_buy_with_no_cash_generates_no_trade():
    bars = _make_bars([100, 200, 300], [150, 250, 350])
    bt = Backtester(_mock_client(bars), initial_capital=0)
    result = bt.run(SignalAtBar(0, _buy(qty=1)), "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert len(result.trades) == 0


# ── sell fill mechanics ───────────────────────────────────────────────────────

def test_sell_without_position_generates_no_trade():
    bars = _make_bars([100, 105, 110], [102, 107, 112])
    bt = Backtester(_mock_client(bars), initial_capital=10_000)
    result = bt.run(SignalAtBar(0, _sell(qty=1)), "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert len(result.trades) == 0


def test_sell_fills_at_next_bar_open():
    # Buy at bar 0 (fills at bar 1 open=105), sell at bar 1 (fills at bar 2 open=110)
    bars = _make_bars([100, 105, 110], [102, 107, 112])
    bt = Backtester(_mock_client(bars), initial_capital=10_000)
    strategy = SignalsAtBars({0: _buy(qty=1), 1: _sell(qty=1)})
    result = bt.run(strategy, "AAPL", "1Day", "2024-01-01", "2024-01-03")
    sell_trade = result.trades[result.trades["side"] == "sell"].iloc[0]
    assert sell_trade["price"] == pytest.approx(110.0)


def test_buy_then_sell_round_trip_pnl():
    # Buy 1 share at 105, sell at 110 → profit = 5
    bars = _make_bars([100, 105, 110], [102, 107, 112])
    bt = Backtester(_mock_client(bars), initial_capital=10_000)
    strategy = SignalsAtBars({0: _buy(qty=1), 1: _sell(qty=1)})
    result = bt.run(strategy, "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert result.equity_curve.iloc[-1] == pytest.approx(10_000 + 5)


def test_sell_capped_by_owned_shares():
    # Own only 1 share but signal says sell 5 → only 1 sold
    bars = _make_bars([100, 105, 110], [102, 107, 112])
    bt = Backtester(_mock_client(bars), initial_capital=10_000)
    strategy = SignalsAtBars({0: _buy(qty=1), 1: _sell(qty=5)})
    result = bt.run(strategy, "AAPL", "1Day", "2024-01-01", "2024-01-03")
    sell_trade = result.trades[result.trades["side"] == "sell"].iloc[0]
    assert sell_trade["qty"] == pytest.approx(1.0)


# ── commission ────────────────────────────────────────────────────────────────

def test_commission_deducted_on_buy():
    # Buy 1 share at open=105, commission=5 → cash = 10000 - 105 - 5 = 9890
    # equity at bar 1 close=107: 9890 + 107 = 9997
    bars = _make_bars([100, 105, 110], [102, 107, 112])
    bt = Backtester(_mock_client(bars), initial_capital=10_000, commission=5.0)
    result = bt.run(SignalAtBar(0, _buy(qty=1)), "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert result.equity_curve.iloc[1] == pytest.approx(10_000 - 105 - 5 + 107)


def test_commission_deducted_on_sell():
    # Buy at 105 (comm=5), sell at 110 (comm=5) → net PnL = 5 - 5 - 5 = -5
    bars = _make_bars([100, 105, 110], [102, 107, 112])
    bt = Backtester(_mock_client(bars), initial_capital=10_000, commission=5.0)
    strategy = SignalsAtBars({0: _buy(qty=1), 1: _sell(qty=1)})
    result = bt.run(strategy, "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert result.equity_curve.iloc[-1] == pytest.approx(10_000 - 5)


# ── trades DataFrame ──────────────────────────────────────────────────────────

def test_trades_dataframe_columns():
    bars = _make_bars([100, 105], [102, 107])
    bt = Backtester(_mock_client(bars), initial_capital=10_000)
    result = bt.run(SignalAtBar(0, _buy(qty=1)), "AAPL", "1Day", "2024-01-01", "2024-01-02")
    assert set(result.trades.columns) >= {"timestamp", "symbol", "side", "qty", "price"}


def test_trades_count_for_buy_and_sell():
    bars = _make_bars([100, 105, 110], [102, 107, 112])
    bt = Backtester(_mock_client(bars), initial_capital=10_000)
    strategy = SignalsAtBars({0: _buy(qty=1), 1: _sell(qty=1)})
    result = bt.run(strategy, "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert len(result.trades) == 2


def test_last_bar_signal_is_not_filled():
    # Signal emitted at the final bar has no next bar → should not appear in trades
    bars = _make_bars([100, 105], [102, 107])
    bt = Backtester(_mock_client(bars), initial_capital=10_000)
    result = bt.run(SignalAtBar(1, _buy(qty=1)), "AAPL", "1Day", "2024-01-01", "2024-01-02")
    assert len(result.trades) == 0


# ── metrics ───────────────────────────────────────────────────────────────────

def test_total_return_positive_after_profitable_round_trip():
    bars = _make_bars([100, 100, 200], [100, 100, 200])
    bt = Backtester(_mock_client(bars), initial_capital=1_000)
    # Buy 1 share at 100, sell at 200 → profit 100 on 1000 capital = +10%
    strategy = SignalsAtBars({0: _buy(qty=1), 1: _sell(qty=1)})
    result = bt.run(strategy, "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert result.total_return == pytest.approx(100 / 1_000)


def test_total_return_zero_with_no_trades():
    bars = _make_bars([100, 110, 120], [100, 110, 120])
    bt = Backtester(_mock_client(bars))
    result = bt.run(NoSignalStrategy(), "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert result.total_return == pytest.approx(0.0)


def test_max_drawdown_is_non_positive():
    bars = _make_bars([100, 100, 200], [100, 100, 200])
    bt = Backtester(_mock_client(bars), initial_capital=1_000)
    strategy = SignalsAtBars({0: _buy(qty=1), 1: _sell(qty=1)})
    result = bt.run(strategy, "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert result.max_drawdown <= 0


def test_max_drawdown_zero_when_equity_only_rises():
    # Equity never falls below its running peak → drawdown = 0
    bars = _make_bars([100, 100, 100], [100, 110, 120])
    bt = Backtester(_mock_client(bars), initial_capital=1_000)
    strategy = SignalsAtBars({0: _buy(qty=1)})
    result = bt.run(strategy, "AAPL", "1Day", "2024-01-01", "2024-01-03")
    assert result.max_drawdown == pytest.approx(0.0, abs=1e-9)


def test_result_is_backtest_result_instance():
    bars = _make_bars([100], [101])
    bt = Backtester(_mock_client(bars))
    result = bt.run(NoSignalStrategy(), "AAPL", "1Day", "2024-01-01", "2024-01-01")
    assert isinstance(result, BacktestResult)

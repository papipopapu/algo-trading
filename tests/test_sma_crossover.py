"""Tests for strategies/sma_crossover.py.

Test prices are chosen so that the resulting SMAs are easy to verify by hand.
All tests use short_window=3, long_window=5 unless stated otherwise.

Golden-cross dataset  (prices = [10, 9, 8, 7, 6, 7, 9, 12]):
  idx 6: sma3 = (6+7+9)/3  = 7.33   sma5 = (8+7+6+7+9)/5  = 7.40  → sma3 < sma5
  idx 7: sma3 = (7+9+12)/3 = 9.33   sma5 = (7+6+7+9+12)/5 = 8.20  → sma3 > sma5 ← BUY

Death-cross dataset  (prices = [6, 7, 9, 12, 10, 9, 7]):
  idx 5: sma3 = (12+10+9)/3 = 10.33  sma5 = (7+9+12+10+9)/5 = 9.40  → sma3 > sma5
  idx 6: sma3 = (10+9+7)/3  =  8.67  sma5 = (9+12+10+9+7)/5 = 9.40  → sma3 < sma5 ← SELL
"""

import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta

from strategies.sma_crossover import SMACrossover


# ── helpers ───────────────────────────────────────────────────────────────────

def _bars(prices: list[float]) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a list of close prices."""
    n = len(prices)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    idx = pd.DatetimeIndex([base + timedelta(days=i) for i in range(n)], name="timestamp")
    return pd.DataFrame(
        {"open": prices, "high": prices, "low": prices, "close": prices, "volume": [1_000] * n},
        index=idx,
    )


def _strategy(**kwargs) -> SMACrossover:
    defaults = {"symbols": ["AAPL"], "short_window": 3, "long_window": 5, "qty": 10.0}
    defaults.update(kwargs)
    return SMACrossover(**defaults)


GOLDEN_CROSS_PRICES = [10, 9, 8, 7, 6, 7, 9, 12]
DEATH_CROSS_PRICES  = [6, 7, 9, 12, 10, 9, 7]
FLAT_PRICES         = [100.0] * 7


# ── constructor ───────────────────────────────────────────────────────────────

def test_short_window_must_be_less_than_long_window():
    with pytest.raises(ValueError, match="short_window"):
        SMACrossover(["AAPL"], short_window=10, long_window=10)


def test_short_window_greater_than_long_raises():
    with pytest.raises(ValueError):
        SMACrossover(["AAPL"], short_window=20, long_window=5)


# ── not enough data ───────────────────────────────────────────────────────────

def test_returns_empty_when_bars_exactly_equal_long_window():
    # long_window=5, so need at least 6 bars; 5 bars → []
    s = _strategy()
    assert s.generate_signals(_bars([1, 2, 3, 4, 5])) == []


def test_returns_empty_when_bars_below_long_window():
    s = _strategy()
    assert s.generate_signals(_bars([1, 2, 3])) == []


def test_returns_empty_on_single_bar():
    s = _strategy()
    assert s.generate_signals(_bars([100])) == []


# ── no crossover ──────────────────────────────────────────────────────────────

def test_no_signal_on_flat_prices():
    s = _strategy()
    # SMAs are identical throughout; prev_diff = curr_diff = 0 → no condition met
    assert s.generate_signals(_bars(FLAT_PRICES)) == []


def test_no_signal_when_short_stays_below_long():
    # Steadily falling: sma3 remains below sma5, no crossover
    prices = [10, 9, 8, 7, 6, 5, 4]
    s = _strategy()
    assert s.generate_signals(_bars(prices)) == []


def test_no_signal_when_short_stays_above_long():
    # Steadily rising: sma3 above sma5 from the start, no crossover event
    prices = [4, 5, 6, 7, 8, 9, 10]
    s = _strategy()
    assert s.generate_signals(_bars(prices)) == []


# ── golden cross → BUY ───────────────────────────────────────────────────────

def test_golden_cross_generates_buy_signal():
    s = _strategy()
    signals = s.generate_signals(_bars(GOLDEN_CROSS_PRICES))
    assert len(signals) == 1
    assert signals[0].side == "buy"


def test_golden_cross_signal_symbol():
    s = _strategy(symbols=["TSLA"])
    signals = s.generate_signals(_bars(GOLDEN_CROSS_PRICES))
    assert signals[0].symbol == "TSLA"


def test_golden_cross_signal_quantity():
    s = _strategy(qty=7.0)
    signals = s.generate_signals(_bars(GOLDEN_CROSS_PRICES))
    assert signals[0].quantity == 7.0


def test_golden_cross_signal_is_market_order():
    s = _strategy()
    signals = s.generate_signals(_bars(GOLDEN_CROSS_PRICES))
    assert signals[0].price is None


def test_golden_cross_signal_strategy_name():
    s = _strategy()
    signals = s.generate_signals(_bars(GOLDEN_CROSS_PRICES))
    assert signals[0].strategy == "sma_crossover"


def test_no_signal_one_bar_before_golden_cross():
    # Penultimate state: sma3 still below sma5 → no signal yet
    s = _strategy()
    assert s.generate_signals(_bars(GOLDEN_CROSS_PRICES[:-1])) == []


# ── death cross → SELL ────────────────────────────────────────────────────────

def test_death_cross_generates_sell_signal():
    s = _strategy()
    signals = s.generate_signals(_bars(DEATH_CROSS_PRICES))
    assert len(signals) == 1
    assert signals[0].side == "sell"


def test_death_cross_signal_symbol():
    s = _strategy(symbols=["MSFT"])
    signals = s.generate_signals(_bars(DEATH_CROSS_PRICES))
    assert signals[0].symbol == "MSFT"


def test_death_cross_signal_is_market_order():
    s = _strategy()
    signals = s.generate_signals(_bars(DEATH_CROSS_PRICES))
    assert signals[0].price is None


def test_no_signal_one_bar_before_death_cross():
    s = _strategy()
    assert s.generate_signals(_bars(DEATH_CROSS_PRICES[:-1])) == []


# ── at most one signal per call ───────────────────────────────────────────────

def test_at_most_one_signal_per_call():
    s = _strategy()
    for prices in [GOLDEN_CROSS_PRICES, DEATH_CROSS_PRICES, FLAT_PRICES]:
        signals = s.generate_signals(_bars(prices))
        assert len(signals) <= 1

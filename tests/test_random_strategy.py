"""Tests for strategies/random_strategy.py."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pandas as pd
import pytest

from strategies.random_strategy import RandomStrategy
from strategies.base import Signal


def _make_tick(symbol="TSLA", price=200.0, size=100, ts=None):
    tick = MagicMock()
    tick.symbol = symbol
    tick.price = price
    tick.size = size
    tick.timestamp = ts or datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
    return tick


def _make_strategy(symbols=None, qty=1.0, max_position=3,
                   min_interval=1.0, max_interval=30.0, seed=42):
    return RandomStrategy(
        symbols=symbols or ["TSLA", "NVDA"],
        qty=qty,
        max_position=max_position,
        min_interval=min_interval,
        max_interval=max_interval,
        seed=seed,
    )


# ── frequency / generate_signals ─────────────────────────────────────────────

def test_frequency_is_tick():
    s = _make_strategy()
    assert s.frequency == "tick"


def test_generate_signals_returns_empty_list():
    s = _make_strategy()
    assert s.generate_signals(pd.DataFrame()) == []


# ── symbol filtering ──────────────────────────────────────────────────────────

def test_on_tick_ignores_unknown_symbol():
    s = _make_strategy(symbols=["TSLA"])
    result = s.on_tick(_make_tick(symbol="AAPL"))
    assert result == []


# ── first tick always buys (position starts at 0) ────────────────────────────

def test_first_tick_always_buys():
    s = _make_strategy(symbols=["TSLA"], seed=0)
    signals = s.on_tick(_make_tick(symbol="TSLA"))
    assert len(signals) == 1
    assert signals[0].side == "buy"


def test_first_tick_signal_has_correct_fields():
    s = _make_strategy(symbols=["TSLA"])
    signals = s.on_tick(_make_tick(symbol="TSLA", price=220.5))
    assert signals[0].symbol == "TSLA"
    assert signals[0].quantity == 1.0
    assert signals[0].price is None   # market order
    assert signals[0].strategy == "random"


# ── throttle: second tick within interval is ignored ─────────────────────────

def test_throttle_blocks_second_tick_within_interval():
    # 60-second interval, second call happens in <1ms wall-clock time → always blocked.
    s = _make_strategy(symbols=["TSLA"], min_interval=60.0, max_interval=60.0)
    s.on_tick(_make_tick(symbol="TSLA"))
    result = s.on_tick(_make_tick(symbol="TSLA"))
    assert result == []


def test_throttle_allows_tick_after_interval():
    # Simulate the interval having already expired by backdating _last_action.
    s = _make_strategy(symbols=["TSLA"], min_interval=10.0, max_interval=10.0)
    s._last_action["TSLA"] = datetime.now(timezone.utc) - timedelta(seconds=11)
    s._next_interval["TSLA"] = 10.0
    result = s.on_tick(_make_tick(symbol="TSLA"))
    assert len(result) == 1


# ── position floor: never goes below 0 (no shorts) ───────────────────────────

def test_at_zero_position_always_buys():
    s = _make_strategy(symbols=["TSLA"], min_interval=0.0, max_interval=0.0, seed=99)
    s._positions["TSLA"] = 0.0
    t0 = datetime(2024, 1, 15, tzinfo=timezone.utc)

    # Drain any cached last_action to allow immediate action
    s._last_action["TSLA"] = None

    signals = s.on_tick(_make_tick(symbol="TSLA", ts=t0))
    assert signals[0].side == "buy"


def test_at_max_position_always_sells():
    s = _make_strategy(symbols=["TSLA"], max_position=3,
                       min_interval=0.0, max_interval=0.0, seed=99)
    s._positions["TSLA"] = 3.0
    s._last_action["TSLA"] = None

    t0 = datetime(2024, 1, 15, tzinfo=timezone.utc)
    signals = s.on_tick(_make_tick(symbol="TSLA", ts=t0))
    assert signals[0].side == "sell"


# ── position tracking ─────────────────────────────────────────────────────────

def test_position_increments_on_buy():
    s = _make_strategy(symbols=["TSLA"], min_interval=0.0, max_interval=0.0)
    s._last_action["TSLA"] = None
    s._positions["TSLA"] = 0.0

    s.on_tick(_make_tick(symbol="TSLA"))
    assert s._positions["TSLA"] == 1.0


def test_position_decrements_on_sell():
    s = _make_strategy(symbols=["TSLA"], max_position=3,
                       min_interval=0.0, max_interval=0.0)
    s._positions["TSLA"] = 3.0
    s._last_action["TSLA"] = None

    s.on_tick(_make_tick(symbol="TSLA"))
    assert s._positions["TSLA"] == 2.0


def test_position_never_exceeds_max():
    s = _make_strategy(symbols=["TSLA"], max_position=3, qty=2.0,
                       min_interval=0.0, max_interval=0.0)
    s._positions["TSLA"] = 2.0
    s._last_action["TSLA"] = None

    s.on_tick(_make_tick(symbol="TSLA"))
    assert s._positions["TSLA"] <= 3.0


def test_position_never_goes_below_zero():
    s = _make_strategy(symbols=["TSLA"], qty=2.0,
                       min_interval=0.0, max_interval=0.0)
    s._positions["TSLA"] = 1.0
    s._last_action["TSLA"] = None

    # Force sell path: set position to max so it will sell
    s._positions["TSLA"] = 3.0
    s._last_action["TSLA"] = None
    s.on_tick(_make_tick(symbol="TSLA"))
    assert s._positions["TSLA"] >= 0.0


# ── multi-symbol independence ─────────────────────────────────────────────────

def test_throttle_is_per_symbol():
    s = _make_strategy(symbols=["TSLA", "NVDA"], min_interval=60.0, max_interval=60.0)
    t0 = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)

    # TSLA fires at t0
    s.on_tick(_make_tick(symbol="TSLA", ts=t0))
    # NVDA should still be allowed since it has never fired
    result = s.on_tick(_make_tick(symbol="NVDA", ts=t0))
    assert len(result) == 1


def test_position_tracked_independently_per_symbol():
    s = _make_strategy(symbols=["TSLA", "NVDA"], min_interval=0.0, max_interval=0.0)
    s._positions["TSLA"] = 3.0   # maxed
    s._positions["NVDA"] = 0.0   # empty
    s._last_action["TSLA"] = None
    s._last_action["NVDA"] = None

    t0 = datetime(2024, 1, 15, tzinfo=timezone.utc)
    tsla_signals = s.on_tick(_make_tick(symbol="TSLA", ts=t0))
    nvda_signals = s.on_tick(_make_tick(symbol="NVDA", ts=t0))

    assert tsla_signals[0].side == "sell"
    assert nvda_signals[0].side == "buy"


# ── reproducibility with seed ─────────────────────────────────────────────────

def test_seeded_strategy_is_deterministic():
    results_a = []
    results_b = []
    t0 = datetime(2024, 1, 15, tzinfo=timezone.utc)

    for seed_run, results in ((42, results_a), (42, results_b)):
        s = _make_strategy(symbols=["TSLA"], min_interval=0.0, max_interval=0.0,
                           max_position=10, seed=seed_run)
        s._last_action["TSLA"] = None
        for i in range(10):
            t = t0 + timedelta(seconds=i)
            sig = s.on_tick(_make_tick(symbol="TSLA", ts=t))
            results.append(sig[0].side if sig else "throttled")

    assert results_a == results_b


# ── on_fill is a no-op ────────────────────────────────────────────────────────

def test_on_fill_does_not_raise():
    s = _make_strategy()
    signal = Signal(symbol="TSLA", side="buy", quantity=1.0, price=None, strategy="random")
    s.on_fill(signal, 200.0, 1.0)  # must not raise

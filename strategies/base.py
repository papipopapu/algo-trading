"""Abstract base class that all trading strategies must implement."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass
class Signal:
    """Represents a trading signal produced by a strategy."""

    symbol: str
    side: str       # 'buy' or 'sell'
    quantity: float
    price: Optional[float]   # None → market order
    strategy: str


FREQUENCIES = frozenset({
    "tick",
    "1Min", "5Min", "15Min", "30Min", "1Hour",
    "1Day", "1Week",
})


class BaseStrategy(ABC):
    """Abstract base for all trading strategies.

    Set the `frequency` class attribute to control the data cadence:
      - "tick"  → on_tick() is called on every real-time trade tick.
      - "1Min", "5Min", "15Min", "30Min", "1Hour", "1Day", "1Week"
                → generate_signals() is called with an OHLCV DataFrame
                  at the declared bar frequency.

    Attributes:
        frequency: Data frequency this strategy operates on.
        name: Human-readable strategy identifier.
        symbols: List of tickers this strategy trades.
    """

    frequency: str = "1Day"

    def __init__(self, name: str, symbols: list[str]) -> None:
        if self.frequency not in FREQUENCIES:
            raise ValueError(
                f"Invalid frequency {self.frequency!r}. "
                f"Must be one of {sorted(FREQUENCIES)}"
            )
        self.name = name
        self.symbols = symbols

    @abstractmethod
    def generate_signals(self, bars: pd.DataFrame) -> list[Signal]:
        """Analyze OHLCV bars and return trading signals.

        Tick-based strategies implement this as `return []`.
        """
        ...

    def on_tick(self, tick) -> list[Signal]:
        """Called on every real-time trade tick.

        Override for tick-based strategies; default is a no-op.
        `tick` is an alpaca-py `Trade` object with .symbol, .price,
        .size, .timestamp attributes.
        """
        return []

    def on_fill(self, signal: Signal, filled_price: float, filled_qty: float) -> None:
        """Called by the engine when an order from this strategy is filled."""
        ...

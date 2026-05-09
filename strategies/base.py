"""Abstract base class that all trading strategies must implement."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass
class Signal:
    """Represents a trading signal produced by a strategy.

    Attributes:
        symbol: Ticker symbol (e.g. 'AAPL').
        side: 'buy' or 'sell'.
        quantity: Number of shares/units.
        price: Limit price, or None for market orders.
        strategy: Name of the strategy that emitted the signal.
    """

    symbol: str
    side: str
    quantity: float
    price: Optional[float]
    strategy: str


class BaseStrategy(ABC):
    """Abstract base for all trading strategies.

    Subclasses must implement `generate_signals`, which receives a DataFrame
    of OHLCV bars and returns a list of Signal objects.

    Attributes:
        name: Human-readable strategy identifier.
        symbols: List of tickers this strategy trades.
    """

    def __init__(self, name: str, symbols: list[str]) -> None:
        """Initialize the strategy.

        Args:
            name: Unique strategy name.
            symbols: Tickers to watch.
        """
        self.name = name
        self.symbols = symbols

    @abstractmethod
    def generate_signals(self, bars: pd.DataFrame) -> list[Signal]:
        """Analyze bars and return trading signals.

        Args:
            bars: OHLCV DataFrame indexed by timestamp.

        Returns:
            List of Signal objects (may be empty).
        """
        ...

    def on_fill(self, signal: Signal, filled_price: float, filled_qty: float) -> None:
        """Called by the engine when an order based on this strategy's signal is filled.

        Args:
            signal: The original signal that triggered the order.
            filled_price: Actual execution price.
            filled_qty: Actual filled quantity.
        """
        ...

"""SMA crossover strategy: buy on golden cross, sell on death cross."""

import pandas as pd

from strategies.base import BaseStrategy, Signal


class SMACrossover(BaseStrategy):
    """Generates signals when a short-period SMA crosses a long-period SMA.

    Operates on daily bars by default (frequency = "1Day"). Pass a different
    frequency (e.g. "1Hour") to trade on intraday bars.

    - Golden cross (short crosses above long) → BUY signal.
    - Death  cross (short crosses below long) → SELL signal.

    Designed for a single symbol; uses self.symbols[0] in every emitted signal.

    Attributes:
        frequency: Bar frequency (default "1Day").
        short_window: Lookback period for the fast SMA.
        long_window: Lookback period for the slow SMA.
        qty: Fixed number of shares per signal.
    """

    frequency: str = "1Day"

    def __init__(
        self,
        symbols: list[str],
        short_window: int = 20,
        long_window: int = 50,
        qty: float = 1.0,
        frequency: str = "1Day",
    ) -> None:
        if short_window >= long_window:
            raise ValueError("short_window must be strictly less than long_window.")
        self.frequency = frequency  # instance attribute shadows class default
        super().__init__("sma_crossover", symbols)
        self.short_window = short_window
        self.long_window = long_window
        self.qty = qty

    def generate_signals(self, bars: pd.DataFrame) -> list[Signal]:
        """Return a BUY or SELL signal if a crossover occurred at the last bar.

        Requires at least long_window + 1 bars to compare two consecutive SMA
        values. Returns an empty list whenever there is insufficient data or no
        crossover.

        Args:
            bars: OHLCV DataFrame indexed by timestamp, covering history up to
                  and including the current bar (no lookahead).

        Returns:
            List with at most one Signal.
        """
        if len(bars) < self.long_window + 1:
            return []

        close = bars["close"]
        sma_short = close.rolling(self.short_window).mean()
        sma_long = close.rolling(self.long_window).mean()

        prev_diff = sma_short.iloc[-2] - sma_long.iloc[-2]
        curr_diff = sma_short.iloc[-1] - sma_long.iloc[-1]

        if pd.isna(prev_diff) or pd.isna(curr_diff):
            return []

        symbol = self.symbols[0]

        if prev_diff <= 0 and curr_diff > 0:
            return [Signal(symbol=symbol, side="buy", quantity=self.qty, price=None, strategy=self.name)]

        if prev_diff >= 0 and curr_diff < 0:
            return [Signal(symbol=symbol, side="sell", quantity=self.qty, price=None, strategy=self.name)]

        return []

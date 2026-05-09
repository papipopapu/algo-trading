"""Random tick-based strategy for testing the live pipeline."""

import random
from datetime import datetime, timezone

import pandas as pd

from strategies.base import BaseStrategy, Signal


class RandomStrategy(BaseStrategy):
    """Trades randomly on real-time ticks, staying within simple safety bounds.

    Decision logic per tick:
      - Throttles to one decision per X seconds, X ~ Uniform(min_interval, max_interval).
      - Never shorts: position floor is 0.
      - Caps position at max_position shares per symbol.
      - When position == 0 always buys; when position == max_position always sells;
        otherwise picks randomly.

    Because it is tick-based, `generate_signals` is unused and returns [].
    """

    frequency = "tick"

    def __init__(
        self,
        symbols: list[str],
        qty: float = 1.0,
        max_position: int = 3,
        min_interval: float = 1.0,
        max_interval: float = 30.0,
        seed: int | None = None,
    ) -> None:
        super().__init__("random", symbols)
        self.qty = qty
        self.max_position = max_position
        self.min_interval = min_interval
        self.max_interval = max_interval
        self._rng = random.Random(seed)
        # Internal position tracker (optimistic, updated on signal emit)
        self._positions: dict[str, float] = {s: 0.0 for s in symbols}
        self._last_action: dict[str, datetime | None] = {s: None for s in symbols}
        self._next_interval: dict[str, float] = {
            s: self._rng.uniform(min_interval, max_interval) for s in symbols
        }

    def generate_signals(self, bars: pd.DataFrame) -> list[Signal]:
        return []

    def on_tick(self, tick) -> list[Signal]:
        symbol = tick.symbol
        if symbol not in self.symbols:
            return []

        now = datetime.now(timezone.utc)
        last = self._last_action[symbol]

        if last is not None:
            if (now - last).total_seconds() < self._next_interval[symbol]:
                return []

        position = self._positions[symbol]

        if position <= 0:
            side = "buy"
        elif position >= self.max_position:
            side = "sell"
        else:
            side = self._rng.choice(["buy", "sell"])

        # Update state before returning so the next tick sees the new position
        self._last_action[symbol] = now
        self._next_interval[symbol] = self._rng.uniform(self.min_interval, self.max_interval)
        if side == "buy":
            self._positions[symbol] = min(self._positions[symbol] + self.qty, self.max_position)
        else:
            self._positions[symbol] = max(0.0, self._positions[symbol] - self.qty)

        return [Signal(
            symbol=symbol,
            side=side,
            quantity=self.qty,
            price=None,
            strategy=self.name,
        )]

    def on_fill(self, signal: Signal, filled_price: float, filled_qty: float) -> None:
        # Position already updated optimistically in on_tick; no correction needed.
        pass

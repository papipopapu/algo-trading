"""Event-driven backtester for daily and higher timeframes using Alpaca historical data."""

from dataclasses import dataclass, field
from typing import Optional
import math

import pandas as pd

from strategies.base import BaseStrategy, Signal
from execution.alpaca_client import AlpacaClient

_ANNUALISATION = {
    "1Day": math.sqrt(252),
    "1Week": math.sqrt(52),
    "1Month": math.sqrt(12),
}


@dataclass
class BacktestResult:
    """Aggregated output of a completed backtest run.

    Attributes:
        equity_curve: Portfolio value at each bar's close, indexed by timestamp.
        trades: One row per filled trade (timestamp, symbol, side, qty, price).
        total_return: Fractional return over the period, e.g. 0.15 = +15 %.
        sharpe_ratio: Annualised Sharpe ratio computed from bar-frequency returns.
        max_drawdown: Maximum peak-to-trough drawdown as a negative fraction.
    """

    equity_curve: pd.Series = field(default_factory=pd.Series)
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0


class Backtester:
    """Event-driven backtester restricted to daily or higher timeframes.

    Execution model
    ---------------
    At each bar i the strategy sees bars[0..i] and may emit signals. Those
    signals are filled at the *open* of bar i+1 (the next bar). Signals
    generated on the final bar are never filled. Positions are long-only; fills
    are capped by available cash (buys) or current share count (sells).

    Attributes:
        client: AlpacaClient used to fetch historical bars.
        initial_capital: Starting cash balance for the simulation.
        commission: Flat dollar commission deducted per fill.
    """

    SUPPORTED_TIMEFRAMES = {"1Day", "1Week", "1Month"}

    def __init__(
        self,
        client: AlpacaClient,
        initial_capital: float = 100_000.0,
        commission: float = 0.0,
    ) -> None:
        self.client = client
        self.initial_capital = initial_capital
        self.commission = commission

    # ── public ────────────────────────────────────────────────────────────────

    def run(
        self,
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
    ) -> BacktestResult:
        """Execute a backtest for a single strategy and symbol.

        Args:
            strategy: Strategy instance to evaluate.
            symbol: Ticker to backtest.
            timeframe: Bar size; must be one of SUPPORTED_TIMEFRAMES.
            start: ISO-8601 start date string.
            end: ISO-8601 end date string.

        Returns:
            BacktestResult with equity curve, filled-trades log, and metrics.

        Raises:
            ValueError: If timeframe is not in SUPPORTED_TIMEFRAMES.
        """
        if timeframe not in self.SUPPORTED_TIMEFRAMES:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}'. "
                f"Allowed: {sorted(self.SUPPORTED_TIMEFRAMES)}"
            )

        bars = self.client.get_historical_bars(symbol, timeframe, start, end)

        cash = self.initial_capital
        shares = 0.0
        equity_points: list[tuple] = []
        trade_rows: list[dict] = []
        pending: list[Signal] = []

        for i in range(len(bars)):
            bar = bars.iloc[i]
            ts = bars.index[i]

            # Fill signals queued by the previous bar
            for signal in pending:
                fill = self._simulate_fill(signal, bar)
                if fill is None:
                    continue
                if signal.side == "buy":
                    max_qty = max(0.0, (cash - self.commission) / fill["price"])
                    fill_qty = min(fill["qty"], max_qty)
                    if fill_qty > 0:
                        cash -= fill_qty * fill["price"] + self.commission
                        shares += fill_qty
                        trade_rows.append(_trade_row(ts, symbol, "buy", fill_qty, fill["price"]))
                        strategy.on_fill(signal, fill["price"], fill_qty)
                elif signal.side == "sell":
                    fill_qty = min(fill["qty"], shares)
                    if fill_qty > 0:
                        cash += fill_qty * fill["price"] - self.commission
                        shares -= fill_qty
                        trade_rows.append(_trade_row(ts, symbol, "sell", fill_qty, fill["price"]))
                        strategy.on_fill(signal, fill["price"], fill_qty)
            pending = []

            # Mark-to-market at close
            equity_points.append((ts, cash + shares * bar["close"]))

            # Strategy sees history up to and including bar i
            pending = strategy.generate_signals(bars.iloc[: i + 1])

        equity_curve = pd.Series(
            [e for _, e in equity_points],
            index=pd.DatetimeIndex([ts for ts, _ in equity_points], name="timestamp"),
        )
        trades_df = pd.DataFrame(trade_rows) if trade_rows else pd.DataFrame(
            columns=["timestamp", "symbol", "side", "qty", "price"]
        )
        metrics = self._compute_metrics(equity_curve, timeframe)

        return BacktestResult(equity_curve=equity_curve, trades=trades_df, **metrics)

    # ── private ───────────────────────────────────────────────────────────────

    def _simulate_fill(self, signal: Signal, next_bar: pd.Series) -> Optional[dict]:
        """Simulate a market fill at the open of the bar following the signal.

        Limit-price logic is intentionally omitted for this POC; all signals
        are treated as market orders and filled at next bar's open.

        Args:
            signal: Signal emitted by the strategy.
            next_bar: The OHLCV bar immediately after the signal bar.

        Returns:
            Dict with 'qty' and 'price', or None when fill is impossible.
        """
        price = next_bar["open"]
        if price <= 0 or signal.quantity <= 0:
            return None
        return {"qty": signal.quantity, "price": price}

    def _compute_metrics(self, equity_curve: pd.Series, timeframe: str = "1Day") -> dict:
        """Derive return, Sharpe, and max-drawdown from the equity curve.

        Args:
            equity_curve: Portfolio value at each bar.
            timeframe: Used to select the correct annualisation factor.

        Returns:
            Dict with keys total_return, sharpe_ratio, max_drawdown.
        """
        if len(equity_curve) < 2:
            return {"total_return": 0.0, "sharpe_ratio": 0.0, "max_drawdown": 0.0}

        if self.initial_capital == 0:
            total_return = 0.0
        else:
            total_return = float(
                (equity_curve.iloc[-1] - self.initial_capital) / self.initial_capital
            )

        period_returns = equity_curve.pct_change().dropna()
        ann_factor = _ANNUALISATION.get(timeframe, math.sqrt(252))
        if len(period_returns) > 0 and period_returns.std() > 0:
            sharpe = float(period_returns.mean() / period_returns.std() * ann_factor)
        else:
            sharpe = 0.0

        rolling_max = equity_curve.cummax()
        drawdown = (equity_curve - rolling_max) / rolling_max
        max_drawdown = float(drawdown.min())

        return {
            "total_return": total_return,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_drawdown,
        }


# ── helpers ───────────────────────────────────────────────────────────────────

def _trade_row(ts, symbol: str, side: str, qty: float, price: float) -> dict:
    return {"timestamp": ts, "symbol": symbol, "side": side, "qty": qty, "price": price}

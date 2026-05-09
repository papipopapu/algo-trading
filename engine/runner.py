"""Live trading runner: wires strategies, WebSocket feed, and order execution."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import pandas as pd

from alpaca.trading.enums import TradeEvent

from data.database import Database, TradeRecord
from execution.alpaca_client import AlpacaClient
from execution.websocket import AlpacaWebSocket
from strategies.base import BaseStrategy, Signal

log = logging.getLogger(__name__)

# Intraday frequencies mapped to their minute count.
# All intraday strategies subscribe to the 1-minute WebSocket stream;
# frequencies > 1 minute are aggregated client-side before dispatch.
_INTRADAY_MINUTES: dict[str, int] = {
    "1Min":  1,
    "5Min":  5,
    "15Min": 15,
    "30Min": 30,
    "1Hour": 60,
}

# Calendar days to look back per unit of `lookback` for each frequency (2× safety buffer).
# Used to compute the REST API seed start date.
_SEED_DAYS_PER_BAR: dict[str, float] = {
    "1Min":  2 / 390,    # ~390 trading minutes per day
    "5Min":  10 / 390,
    "15Min": 30 / 390,
    "30Min": 60 / 390,
    "1Hour": 2 / 7,      # ~7 trading hours per day
    "1Day":  2.0,
    "1Week": 14.0,
}


def _bar_to_df_row(bar) -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "open":   float(bar.open),
            "high":   float(bar.high),
            "low":    float(bar.low),
            "close":  float(bar.close),
            "volume": float(bar.volume),
        }],
        index=pd.DatetimeIndex([bar.timestamp], name="timestamp"),
    )


def _aggregate_to_df_row(bars: list) -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "open":   float(bars[0].open),
            "high":   max(float(b.high) for b in bars),
            "low":    min(float(b.low) for b in bars),
            "close":  float(bars[-1].close),
            "volume": sum(float(b.volume) for b in bars),
        }],
        index=pd.DatetimeIndex([bars[-1].timestamp], name="timestamp"),
    )


class TradingRunner:
    """Orchestrates live paper trading.

    Connects the WebSocket data feed, passes incoming data to each registered
    strategy, and forwards resulting signals to the Alpaca execution client.

    Each strategy declares its `frequency`:
      - "tick"  → on_tick() is called on every real-time trade tick.
      - "1Min"  → generate_signals() called on every 1-minute bar.
      - "5Min", "15Min", "30Min", "1Hour"
                → generate_signals() called on client-side OHLCV aggregations
                  of 1-minute WebSocket bars.
      - "1Day"  → generate_signals() called on every daily bar.
      - "1Week" → generate_signals() called on weekly aggregations of daily
                  bars (flushed every Friday or after 5 accumulated bars).

    Attributes:
        client: Alpaca REST client for order submission and account queries.
        ws: WebSocket client for real-time data and order-event streams.
        db: Optional database for persisting filled trades.
        lookback: Number of bars to keep in memory per (symbol, frequency).
        bar_hook: Optional sync callable(bar) fired on every raw bar received.
        tick_hook: Optional sync callable(tick) fired on every trade tick.
    """

    def __init__(
        self,
        client: AlpacaClient,
        ws: AlpacaWebSocket,
        db: Optional[Database] = None,
        lookback: int = 100,
        bar_hook: Optional[Callable] = None,
        tick_hook: Optional[Callable] = None,
    ) -> None:
        self.client = client
        self.ws = ws
        self.db = db
        self.lookback = lookback
        self.bar_hook = bar_hook
        self.tick_hook = tick_hook
        self.strategies: list[BaseStrategy] = []
        # Historical bars keyed by (symbol, frequency)
        self._bars: dict[tuple[str, str], pd.DataFrame] = {}
        # Aggregation buffers for sub-frequency accumulation, keyed by (symbol, frequency)
        self._agg_buffer: dict[tuple[str, str], list] = {}
        self._pending: dict[str, tuple[Signal, BaseStrategy]] = {}

    def add_strategy(self, strategy: BaseStrategy) -> None:
        """Register a strategy to run during the live session."""
        self.strategies.append(strategy)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _append_bar(self, symbol: str, frequency: str, row: pd.DataFrame) -> None:
        key = (symbol, frequency)
        existing = self._bars.get(key)
        if existing is not None and not existing.empty:
            self._bars[key] = pd.concat([existing, row])
        else:
            self._bars[key] = row

    async def _dispatch_to_strategies(self, symbol: str, frequency: str) -> None:
        df = self._bars.get((symbol, frequency))
        if df is None:
            return
        for strategy in self.strategies:
            if strategy.frequency != frequency or symbol not in strategy.symbols:
                continue
            try:
                signals = strategy.generate_signals(df)
                for signal in signals:
                    await self._execute_signal(signal, strategy)
            except Exception:
                log.exception("strategy %s raised on bar for %s", strategy.name, symbol)

    # ── bar handlers ──────────────────────────────────────────────────────────

    async def _on_minute_bar(self, bar) -> None:
        """Handle a 1-minute bar: dispatch to 1Min strategies, aggregate for longer ones."""
        if self.bar_hook:
            self.bar_hook(bar)

        symbol = bar.symbol

        for freq, n_minutes in _INTRADAY_MINUTES.items():
            relevant = any(
                st.frequency == freq and symbol in st.symbols
                for st in self.strategies
            )
            if not relevant:
                continue

            if n_minutes == 1:
                self._append_bar(symbol, freq, _bar_to_df_row(bar))
                await self._dispatch_to_strategies(symbol, freq)
            else:
                agg_key = (symbol, freq)
                self._agg_buffer.setdefault(agg_key, []).append(bar)
                # Boundary: bar closes the n_minutes window when (minute+1) % n == 0
                # e.g. for 5Min: minute 4 → (4+1)%5 == 0
                if (bar.timestamp.minute + 1) % n_minutes == 0:
                    self._append_bar(symbol, freq, _aggregate_to_df_row(self._agg_buffer[agg_key]))
                    self._agg_buffer[agg_key] = []
                    await self._dispatch_to_strategies(symbol, freq)

    async def _on_daily_bar(self, bar) -> None:
        """Handle a daily bar: dispatch to 1Day strategies, aggregate for weekly ones."""
        if self.bar_hook:
            self.bar_hook(bar)

        symbol = bar.symbol

        if any(st.frequency == "1Day" and symbol in st.symbols for st in self.strategies):
            self._append_bar(symbol, "1Day", _bar_to_df_row(bar))
            await self._dispatch_to_strategies(symbol, "1Day")

        if any(st.frequency == "1Week" and symbol in st.symbols for st in self.strategies):
            agg_key = (symbol, "1Week")
            self._agg_buffer.setdefault(agg_key, []).append(bar)
            # Flush on Friday (weekday == 4) or after 5 bars (short-week safety net)
            if bar.timestamp.weekday() == 4 or len(self._agg_buffer[agg_key]) >= 5:
                self._append_bar(symbol, "1Week", _aggregate_to_df_row(self._agg_buffer[agg_key]))
                self._agg_buffer[agg_key] = []
                await self._dispatch_to_strategies(symbol, "1Week")

    # ── tick handler ──────────────────────────────────────────────────────────

    async def _on_tick(self, tick) -> None:
        """Dispatch a real-time trade tick to tick-based strategies."""
        if self.tick_hook:
            self.tick_hook(tick)

        symbol = tick.symbol
        for strategy in self.strategies:
            if strategy.frequency != "tick" or symbol not in strategy.symbols:
                continue
            try:
                signals = strategy.on_tick(tick)
                for signal in signals:
                    await self._execute_signal(signal, strategy)
            except Exception:
                log.exception("strategy %s raised on tick for %s", strategy.name, symbol)

    # ── order update handler ──────────────────────────────────────────────────

    async def _on_order_update(self, update) -> None:
        """Handle order fill events: notify the strategy and persist the trade."""
        if update.event != TradeEvent.FILL:
            return

        order_id = str(update.order.id)
        if order_id not in self._pending:
            return

        signal, strategy = self._pending.pop(order_id)
        filled_price = float(update.order.filled_avg_price)
        filled_qty = float(update.order.filled_qty)

        strategy.on_fill(signal, filled_price, filled_qty)
        log.info("filled %s %s x%s @ %.2f", signal.side, signal.symbol, filled_qty, filled_price)

        if self.db:
            self.db.insert_trade(TradeRecord(
                symbol=signal.symbol,
                side=signal.side,
                quantity=filled_qty,
                price=filled_price,
                strategy=signal.strategy,
                order_id=order_id,
                timestamp=datetime.now(timezone.utc),
            ))

    # ── signal execution ──────────────────────────────────────────────────────

    async def _execute_signal(self, signal: Signal, strategy: BaseStrategy) -> None:
        """Submit an order for the signal and track it as pending."""
        order_type = "limit" if signal.price is not None else "market"
        try:
            result = self.client.submit_order(
                symbol=signal.symbol,
                qty=signal.quantity,
                side=signal.side,
                order_type=order_type,
                limit_price=signal.price,
            )
            self._pending[result["id"]] = (signal, strategy)
            log.info(
                "submitted %s %s x%s (order %s)",
                signal.side, signal.symbol, signal.quantity, result["id"],
            )
        except Exception:
            log.exception("failed to submit order for signal %s", signal)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Seed bar history, auto-subscribe streams, and start the event loop."""
        tick_symbols = list({
            s for st in self.strategies if st.frequency == "tick"
            for s in st.symbols
        })
        minute_sub_symbols = list({
            s for st in self.strategies if st.frequency in _INTRADAY_MINUTES
            for s in st.symbols
        })
        daily_sub_symbols = list({
            s for st in self.strategies if st.frequency in {"1Day", "1Week"}
            for s in st.symbols
        })

        # Seed historical bars per unique (symbol, frequency) pair
        seed_pairs = {
            (s, st.frequency)
            for st in self.strategies if st.frequency != "tick"
            for s in st.symbols
        }
        end = datetime.now(timezone.utc).date().isoformat()
        for symbol, frequency in seed_pairs:
            days_back = max(7, int(self.lookback * _SEED_DAYS_PER_BAR[frequency]) + 7)
            start = (datetime.now(timezone.utc) - timedelta(days=days_back)).date().isoformat()
            try:
                df = self.client.get_historical_bars(symbol, frequency, start, end)
                self._bars[(symbol, frequency)] = df.tail(self.lookback)
                log.info(
                    "seeded %d %s bars for %s",
                    len(self._bars[(symbol, frequency)]), frequency, symbol,
                )
            except Exception:
                log.exception("failed to seed %s bars for %s", frequency, symbol)
                self._bars[(symbol, frequency)] = pd.DataFrame(
                    columns=["open", "high", "low", "close", "volume"]
                )

        # Register WebSocket handlers based on what strategies need
        if minute_sub_symbols:
            self.ws.on_minute_bar(self._on_minute_bar)
            self.ws.subscribe_minute_bars(minute_sub_symbols)

        if daily_sub_symbols:
            self.ws.on_daily_bar(self._on_daily_bar)
            self.ws.subscribe_daily_bars(daily_sub_symbols)

        if tick_symbols:
            self.ws.on_trade(self._on_tick)
            self.ws.subscribe_ticks(tick_symbols)

        self.ws.on_order_update(self._on_order_update)

        log.info(
            "runner starting — minute symbols: %s  daily symbols: %s  tick symbols: %s",
            minute_sub_symbols or "none",
            daily_sub_symbols or "none",
            tick_symbols or "none",
        )
        await self.ws.run()

    async def stop(self) -> None:
        """Shut down the WebSocket connection."""
        await self.ws.close()

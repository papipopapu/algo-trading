"""Alpaca WebSocket client for real-time market data and order update streams."""

import asyncio
from typing import Callable, Optional

from alpaca.data.live import StockDataStream
from alpaca.trading.stream import TradingStream


class AlpacaWebSocket:
    """Manages connections to Alpaca's streaming WebSocket endpoints.

    Supports three data types from StockDataStream:
      - 1-minute bars  (on_minute_bar / subscribe_minute_bars)
      - daily bars     (on_daily_bar  / subscribe_daily_bars)
      - real-time trade ticks (on_trade / subscribe_ticks)

    Plus order-fill events from TradingStream (on_order_update).
    """

    def __init__(self, api_key: str, secret_key: str) -> None:
        self.api_key = api_key
        self.secret_key = secret_key
        self._minute_bar_handler: Optional[Callable] = None
        self._daily_bar_handler: Optional[Callable] = None
        self._minute_symbols: list[str] = []
        self._daily_symbols: list[str] = []
        self._tick_handler: Optional[Callable] = None
        self._tick_symbols: list[str] = []
        self._order_handler: Optional[Callable] = None
        self._data_stream: Optional[StockDataStream] = None
        self._trade_stream: Optional[TradingStream] = None

    def on_minute_bar(self, handler: Callable) -> None:
        """Register an async callback for 1-minute bar updates."""
        self._minute_bar_handler = handler

    def on_daily_bar(self, handler: Callable) -> None:
        """Register an async callback for end-of-day bar updates."""
        self._daily_bar_handler = handler

    def on_trade(self, handler: Callable) -> None:
        """Register an async callback for real-time trade ticks (Trade objects)."""
        self._tick_handler = handler

    def on_order_update(self, handler: Callable) -> None:
        """Register an async callback for order status change events."""
        self._order_handler = handler

    def subscribe_minute_bars(self, symbols: list[str]) -> None:
        """Set the symbols to receive 1-minute bar updates for."""
        self._minute_symbols = list(symbols)

    def subscribe_daily_bars(self, symbols: list[str]) -> None:
        """Set the symbols to receive daily bar updates for."""
        self._daily_symbols = list(symbols)

    def subscribe_ticks(self, symbols: list[str]) -> None:
        """Set the symbols to receive real-time trade ticks for."""
        self._tick_symbols = list(symbols)

    async def run(self) -> None:
        """Connect both WebSocket streams and dispatch events until stopped."""
        self._data_stream = StockDataStream(self.api_key, self.secret_key)
        self._trade_stream = TradingStream(self.api_key, self.secret_key, paper=True)

        if self._minute_bar_handler and self._minute_symbols:
            self._data_stream.subscribe_bars(self._minute_bar_handler, *self._minute_symbols)

        if self._daily_bar_handler and self._daily_symbols:
            self._data_stream.subscribe_daily_bars(self._daily_bar_handler, *self._daily_symbols)

        if self._tick_handler and self._tick_symbols:
            self._data_stream.subscribe_trades(self._tick_handler, *self._tick_symbols)

        if self._order_handler:
            self._trade_stream.subscribe_trade_updates(self._order_handler)

        await asyncio.gather(
            self._data_stream._run_forever(),
            self._trade_stream._run_forever(),
        )

    async def close(self) -> None:
        """Signal both streams to stop and close their connections."""
        if self._data_stream:
            await self._data_stream.stop_ws()
        if self._trade_stream:
            await self._trade_stream.stop_ws()

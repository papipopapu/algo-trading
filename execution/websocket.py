"""Alpaca WebSocket client for real-time market data and order update streams."""

from typing import Callable, Optional


class AlpacaWebSocket:
    """Manages connections to Alpaca's streaming WebSocket endpoints.

    Subscribes to real-time trade/quote updates and account order events,
    then dispatches payloads to registered handler callbacks.

    Attributes:
        api_key: Alpaca API key.
        secret_key: Alpaca secret key.
        data_url: WebSocket URL for market data stream.
        account_url: WebSocket URL for account/order events.
    """

    def __init__(self, api_key: str, secret_key: str) -> None:
        """Initialize WebSocket client with authentication credentials.

        Args:
            api_key: Alpaca API key.
            secret_key: Alpaca secret key.
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self._bar_handler: Optional[Callable] = None
        self._order_handler: Optional[Callable] = None

    def on_bar(self, handler: Callable) -> None:
        """Register a callback for real-time bar/quote updates.

        Args:
            handler: Async callable that receives a bar payload dict.
        """
        ...

    def on_order_update(self, handler: Callable) -> None:
        """Register a callback for order status change events.

        Args:
            handler: Async callable that receives an order event dict.
        """
        ...

    def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to market data for the given symbols.

        Args:
            symbols: List of tickers to stream.
        """
        ...

    async def run(self) -> None:
        """Start the event loop, connect both WebSocket streams, and dispatch events."""
        ...

    async def close(self) -> None:
        """Gracefully close all WebSocket connections."""
        ...

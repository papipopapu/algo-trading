"""Live trading runner: wires strategies, WebSocket feed, and order execution."""

from strategies.base import BaseStrategy, Signal
from execution.alpaca_client import AlpacaClient
from execution.websocket import AlpacaWebSocket


class TradingRunner:
    """Orchestrates live paper trading.

    Connects the WebSocket data feed, passes incoming bars to each registered
    strategy, and forwards resulting signals to the Alpaca execution client.

    Attributes:
        client: Alpaca REST client for order submission and account queries.
        ws: WebSocket client for real-time bar and order-event streams.
        strategies: List of active strategy instances.
    """

    def __init__(self, client: AlpacaClient, ws: AlpacaWebSocket) -> None:
        """Initialize runner with pre-built client and WebSocket instances.

        Args:
            client: Authenticated AlpacaClient.
            ws: Configured AlpacaWebSocket.
        """
        self.client = client
        self.ws = ws
        self.strategies: list[BaseStrategy] = []

    def add_strategy(self, strategy: BaseStrategy) -> None:
        """Register a strategy to run during the live session.

        Args:
            strategy: Any subclass of BaseStrategy.
        """
        ...

    async def _on_bar(self, bar: dict) -> None:
        """Handle a new bar event from the WebSocket.

        Dispatches the bar to all registered strategies and processes
        any signals they return.

        Args:
            bar: Raw bar payload from the Alpaca stream.
        """
        ...

    async def _execute_signal(self, signal: Signal) -> None:
        """Convert a Signal into an Alpaca order and submit it.

        Args:
            signal: Signal produced by a strategy.
        """
        ...

    async def run(self) -> None:
        """Start the live trading loop (blocking until interrupted)."""
        ...

    async def stop(self) -> None:
        """Shut down the WebSocket connection and finalize open positions."""
        ...

"""Alpaca REST client wrapper for order management and account info (paper trading)."""

from typing import Optional

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

from config import config

_TIMEFRAME_MAP: dict[str, TimeFrame] = {
    "1Day": TimeFrame.Day,
    "1Week": TimeFrame.Week,
    "1Month": TimeFrame.Month,
}


class AlpacaClient:
    """Thin wrapper around the Alpaca REST API targeting the paper trading endpoint."""

    def __init__(self) -> None:
        self.api_key = config.ALPACA_API_KEY
        self.secret_key = config.ALPACA_SECRET_KEY
        self.base_url = config.ALPACA_BASE_URL
        self._trading: Optional[TradingClient] = None
        self._data: Optional[StockHistoricalDataClient] = None

    def connect(self) -> None:
        """Instantiate and authenticate the Alpaca trading and data clients."""
        self._trading = TradingClient(
            api_key=self.api_key,
            secret_key=self.secret_key,
            paper=True,
        )
        self._data = StockHistoricalDataClient(
            api_key=self.api_key,
            secret_key=self.secret_key,
        )

    def _require_trading(self) -> TradingClient:
        if self._trading is None:
            raise RuntimeError("AlpacaClient.connect() must be called first.")
        return self._trading

    def _require_data(self) -> StockHistoricalDataClient:
        if self._data is None:
            raise RuntimeError("AlpacaClient.connect() must be called first.")
        return self._data

    def get_account(self) -> dict:
        """Return account details (equity, buying power, etc.)."""
        account = self._require_trading().get_account()
        return {
            "id": str(account.id),
            "equity": float(account.equity),
            "buying_power": float(account.buying_power),
            "cash": float(account.cash),
            "portfolio_value": float(account.portfolio_value),
            "status": str(account.status),
        }

    def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        time_in_force: str = "day",
    ) -> dict:
        """Submit a single order to Alpaca and return the order dict."""
        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        tif = TimeInForce(time_in_force.lower())

        if order_type == "limit":
            if limit_price is None:
                raise ValueError("limit_price is required for limit orders.")
            req = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                type=OrderType.LIMIT,
                limit_price=limit_price,
                time_in_force=tif,
            )
        else:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=tif,
            )

        order = self._require_trading().submit_order(req)
        return {
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": float(order.qty),
            "side": str(order.side),
            "type": str(order.type),
            "status": str(order.status),
            "limit_price": float(order.limit_price) if order.limit_price else None,
        }

    def get_positions(self) -> list[dict]:
        """Return all currently open positions."""
        positions = self._require_trading().get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": str(p.side),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "avg_entry_price": float(p.avg_entry_price),
            }
            for p in positions
        ]

    def get_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """Fetch historical OHLCV bars. Only daily or higher timeframes are supported.

        Args:
            symbol: Ticker symbol.
            timeframe: '1Day', '1Week', or '1Month'.
            start: ISO-8601 start date string (e.g. '2023-01-01').
            end: ISO-8601 end date string.

        Returns:
            DataFrame with columns [open, high, low, close, volume] indexed by timestamp.

        Raises:
            ValueError: If timeframe is not in {'1Day', '1Week', '1Month'}.
        """
        if timeframe not in _TIMEFRAME_MAP:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}'. "
                f"Allowed: {list(_TIMEFRAME_MAP.keys())}"
            )

        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=_TIMEFRAME_MAP[timeframe],
            start=start,
            end=end,
        )
        bars = self._require_data().get_stock_bars(req)
        df = bars.df

        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")

        df.index.name = "timestamp"
        return df[["open", "high", "low", "close", "volume"]]

    def cancel_order(self, order_id: str) -> None:
        """Cancel an open order by its Alpaca order ID."""
        self._require_trading().cancel_order_by_id(order_id)

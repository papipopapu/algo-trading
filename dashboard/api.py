"""FastAPI application exposing trading metrics, positions, and trade history."""

from fastapi import FastAPI
from data.database import Database, TradeRecord
from execution.alpaca_client import AlpacaClient

app = FastAPI(title="Algo Trading Dashboard", version="0.1.0")

_db: Database = Database()
_client: AlpacaClient = AlpacaClient()


@app.on_event("startup")
async def startup() -> None:
    """Connect to the database and Alpaca client on application startup."""
    ...


@app.on_event("shutdown")
async def shutdown() -> None:
    """Close database connection gracefully on shutdown."""
    ...


@app.get("/account")
async def get_account() -> dict:
    """Return current Alpaca paper account details (equity, buying power, etc.)."""
    ...


@app.get("/positions")
async def get_positions() -> list[dict]:
    """Return all currently open positions from Alpaca."""
    ...


@app.get("/trades")
async def get_trades(
    symbol: str | None = None,
    strategy: str | None = None,
    limit: int = 50,
) -> list[TradeRecord]:
    """Return trade history from the local database with optional filters.

    Query params:
        symbol: Filter by ticker.
        strategy: Filter by strategy name.
        limit: Maximum rows to return (default 50).
    """
    ...


@app.get("/equity")
async def get_equity_curve() -> list[dict]:
    """Return the portfolio equity curve as a list of {timestamp, equity} points."""
    ...

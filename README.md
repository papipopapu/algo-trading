# Algo Trading

Algorithmic trading system in Python connected to the [Alpaca](https://alpaca.markets/) paper trading API.

## Stack

- Python 3.13, `alpaca-py`, pandas, FastAPI
- SQLite (no ORM) for trade and equity persistence
- pytest for all tests

## Project layout

```
algo-trading/
├── config.py               # Config singleton (.env via python-dotenv)
├── strategies/
│   ├── base.py             # BaseStrategy ABC + Signal dataclass
│   └── sma_crossover.py    # SMA golden/death cross strategy
├── execution/
│   ├── alpaca_client.py    # REST paper-trading client
│   └── websocket.py        # Live bar + account-event stream (scaffold)
├── engine/
│   ├── backtester.py       # Event-driven backtester
│   └── runner.py           # Live trading loop (scaffold)
├── data/
│   └── database.py         # SQLite — trades & equity snapshots
├── dashboard/
│   └── api.py              # FastAPI endpoints (scaffold)
└── tests/                  # 79 passing tests
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env          # add your Alpaca paper keys
```

## Running tests

```bash
.venv\Scripts\pytest tests/ -v
```

## Running a backtest

```python
from config import config
from execution.alpaca_client import AlpacaClient
from engine.backtester import Backtester
from strategies.sma_crossover import SMACrossover

client = AlpacaClient()
client.connect()

strategy = SMACrossover(symbols=["AAPL"], short_window=20, long_window=50, qty=1)
bt = Backtester(client, initial_capital=10_000)
result = bt.run(strategy, "AAPL", "1Day", "2022-01-01", "2024-01-01")

print(f"Return:   {result.total_return:.1%}")
print(f"Sharpe:   {result.sharpe_ratio:.2f}")
print(f"Max DD:   {result.max_drawdown:.1%}")
```

## What's implemented

| Module | Status |
|---|---|
| `BaseStrategy` + `Signal` | Done |
| `SMACrossover` | Done |
| `AlpacaClient` (REST) | Done |
| `Backtester` | Done |
| `Database` (SQLite) | Done |
| `AlpacaWebSocket` | Scaffold |
| `TradingRunner` (live loop) | Scaffold |
| `dashboard/api.py` (FastAPI) | Scaffold |

## Design decisions

- **`alpaca-py`** instead of the legacy `alpaca-trade-api` (avoids `websockets==10.4` conflict)
- **Plain sqlite3** — the data model is flat and doesn't need an ORM
- **Daily+ timeframes only** in the backtester — keeps intraday complexity out of scope
- **Fill at next-bar open** — standard no-lookahead model for daily backtesting
- **Long-only** positions in the backtester — sufficient for validating the infrastructure

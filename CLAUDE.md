# Algo Trading

Python algorithmic trading system against the Alpaca paper trading API.
Python 3.13 · virtualenv in `.venv/` · 79 tests passing.

## Commands

```
.venv\Scripts\activate
.venv\Scripts\pytest tests/ -v
uvicorn dashboard.api:app        # once implemented
```

## Architecture

```
algo-trading/
├── config.py                   [DONE]
├── strategies/
│   ├── base.py                 [DONE]     BaseStrategy ABC + Signal dataclass
│   └── sma_crossover.py        [DONE]     SMA golden/death cross
├── execution/
│   ├── alpaca_client.py        [DONE]     REST paper-trading wrapper (alpaca-py)
│   └── websocket.py            [SCAFFOLD]
├── engine/
│   ├── backtester.py           [DONE]     event-driven, daily+ timeframes
│   └── runner.py               [SCAFFOLD]
├── data/
│   └── database.py             [DONE]     SQLite, trades + equity snapshots
├── dashboard/
│   └── api.py                  [SCAFFOLD]
└── tests/                      79 passing (all mocked, no live calls)
```

## Non-obvious technical decisions

- **`alpaca-py` not `alpaca-trade-api`** — legacy package pins `websockets==10.4`, breaks everything else.
- **Fill at next-bar open** — avoids lookahead bias; all signals treated as market orders.
- **Daily+ timeframes only** — explicit design constraint in the backtester; no intraday complexity.
- **`initial_capital=0` returns 0.0** — silent no-op instead of ZeroDivisionError.

## What's left (priority order)

1. **`execution/websocket.py`** — bar stream + account events → `on_bar` / `on_order_update` callbacks
2. **`engine/runner.py`** — asyncio loop: bars → strategies → orders → DB
3. **`dashboard/api.py`** — GET `/account`, `/positions`, `/trades`, `/equity`
4. **Backtester improvements** — limit order simulation, multi-symbol, dynamic position sizing
5. **More strategies** — RSI mean-reversion, Bollinger Bands (any `BaseStrategy` subclass works)

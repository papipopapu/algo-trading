# Algo Trading

Python algorithmic trading system against the Alpaca paper trading API.
Python 3.13 · virtualenv in `.venv/` · 180 tests passing.

## Commands

```
.venv\Scripts\activate
.venv\Scripts\pytest tests/ -v
python main.py                   # live trading + dashboard
```

## Architecture

```
algo-trading/
├── config.py                   [DONE]     loads .env (ALPACA_API_KEY, ALPACA_SECRET_KEY)
├── main.py                     [DONE]     runnable example: two strategies + dashboard
├── strategies/
│   ├── base.py                 [DONE]     BaseStrategy ABC + Signal dataclass
│   ├── sma_crossover.py        [DONE]     SMA golden/death cross (bar-based)
│   └── random_strategy.py      [DONE]     random tick-based trader (TSLA/NVDA demo)
├── execution/
│   ├── alpaca_client.py        [DONE]     REST paper-trading wrapper (alpaca-py)
│   └── websocket.py            [DONE]     StockDataStream + TradingStream, bar/tick/order events
├── engine/
│   ├── backtester.py           [DONE]     event-driven, daily+ timeframes
│   └── runner.py               [DONE]     asyncio loop: feeds → strategies → orders → DB
├── data/
│   └── database.py             [DONE]     SQLite, trades + equity snapshots
├── dashboard/
│   └── api.py                  [DONE]     FastAPI: /account /positions /trades /equity /tickers
│                                          + HTML dashboard with Overview and Tickers tabs
└── tests/                      180 passing (all mocked except 2 integration WebSocket tests)
```

## Strategy system

Each strategy declares a `frequency` class attribute. The runner auto-detects the right WebSocket subscription and REST seed call:

| `frequency` | Live feed | Method called | Seeded with history? |
|---|---|---|---|
| `"tick"` | Real-time trade ticks | `on_tick(tick)` | No |
| `"1Min"` | WebSocket 1-min bars | `generate_signals(df)` | Yes, via REST |
| `"5Min"` / `"15Min"` / `"30Min"` / `"1Hour"` | 1-min WS bars, aggregated client-side | `generate_signals(df)` | Yes, via REST |
| `"1Day"` | WebSocket daily bars | `generate_signals(df)` | Yes, via REST |
| `"1Week"` | Daily WS bars, aggregated client-side (flush on Friday) | `generate_signals(df)` | Yes, via REST |

Adding a new strategy: subclass `BaseStrategy`, set `frequency`, implement the relevant method, call `runner.add_strategy(instance)`. The runner auto-subscribes the right WebSocket streams.

## Non-obvious technical decisions

- **`alpaca-py` not `alpaca-trade-api`** — legacy package pins `websockets==10.4`, breaks everything else.
- **Fill at next-bar open** — avoids lookahead bias in backtester; live runner uses market orders.
- **Daily+ timeframes only in backtester** — explicit design constraint; no intraday complexity there.
- **`initial_capital=0` returns 0.0** — silent no-op instead of ZeroDivisionError.
- **`_run_forever()` not `run()`** — alpaca-py's `stream.run()` calls `asyncio.run()` internally (can't be nested). Use the internal `_run_forever()` coroutine + `asyncio.gather()` to run both streams concurrently in an existing event loop.
- **`stop_ws()` not `stop()`** — `stop()` requires the stream's `_loop` to be set (only after connecting) and uses threading. `stop_ws()` is async and enqueues a stop signal safely.
- **`lifespan="off"` in main.py** — prevents uvicorn from running the dashboard's lifespan (which calls `_db.connect()` / `_client.connect()`). Instead, `main.py` connects both and assigns them to `dashboard_module._db` / `dashboard_module._client` directly.
- **`_latest_ticks` dict** — module-level in `dashboard/api.py`. The runner's `bar_hook` / `tick_hook` write to it; `GET /tickers` reads it. No locking needed (GIL + single-threaded asyncio).
- **`_bars` keyed by `(symbol, frequency)`** — the runner stores one DataFrame per (symbol, frequency) pair. A strategy with `frequency="5Min"` gets `_bars[("AAPL", "5Min")]` seeded from REST and updated from live aggregations. Different frequencies for the same symbol are fully independent.
- **Intraday aggregation boundary** — `(bar.timestamp.minute + 1) % n_minutes == 0`. For 5Min this fires at minutes 4, 9, 14 … For 1Hour at minute 59. Alpaca minute bars are timestamped at the start of the minute, so minute 4 closes the 9:30–9:35 window.
- **Tick throttling in RandomStrategy** — uses `datetime.now(timezone.utc)` (wall clock), not tick timestamp. Tests that check throttling must backdate `_last_action` directly rather than injecting timestamps.
- **`pytest-asyncio` with `asyncio_mode = auto`** — all async test functions run automatically; no `@pytest.mark.asyncio` decorator needed. Config in `pytest.ini`.
- **`httpx` required by Starlette TestClient** — must be installed alongside `fastapi` for dashboard tests.

## Running live (main.py)

Starts three concurrent asyncio tasks:
1. `TradingRunner.run()` — seeds bar history via REST, opens WebSocket streams, dispatches to strategies
2. `uvicorn Server.serve()` — dashboard at http://localhost:8000
3. `_equity_task()` — writes equity snapshot to SQLite every 60s

Active strategies in main.py:
- `SMACrossover(AAPL, MSFT)` — daily bars, signals on golden/death cross
- `RandomStrategy(TSLA, NVDA)` — real-time ticks, random buy/sell every 1–30s

Ctrl+C triggers clean shutdown: uvicorn exits, WebSocket streams close, DB closes.

## What's left (priority order)

1. **Backtester improvements** — limit order simulation, multi-symbol portfolios, dynamic position sizing
2. **More strategies** — RSI mean-reversion, Bollinger Bands, momentum (any `BaseStrategy` subclass works)
3. **Dashboard enhancements** — WebSocket push instead of polling, strategy PnL breakdown per symbol
4. **Risk management layer** — max drawdown kill-switch, per-symbol position limits enforced at runner level

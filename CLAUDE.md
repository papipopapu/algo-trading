# Algo Trading — Guía de sesión

Sistema de algorithmic trading en Python contra la API de Alpaca (paper trading).
Entorno: Python 3.13, virtualenv en `.venv/`, tests con pytest.

```
.venv/Scripts/activate          # activar entorno
.venv/Scripts/pytest tests/ -v  # correr todos los tests (79 passing)
```

---

## Arquitectura

```
algo-trading/
├── config.py                   ← Config singleton (lee .env con python-dotenv)
├── conftest.py                 ← Añade project root a sys.path para pytest
├── .env                        ← API keys (gitignored) — copiar de .env.example
│
├── strategies/
│   ├── base.py                 ← BaseStrategy (ABC) + Signal (dataclass)  [COMPLETO]
│   └── sma_crossover.py        ← SMACrossover                             [COMPLETO]
│
├── execution/
│   ├── alpaca_client.py        ← AlpacaClient (REST paper trading)        [COMPLETO]
│   └── websocket.py            ← AlpacaWebSocket                          [SCAFFOLD]
│
├── engine/
│   ├── backtester.py           ← Backtester + BacktestResult              [COMPLETO]
│   └── runner.py               ← TradingRunner (live loop)                [SCAFFOLD]
│
├── data/
│   └── database.py             ← Database (SQLite) + TradeRecord          [COMPLETO]
│
├── dashboard/
│   └── api.py                  ← FastAPI app                              [SCAFFOLD]
│
└── tests/
    ├── test_alpaca_client.py   ← 16 tests (SDK mockeado)
    ├── test_backtester.py      ← 27 tests
    ├── test_sma_crossover.py   ← 19 tests
    └── test_database.py        ← 17 tests
```

---

## Módulos implementados

### `strategies/base.py`
- `Signal`: dataclass con `symbol`, `side`, `quantity`, `price` (None = market), `strategy`
- `BaseStrategy`: ABC con `generate_signals(bars: DataFrame) -> list[Signal]` y hook `on_fill`

### `strategies/sma_crossover.py`
- `SMACrossover(symbols, short_window=20, long_window=50, qty=1.0)`
- Golden cross → `buy`, death cross → `sell`, como mucho una señal por llamada
- Requiere `long_window + 1` barras mínimo para detectar el cruce
- Diseñada para un único símbolo (`symbols[0]`)

### `execution/alpaca_client.py`
- `AlpacaClient` — wrapper de `alpaca-py` (librería moderna, no `alpaca-trade-api`)
- `connect()` inicializa `TradingClient(paper=True)` y `StockHistoricalDataClient`
- `submit_order(symbol, qty, side, order_type, limit_price, time_in_force)`
- `get_historical_bars(symbol, timeframe, start, end)` → DataFrame OHLCV
  - Solo acepta `'1Day'`, `'1Week'`, `'1Month'` (restricción de diseño del backtester)
  - Devuelve DataFrame con índice `timestamp` sin MultiIndex
- `get_account()`, `get_positions()`, `cancel_order(order_id)`

### `data/database.py`
- `Database(db_path)` — sqlite3 puro (sin SQLAlchemy)
- Tablas: `trades`, `equity_snapshots`
- `connect()` crea tablas si no existen; guard `_require_conn()` en todos los métodos
- `insert_trade(TradeRecord) -> int`, `get_trades(symbol, strategy, limit)`
- `insert_equity_snapshot(equity, timestamp)`, `get_equity_curve()`

### `engine/backtester.py`
- `Backtester(client, initial_capital=100_000, commission=0.0)`
- `run(strategy, symbol, timeframe, start, end) -> BacktestResult`
- Modelo de ejecución: señal en barra `i` → fill al `open` de barra `i+1`
- Long-only; fills capados por cash (compras) y shares en cartera (ventas)
- Métricas en `BacktestResult`: `total_return`, `sharpe_ratio`, `max_drawdown`
  - Sharpe anualizado con factor correcto por timeframe: √252, √52, √12
- `_simulate_fill`: todas las señales se tratan como market orders (sin lógica de limit)

---

## Decisiones técnicas

| Decisión | Motivo |
|---|---|
| `alpaca-py` en lugar de `alpaca-trade-api` | `alpaca-trade-api` es legacy y fuerza `websockets==10.4`, rompiendo otros paquetes |
| sqlite3 directo (sin SQLAlchemy ORM) | Simplicidad; el modelo de datos es plano y no justifica un ORM |
| Backtester solo acepta timeframes diarios o superiores | Restricción de diseño explícita; evita complejidad de datos intradía |
| Fill al open de la siguiente barra | Evita lookahead bias; modelo estándar para backtesting diario |
| Posiciones long-only en el backtester | POC; suficiente para validar la infraestructura |
| `initial_capital=0` no lanza excepción | Genera `total_return=0.0` en lugar de dividir por cero |
| Tests con datos sintéticos calculados a mano | Los SMAs de los tests de golden/death cross están verificados numéricamente en los docstrings |

---

## Qué queda por implementar

### Prioritario (bloquea el trading en vivo)

1. **`execution/websocket.py`** — `AlpacaWebSocket`
   - Conectar al stream de barras de Alpaca (`wss://stream.data.alpaca.markets`)
   - Conectar al stream de eventos de cuenta (fills, order updates)
   - Dispatch a callbacks `on_bar` y `on_order_update`

2. **`engine/runner.py`** — `TradingRunner`
   - Loop asyncio que consume el WebSocket
   - Pasa barras a todas las estrategias registradas
   - Convierte señales en órdenes via `AlpacaClient.submit_order`
   - Persiste fills en `Database`
   - `add_strategy`, `run`, `stop`

### Secundario

3. **`dashboard/api.py`** — endpoints FastAPI
   - `GET /account` → `AlpacaClient.get_account()`
   - `GET /positions` → `AlpacaClient.get_positions()`
   - `GET /trades` → `Database.get_trades()`
   - `GET /equity` → `Database.get_equity_curve()`
   - Arrancar con `uvicorn dashboard.api:app`

### Mejoras futuras al backtester
- Soporte de limit orders en `_simulate_fill` (verificar si el límite se cruza dentro de la barra)
- Multi-símbolo en una sola ejecución
- Position sizing dinámico (% de capital en lugar de cantidad fija)

### Más estrategias
- RSI mean-reversion
- Bollinger Bands breakout
- Cualquiera que herede `BaseStrategy` e implemente `generate_signals`

---

## Cómo correr un backtest (cuando tengas keys en .env)

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

print(f"Return:    {result.total_return:.1%}")
print(f"Sharpe:    {result.sharpe_ratio:.2f}")
print(f"Max DD:    {result.max_drawdown:.1%}")
print(result.trades)
```

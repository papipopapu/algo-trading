# Algo Trading

Base para implementar y estudiar estrategias de trading algorítmico conectadas a la API de paper trading de [Alpaca](https://alpaca.markets/). Incluye backtester, ejecución en vivo y un dashboard web.

## Stack

- Python 3.13, `alpaca-py`, pandas, FastAPI, SQLite
- 180 tests con pytest

## Estructura

```
algo-trading/
├── config.py               # Carga .env (claves Alpaca)
├── main.py                 # Punto de entrada: lanza runner + dashboard
├── strategies/
│   ├── base.py             # BaseStrategy (ABC) + Signal
│   ├── sma_crossover.py    # Ejemplo: cruce de medias móviles (barras diarias)
│   └── random_strategy.py  # Ejemplo: órdenes aleatorias por tick (TSLA/NVDA)
├── execution/
│   ├── alpaca_client.py    # Cliente REST paper trading
│   └── websocket.py        # Streams de barras y eventos de cuenta
├── engine/
│   ├── backtester.py       # Backtester event-driven (timeframes diarios+)
│   └── runner.py           # Loop en vivo: feeds → estrategias → órdenes
├── data/
│   └── database.py         # SQLite: trades y snapshots de equity
├── dashboard/
│   └── api.py              # FastAPI: cuenta, posiciones, trades, equity, tickers
└── tests/
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # añadir ALPACA_API_KEY y ALPACA_SECRET_KEY
```

## Uso

**Ejecutar en vivo + dashboard** (`http://localhost:8000`):
```bash
python main.py
```

**Tests:**
```bash
.venv\Scripts\pytest tests/ -v
```

**Backtest:**
```python
from execution.alpaca_client import AlpacaClient
from engine.backtester import Backtester
from strategies.sma_crossover import SMACrossover

client = AlpacaClient()
client.connect()

strategy = SMACrossover(symbols=["AAPL"], short_window=20, long_window=50, qty=1)
bt = Backtester(client, initial_capital=10_000)
result = bt.run(strategy, "AAPL", "1Day", "2022-01-01", "2024-01-01")

print(f"Retorno:  {result.total_return:.1%}")
print(f"Sharpe:   {result.sharpe_ratio:.2f}")
print(f"Max DD:   {result.max_drawdown:.1%}")
```

## Añadir una estrategia nueva

1. Crear una subclase de `BaseStrategy` en `strategies/`
2. Definir el atributo `frequency` (`"tick"`, `"1Min"`, `"5Min"`, `"1Day"`, etc.)
3. Implementar `on_tick(tick)` (tick) o `generate_signals(df)` (barras)
4. Registrarla en el runner: `runner.add_strategy(mi_estrategia)`

El runner se encarga automáticamente de suscribirse al stream correcto y de poblar el histórico vía REST.

## Decisiones de diseño

- **`alpaca-py`** en vez del paquete legacy (evita conflicto con `websockets==10.4`)
- **Fill al open de la siguiente barra** — sin lookahead bias en el backtester
- **Backtester solo timeframes diarios+** — la complejidad intraday queda fuera de scope
- **SQLite sin ORM** — el modelo de datos es plano y no lo necesita

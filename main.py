"""
main.py — Ejemplo completo: SMA Crossover + RandomStrategy en paper trading con dashboard.

Arranca tres tareas concurrentes:
  1. TradingRunner  — WebSocket de barras diarias + ticks en tiempo real
                      → estrategias → órdenes → SQLite
  2. Dashboard      — FastAPI en http://localhost:8000
  3. Equity snapshots — escribe equity en DB cada EQUITY_INTERVAL segundos

Estrategias activas:
  - SMACrossover(AAPL, MSFT) — barras diarias, señal en golden/death cross
  - RandomStrategy(TSLA, NVDA) — ticks en tiempo real, trades aleatorios cada 1-30s

Las barras diarias llegan a las 16:00 ET (cierre NYSE).
Los ticks llegan durante el horario de mercado (9:30–16:00 ET).

Uso:
    python main.py
    Ctrl+C para parar limpiamente.
"""

import asyncio
import logging
from datetime import datetime, timezone

from uvicorn import Config, Server

import dashboard.api as dashboard_module
from config import config
from data.database import Database
from engine.runner import TradingRunner
from execution.alpaca_client import AlpacaClient
from execution.websocket import AlpacaWebSocket
from strategies.random_strategy import RandomStrategy
from strategies.sma_crossover import SMACrossover

# ── parámetros ────────────────────────────────────────────────────────────────

SMA_SYMBOLS      = ["AAPL", "MSFT"]   # barras diarias
SHORT_WINDOW     = 20
LONG_WINDOW      = 50
TICK_SYMBOLS     = ["TSLA", "NVDA"]   # ticks en tiempo real
QTY              = 1.0
LOOKBACK         = 100
EQUITY_INTERVAL  = 60

# ── logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


# ── tarea de equity snapshots ─────────────────────────────────────────────────

async def _equity_task(client: AlpacaClient, db: Database) -> None:
    """Guarda un snapshot de equity en la DB cada EQUITY_INTERVAL segundos."""
    while True:
        try:
            account = client.get_account()
            equity = account["equity"]
            db.insert_equity_snapshot(equity, datetime.now(timezone.utc))
            log.info("equity snapshot  $%s", f"{equity:,.2f}")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("equity snapshot falló")
        await asyncio.sleep(EQUITY_INTERVAL)


# ── main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    # ── inicializar componentes ───────────────────────────────────────────────
    log.info("conectando con Alpaca paper trading...")

    db = Database()
    db.connect()

    client = AlpacaClient()
    client.connect()

    account = client.get_account()
    log.info(
        "cuenta OK  equity=$%s  buying_power=$%s  cash=$%s",
        f"{account['equity']:,.2f}", f"{account['buying_power']:,.2f}", f"{account['cash']:,.2f}",
    )

    # Mostrar trades recientes de la DB al arrancar
    recent = db.get_trades(limit=5)
    if recent:
        log.info("últimos %d trades en DB:", len(recent))
        for t in recent:
            log.info("  %s  %-4s  %-6s  x%.1f  @$%.2f  [%s]",
                     t.timestamp.strftime("%Y-%m-%d"), t.symbol,
                     t.side, t.quantity, t.price, t.strategy)
    else:
        log.info("DB vacía — aún no hay trades registrados")

    # ── hooks para el dashboard de tickers ───────────────────────────────────
    # Capturan el último dato de cada símbolo y lo exponen en GET /tickers.

    def _bar_hook(bar) -> None:
        dashboard_module._latest_ticks[bar.symbol] = {
            "price": float(bar.close),
            "size": float(bar.volume),
            "timestamp": bar.timestamp.isoformat(),
        }

    def _tick_hook(tick) -> None:
        dashboard_module._latest_ticks[tick.symbol] = {
            "price": float(tick.price),
            "size": float(tick.size),
            "timestamp": tick.timestamp.isoformat(),
        }

    # ── estrategias y runner ──────────────────────────────────────────────────
    sma_strategy = SMACrossover(
        symbols=SMA_SYMBOLS,
        short_window=SHORT_WINDOW,
        long_window=LONG_WINDOW,
        qty=QTY,
    )
    random_strategy = RandomStrategy(
        symbols=TICK_SYMBOLS,
        qty=QTY,
        max_position=3,
        min_interval=1.0,
        max_interval=30.0,
    )

    ws = AlpacaWebSocket(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)

    runner = TradingRunner(
        client=client,
        ws=ws,
        db=db,
        lookback=LOOKBACK,
        bar_hook=_bar_hook,
        tick_hook=_tick_hook,
    )
    runner.add_strategy(sma_strategy)
    runner.add_strategy(random_strategy)

    # ── compartir instancias con el dashboard ─────────────────────────────────
    # El dashboard usa las mismas conexiones (no duplica clientes).
    # lifespan="off" evita que el dashboard llame connect()/close() por su cuenta.
    dashboard_module._db = db
    dashboard_module._client = client

    # ── snapshot inicial de equity ────────────────────────────────────────────
    try:
        db.insert_equity_snapshot(account["equity"], datetime.now(timezone.utc))
    except Exception:
        log.exception("snapshot inicial de equity falló")

    # ── uvicorn ───────────────────────────────────────────────────────────────
    uv_cfg = Config(
        app=dashboard_module.app,
        host="0.0.0.0",
        port=8000,
        log_level="warning",
        lifespan="off",   # gestionamos connect/close nosotros arriba
    )
    server = Server(uv_cfg)

    log.info("-" * 60)
    log.info("dashboard   ->  http://localhost:8000")
    log.info("SMA(%d/%d)  ->  barras diarias en %s", SHORT_WINDOW, LONG_WINDOW, SMA_SYMBOLS)
    log.info("RandomStrategy -> ticks en tiempo real en %s (1-30s)", TICK_SYMBOLS)
    log.info("barras diarias llegan a las ~16:00 ET (cierre NYSE)")
    log.info("ticks disponibles durante horario de mercado (9:30-16:00 ET)")
    log.info("-" * 60)

    # ── tareas concurrentes ───────────────────────────────────────────────────
    tasks = [
        asyncio.create_task(server.serve(),                        name="dashboard"),
        asyncio.create_task(runner.run(),                          name="runner"),
        asyncio.create_task(_equity_task(client, db),              name="equity"),
    ]

    try:
        await asyncio.gather(*tasks)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        log.info("parando...")
        server.should_exit = True
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await runner.stop()
        except Exception:
            pass
        db.close()
        log.info("parado limpiamente.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

"""FastAPI application exposing trading metrics, positions, and trade history."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from data.database import Database
from execution.alpaca_client import AlpacaClient

_db: Database = Database()
_client: AlpacaClient = AlpacaClient()
# Populated by the runner's tick_hook / bar_hook so the Tickers tab stays live.
_latest_ticks: dict[str, dict] = {}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _db.connect()
    _client.connect()
    yield
    _db.close()


app = FastAPI(title="Algo Trading Dashboard", version="0.1.0", lifespan=_lifespan)

# ── HTML dashboard ─────────────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Algo Trading Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0d1117; color: #c9d1d9;
    min-height: 100vh; padding: 28px 32px;
  }
  header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 20px; flex-wrap: wrap; gap: 12px;
  }
  header h1 { font-size: 1.25rem; font-weight: 600; color: #f0f6fc; }
  .meta { font-size: 0.75rem; color: #484f58; }
  .meta span { color: #8b949e; }

  /* tabs */
  .tab-nav {
    display: flex; gap: 4px; margin-bottom: 24px;
    border-bottom: 1px solid #21262d; padding-bottom: 0;
  }
  .tab-btn {
    background: none; border: none; color: #8b949e;
    padding: 8px 18px; font-size: 0.85rem; cursor: pointer;
    border-bottom: 2px solid transparent; margin-bottom: -1px;
    border-radius: 4px 4px 0 0; transition: color 0.15s;
  }
  .tab-btn:hover { color: #c9d1d9; }
  .tab-btn.active { color: #f0f6fc; border-bottom-color: #2f81f7; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  /* status dot */
  .dot {
    display: inline-block; width: 9px; height: 9px;
    border-radius: 50%; margin-right: 8px; vertical-align: middle;
    background: #484f58;
  }
  .dot.active  { background: #3fb950; box-shadow: 0 0 6px #3fb950; }
  .dot.inactive { background: #f85149; }

  /* metric cards */
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px; margin-bottom: 24px;
  }
  .card {
    background: #161b22; border: 1px solid #21262d;
    border-radius: 10px; padding: 20px 22px;
  }
  .card .label {
    font-size: 0.7rem; text-transform: uppercase;
    letter-spacing: 0.08em; color: #484f58; margin-bottom: 10px;
  }
  .card .val {
    font-size: 1.6rem; font-weight: 700; color: #f0f6fc;
    font-variant-numeric: tabular-nums;
  }
  .card.status-card .val { font-size: 1rem; display: flex; align-items: center; }

  /* ticker cards grid */
  .ticker-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 16px;
  }
  .ticker-card {
    background: #161b22; border: 1px solid #21262d;
    border-radius: 10px; padding: 20px 22px;
  }
  .ticker-card .sym { font-size: 1.1rem; font-weight: 700; color: #f0f6fc; margin-bottom: 12px; }
  .ticker-card .price {
    font-size: 2rem; font-weight: 700; color: #2f81f7;
    font-variant-numeric: tabular-nums; margin-bottom: 8px;
  }
  .ticker-card .detail { font-size: 0.75rem; color: #484f58; margin-top: 4px; }
  .ticker-card .detail span { color: #8b949e; }
  .no-tickers { color: #484f58; font-size: 0.875rem; padding: 16px 0; }

  /* sections */
  .section {
    background: #161b22; border: 1px solid #21262d;
    border-radius: 10px; padding: 22px 24px; margin-bottom: 20px;
  }
  .section h2 {
    font-size: 0.75rem; text-transform: uppercase;
    letter-spacing: 0.08em; color: #8b949e; margin-bottom: 18px;
  }
  .chart-wrap { position: relative; height: 260px; }

  /* tables */
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th {
    text-align: left; padding: 6px 12px;
    font-size: 0.7rem; text-transform: uppercase;
    letter-spacing: 0.06em; color: #484f58;
    border-bottom: 1px solid #21262d;
  }
  td { padding: 10px 12px; border-bottom: 1px solid #161b22; color: #c9d1d9; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #1c2128; }
  .sym  { font-weight: 600; color: #f0f6fc; }
  .buy  { color: #3fb950; font-weight: 600; }
  .sell { color: #f85149; font-weight: 600; }
  .muted { color: #484f58; font-style: italic; }
  .pos  { color: #3fb950; }
  .neg  { color: #f85149; }
</style>
</head>
<body>

<header>
  <h1><span class="dot" id="dot"></span>Algo Trading Dashboard</h1>
  <p class="meta">Actualiza cada 10 s &nbsp;·&nbsp; Ultima vez: <span id="ts">-</span></p>
</header>

<nav class="tab-nav">
  <button class="tab-btn active" data-tab="overview">Overview</button>
  <button class="tab-btn"        data-tab="tickers">Tickers en vivo</button>
</nav>

<!-- ── TAB: OVERVIEW ── -->
<div id="panel-overview" class="tab-panel active">

  <div class="cards">
    <div class="card status-card">
      <div class="label">Estado</div>
      <div class="val" id="status-val">-</div>
    </div>
    <div class="card">
      <div class="label">Equity</div>
      <div class="val" id="equity-val">-</div>
    </div>
    <div class="card">
      <div class="label">Buying Power</div>
      <div class="val" id="bp-val">-</div>
    </div>
    <div class="card">
      <div class="label">Cash</div>
      <div class="val" id="cash-val">-</div>
    </div>
  </div>

  <div class="section">
    <h2>Equity Curve</h2>
    <div class="chart-wrap"><canvas id="eq-chart"></canvas></div>
  </div>

  <div class="section">
    <h2>Posiciones Abiertas</h2>
    <table>
      <thead>
        <tr>
          <th>Simbolo</th><th>Cantidad</th><th>Entrada Avg</th>
          <th>Valor Mercado</th><th>P&amp;L No realizado</th>
        </tr>
      </thead>
      <tbody id="pos-body"></tbody>
    </table>
  </div>

  <div class="section">
    <h2>Ultimos Trades</h2>
    <table>
      <thead>
        <tr>
          <th>Timestamp</th><th>Simbolo</th><th>Lado</th>
          <th>Cantidad</th><th>Precio</th><th>Estrategia</th>
        </tr>
      </thead>
      <tbody id="trades-body"></tbody>
    </table>
  </div>

</div><!-- end overview -->

<!-- ── TAB: TICKERS ── -->
<div id="panel-tickers" class="tab-panel">
  <div class="section">
    <h2>Precios en tiempo real</h2>
    <div class="ticker-grid" id="ticker-grid">
      <p class="no-tickers">Sin datos de tickers aun. Los tickers aparecen cuando el mercado esta abierto y el runner recibe ticks.</p>
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);

// ── tab navigation ────────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    $('panel-' + btn.dataset.tab).classList.add('active');
  });
});

// ── formatting ────────────────────────────────────────────────────────────────
const usd = n => n != null
  ? '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})
  : '-';
const num = n => n != null
  ? Number(n).toLocaleString('en-US', {minimumFractionDigits: 4, maximumFractionDigits: 4})
  : '-';

async function api(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

// ── account ───────────────────────────────────────────────────────────────────
async function refreshAccount() {
  try {
    const d = await api('/account');
    $('dot').className = 'dot active';
    $('status-val').innerHTML = '<span class="dot active"></span>Activo';
    $('equity-val').textContent = usd(d.equity);
    $('bp-val').textContent     = usd(d.buying_power);
    $('cash-val').textContent   = usd(d.cash);
  } catch {
    $('dot').className = 'dot inactive';
    $('status-val').innerHTML = '<span class="dot inactive"></span>Inactivo';
    $('equity-val').textContent = $('bp-val').textContent = $('cash-val').textContent = '-';
  }
}

// ── positions ─────────────────────────────────────────────────────────────────
async function refreshPositions() {
  const tb = $('pos-body');
  try {
    const ps = await api('/positions');
    if (!ps.length) {
      tb.innerHTML = '<tr><td colspan="5" class="muted">Sin posiciones abiertas</td></tr>';
      return;
    }
    tb.innerHTML = ps.map(p => {
      const pl = Number(p.unrealized_pl);
      return `<tr>
        <td class="sym">${p.symbol}</td>
        <td>${num(p.qty)}</td>
        <td>${usd(p.avg_entry_price)}</td>
        <td>${usd(p.market_value)}</td>
        <td class="${pl >= 0 ? 'pos' : 'neg'}">${usd(p.unrealized_pl)}</td>
      </tr>`;
    }).join('');
  } catch {
    tb.innerHTML = '<tr><td colspan="5" class="neg">Error cargando posiciones</td></tr>';
  }
}

// ── trades ────────────────────────────────────────────────────────────────────
async function refreshTrades() {
  const tb = $('trades-body');
  try {
    const ts = await api('/trades?limit=20');
    if (!ts.length) {
      tb.innerHTML = '<tr><td colspan="6" class="muted">Sin trades registrados</td></tr>';
      return;
    }
    tb.innerHTML = ts.map(t => `<tr>
      <td>${new Date(t.timestamp).toLocaleString('es-ES')}</td>
      <td class="sym">${t.symbol}</td>
      <td class="${t.side === 'buy' ? 'buy' : 'sell'}">${t.side.toUpperCase()}</td>
      <td>${num(t.quantity)}</td>
      <td>${usd(t.price)}</td>
      <td style="color:#8b949e">${t.strategy}</td>
    </tr>`).join('');
  } catch {
    tb.innerHTML = '<tr><td colspan="6" class="neg">Error cargando trades</td></tr>';
  }
}

// ── equity chart ──────────────────────────────────────────────────────────────
let chart = null;

async function refreshChart() {
  try {
    const pts = await api('/equity');
    const labels = pts.map(p => new Date(p.timestamp).toLocaleDateString('es-ES'));
    const data   = pts.map(p => p.equity);

    if (!chart) {
      const ctx = $('eq-chart').getContext('2d');
      chart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            data,
            borderColor: '#2f81f7',
            backgroundColor: 'rgba(47,129,247,0.08)',
            borderWidth: 2,
            pointRadius: data.length < 60 ? 3 : 0,
            fill: true,
            tension: 0.3,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { callbacks: { label: ctx => ' ' + usd(ctx.parsed.y) } }
          },
          scales: {
            x: { ticks: { color: '#484f58', maxTicksLimit: 10 }, grid: { color: '#21262d' } },
            y: {
              ticks: { color: '#484f58', callback: v => '$' + v.toLocaleString() },
              grid:  { color: '#21262d' }
            }
          }
        }
      });
    } else {
      chart.data.labels = labels;
      chart.data.datasets[0].data = data;
      chart.data.datasets[0].pointRadius = data.length < 60 ? 3 : 0;
      chart.update('none');
    }
  } catch { /* equity may be empty */ }
}

// ── tickers ───────────────────────────────────────────────────────────────────
async function refreshTickers() {
  const grid = $('ticker-grid');
  try {
    const tickers = await api('/tickers');
    const syms = Object.keys(tickers);
    if (!syms.length) {
      grid.innerHTML = '<p class="no-tickers">Sin datos de tickers aun. Los tickers aparecen cuando el mercado esta abierto y el runner recibe ticks.</p>';
      return;
    }
    grid.innerHTML = syms.map(sym => {
      const t = tickers[sym];
      const ts = t.timestamp ? new Date(t.timestamp).toLocaleTimeString('es-ES') : '-';
      return `<div class="ticker-card">
        <div class="sym">${sym}</div>
        <div class="price">${usd(t.price)}</div>
        <div class="detail">Tamano: <span>${t.size != null ? t.size.toLocaleString() : '-'}</span></div>
        <div class="detail">Ultimo tick: <span>${ts}</span></div>
      </div>`;
    }).join('');
  } catch {
    grid.innerHTML = '<p class="no-tickers" style="color:#f85149">Error cargando tickers</p>';
  }
}

// ── main loop ─────────────────────────────────────────────────────────────────
async function refresh() {
  await Promise.all([
    refreshAccount(), refreshPositions(), refreshTrades(), refreshChart(), refreshTickers()
  ]);
  $('ts').textContent = new Date().toLocaleTimeString('es-ES');
}

refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>"""


# ── API endpoints ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(_HTML)


@app.get("/account")
async def get_account() -> dict:
    """Return current Alpaca paper account details."""
    try:
        return _client.get_account()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/positions")
async def get_positions() -> list[dict]:
    """Return all currently open positions from Alpaca."""
    try:
        return _client.get_positions()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/trades")
async def get_trades(
    symbol: str | None = None,
    strategy: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return trade history from the local database with optional filters."""
    records = _db.get_trades(symbol=symbol, strategy=strategy, limit=limit)
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "side": r.side,
            "quantity": r.quantity,
            "price": r.price,
            "strategy": r.strategy,
            "order_id": r.order_id,
            "timestamp": r.timestamp.isoformat(),
        }
        for r in records
    ]


@app.get("/equity")
async def get_equity_curve() -> list[dict]:
    """Return the portfolio equity curve as {timestamp, equity} points."""
    return _db.get_equity_curve()


@app.get("/tickers")
async def get_tickers() -> dict:
    """Return the latest tick data per symbol, populated by the runner's tick/bar hooks."""
    return _latest_ticks

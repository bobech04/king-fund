'use strict';

const API    = '/api';
const TARGET = 10_000;
const START  = 500;

let state       = null;
let ws          = null;
let pollTimer   = null;
let modalChart  = null;
let activeTraderId = null;

// ─── WebSocket ────────────────────────────────────────────────────

function initWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws`);

  ws.onopen    = () => { stopPolling(); hideBanner(); };
  ws.onclose   = () => { showBanner(); startPolling(); setTimeout(initWS, 5000); };
  ws.onerror   = () => ws.close();
  ws.onmessage = ({ data }) => {
    const msg = JSON.parse(data);
    if (msg.type !== 'heartbeat') applyState(msg);
  };
}

function startPolling() {
  if (pollTimer) return;
  fetchState();
  pollTimer = setInterval(fetchState, 5000);
}

function stopPolling() {
  clearInterval(pollTimer);
  pollTimer = null;
}

async function fetchState() {
  try { applyState(await (await fetch(`${API}/state`)).json()); } catch {}
}

// ─── State ────────────────────────────────────────────────────────

function applyState(s) {
  state = s;

  qs('#battle-day').textContent = `J${s.battle_day} / 30`;
  const winners = s.leaderboard.filter(t => t.won).length;
  qs('#winners-count').textContent = winners > 0 ? `${winners} 👑` : '0';
  qs('#update-time').textContent = new Date().toLocaleTimeString('fr-FR', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });

  renderLeaderboard(s.leaderboard);

  if (activeTraderId !== null) refreshModal();
}

// ─── Leaderboard ──────────────────────────────────────────────────

function renderLeaderboard(traders) {
  const container = qs('main');
  const byId = {};
  container.querySelectorAll('.card').forEach(el => { byId[el.dataset.id] = el; });

  traders.forEach(t => {
    let card = byId[t.id];
    if (!card) {
      card = document.createElement('div');
      card.className = 'card';
      card.dataset.id = t.id;
    }
    card.className = `card${t.won ? ' won' : ''}`;
    card.innerHTML = cardHTML(t);
    container.appendChild(card);
  });
}

function cardHTML(t) {
  const pp      = pct(t.value);
  const sign    = t.pnl >= 0 ? '+' : '';
  const pnlCls  = t.pnl >= 0 ? 'green' : 'red';
  const fillCls = t.won ? ' gold' : t.pnl < 0 ? ' red' : '';
  return `
    <div class="card-top">
      <div class="card-rank">${rankIcon(t.rank)}</div>
      <div class="card-info">
        <div class="card-name">
          ${t.name}
          ${t.won ? '<span class="won-badge">WINNER</span>' : ''}
        </div>
        <div class="card-strategy">${t.strategy}</div>
      </div>
      <div class="card-right">
        <div class="card-value">€${fmt(t.value, 0)}</div>
        <div class="card-pnl ${pnlCls}">${sign}€${fmt(Math.abs(t.pnl), 0)} (${sign}${t.pnl_pct}%)</div>
      </div>
    </div>
    <div class="progress-bg">
      <div class="progress-fill${fillCls}" style="width:${pp}%"></div>
    </div>`;
}

function rankIcon(r) {
  if (r === 1) return '🥇';
  if (r === 2) return '🥈';
  if (r === 3) return '🥉';
  return `<span class="num">#${r}</span>`;
}

// ─── Modal ────────────────────────────────────────────────────────

function openModal(id) {
  activeTraderId = id;
  qs('#overlay').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
  refreshModal();
}

function closeModal() {
  qs('#overlay').classList.add('hidden');
  document.body.style.overflow = '';
  if (modalChart) { modalChart.destroy(); modalChart = null; }
  activeTraderId = null;
}

async function refreshModal() {
  try {
    const data = await (await fetch(`${API}/trader/${activeTraderId}`)).json();
    renderModal(data);
  } catch {}
}

function renderModal(data) {
  const ts   = state?.leaderboard.find(t => t.id === data.id);
  const pnl  = data.value - START;
  const sign = pnl >= 0 ? '+' : '';
  const cls  = pnl >= 0 ? 'green' : 'red';

  qs('#modal-name').textContent      = data.name;
  qs('#modal-strategy').textContent  = data.strategy;
  qs('#modal-rank-badge').textContent = ts
    ? (ts.rank <= 3 ? rankIcon(ts.rank) : `#${ts.rank}`)
    : '';

  qs('#modal-value').textContent = `€${fmt(data.value, 2)}`;
  qs('#modal-pnl').innerHTML =
    `<span class="${cls}">${sign}€${fmt(Math.abs(pnl), 2)} (${sign}${((pnl / START) * 100).toFixed(2)}%)</span>`;

  const pp   = pct(data.value);
  const fill = qs('#modal-progress');
  fill.style.width  = `${pp}%`;
  fill.className    = `progress-fill${data.value >= TARGET ? ' gold' : pnl < 0 ? ' red' : ''}`;
  qs('#modal-progress-pct').textContent = `${pp.toFixed(1)}%`;

  renderChart(data.history || []);
  renderPositions(data.positions || {}, data.cash ?? 0);
  renderTrades(data.trades || []);
}

// ─── Chart ────────────────────────────────────────────────────────

function renderChart(history) {
  if (modalChart) { modalChart.destroy(); modalChart = null; }
  if (history.length < 2) return;

  const labels = history.map(h => h.timestamp.slice(11, 16));
  const values = history.map(h => h.portfolio_value);
  const isUp   = values.at(-1) >= values[0];
  const color  = isUp ? '#00e5a0' : '#ff4466';

  modalChart = new Chart(qs('#modal-chart').getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: values,
        borderColor: color,
        borderWidth: 2,
        pointRadius: 0,
        fill: true,
        backgroundColor: `${color}18`,
        tension: 0.35,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: 'index',
          intersect: false,
          callbacks: { label: ctx => `€${ctx.parsed.y.toFixed(2)}` },
        },
      },
      scales: {
        x: {
          ticks: { color: '#52526a', maxTicksLimit: 6, font: { size: 10 } },
          grid:  { color: '#222230' },
        },
        y: {
          ticks: { color: '#52526a', font: { size: 10 }, callback: v => `€${v.toFixed(0)}` },
          grid:  { color: '#222230' },
        },
      },
    },
  });
}

// ─── Positions ────────────────────────────────────────────────────

function renderPositions(positions, cash) {
  const el      = qs('#modal-positions');
  const entries = Object.entries(positions).filter(([, qty]) => qty > 0);
  const cashRow = `
    <div class="position-row">
      <span class="pos-symbol">💶 CASH</span>
      <span class="pos-qty">€${fmt(cash, 2)}</span>
    </div>`;

  if (!entries.length) {
    el.innerHTML = cashRow + '<div class="empty-state">Pas de positions ouvertes</div>';
    return;
  }
  el.innerHTML = cashRow + entries.map(([sym, qty]) => `
    <div class="position-row">
      <span class="pos-symbol">${sym}</span>
      <span class="pos-qty">${trimQty(qty)} unités</span>
    </div>`).join('');
}

// ─── Trades ───────────────────────────────────────────────────────

function renderTrades(trades) {
  const el = qs('#modal-trades');
  if (!trades.length) { el.innerHTML = '<div class="empty-state">Aucun trade</div>'; return; }
  el.innerHTML = trades.slice(0, 20).map(tr => {
    const buy = tr.action === 'buy';
    return `
      <div class="trade-row ${buy ? 'buy' : 'sell'}">
        <span class="trade-action">${buy ? '↑ BUY' : '↓ SELL'}</span>
        <span class="trade-symbol">${tr.symbol}</span>
        <span class="trade-amount">×${trimQty(tr.amount)}</span>
        <span class="trade-price">@ €${Number(tr.price).toFixed(2)}</span>
        <span class="trade-time">${tr.timestamp.slice(11, 16)}</span>
      </div>`;
  }).join('');
}

// ─── Helpers ──────────────────────────────────────────────────────

function pct(value) {
  return Math.min(100, Math.max(0, (value - START) / (TARGET - START) * 100));
}

function fmt(n, decimals) {
  return Number(n).toLocaleString('fr-FR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function trimQty(n) {
  return Number(n).toFixed(6).replace(/\.?0+$/, '');
}

function qs(sel) { return document.querySelector(sel); }

function showBanner() { qs('#banner').classList.remove('hidden'); }
function hideBanner() { qs('#banner').classList.add('hidden'); }

// ─── Event listeners ──────────────────────────────────────────────

qs('main').addEventListener('click', e => {
  const card = e.target.closest('.card');
  if (card) openModal(+card.dataset.id);
});

qs('#btn-close').addEventListener('click', closeModal);

qs('#overlay').addEventListener('click', e => {
  if (e.target === qs('#overlay')) closeModal();
});

// ─── Boot ─────────────────────────────────────────────────────────

initWS();

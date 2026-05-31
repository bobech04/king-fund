'use strict';

// API base: check window.KING_API (config.js), then ?api= URL param, then relative /api
const _apiOverride = (typeof window.KING_API !== 'undefined' && window.KING_API)
  || new URLSearchParams(location.search).get('api');
const API    = _apiOverride ? _apiOverride.replace(/\/+$/, '') : '/api';
const _remoteMode = Boolean(_apiOverride);

const TARGET = 10_000;
const START  = 500;

// ── Division metadata ─────────────────────────────────────────────
const DIV_META = {
  'Investissement':  { color: '#ffd700', icon: '📈' },
  'Banque Centrale': { color: '#4488ff', icon: '🏛️' },
  'Expert Tech':     { color: '#00e5a0', icon: '💻' },
  'Expert Crypto':   { color: '#b44cff', icon: '₿'  },
  'Expert Commerce': { color: '#ff6b35', icon: '🛒' },
  'Morning Brief':   { color: '#ff4488', icon: '🌅' },
};
function divColor(d) { return (DIV_META[d] || {}).color || '#888'; }
function divIcon(d)  { return (DIV_META[d] || {}).icon  || '⚡';  }

// ── App state ─────────────────────────────────────────────────────
let state          = null;
let ws             = null;
let pollTimer      = null;
let modalChart     = null;
let divisionChart  = null;
let activeTraderId = null;
let activeTab      = 'classement';
let activeFilter   = null;

// Lazy-loaded panel data
let divisionsData    = null;
let divisionsLoaded  = false;
let briefLoaded      = false;
let postmarketLoaded = false;
let diplomeLoaded    = false;
let liquiditeLoaded  = false;
let _liqRefreshing   = false;

// ── Change detection state ────────────────────────────────────────
const prevTraderValues = new Map();  // id → value
const prevTraderRanks  = new Map();  // id → rank
const wonTraders       = new Set();  // ids already notified as winner
const milestones       = new Map();  // id → Set of milestone values reached
const MILESTONES       = [1_000, 2_500, 5_000]; // 2x, 5x, 10x of 500€

// ── Sparkline / chart data ────────────────────────────────────────
const sparklineData  = new Map();  // id → [value, ...]
const divisionHistory = new Map(); // divName → [avgValue, ...]
const MAX_HISTORY    = 60;         // keep last 60 ticks

// ── Notification state ────────────────────────────────────────────
const NOTIFS  = [];
let unread    = 0;
let notifOpen = false;

// ── Live clock ────────────────────────────────────────────────────
function startClock() {
  function tick() {
    const el = qs('#header-clock');
    if (el) el.textContent = new Date().toLocaleTimeString('fr-FR', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  }
  tick();
  setInterval(tick, 1000);
}

// ── WebSocket ─────────────────────────────────────────────────────
function _wsUrl() {
  if (_remoteMode) {
    // Construit l'URL WS depuis l'API remote (http→ws, https→wss)
    return API.replace(/^http/, 'ws').replace(/\/api\/?$/, '/ws');
  }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}/ws`;
}

function initWS() {
  ws = new WebSocket(_wsUrl());

  ws.onopen = () => {
    stopPolling();
    hideBanner();
    setWsDot('live');
    notify('🔌', 'CONNECTÉ', 'Flux temps réel établi.', 'var(--accent)');
  };
  ws.onclose = () => {
    showBanner();
    setWsDot('offline');
    startPolling();
    setTimeout(initWS, 5000);
    notify('⚠', 'DÉCONNECTÉ', 'Mode polling activé — reconnexion dans 5s.', 'var(--red)');
  };
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
function stopPolling() { clearInterval(pollTimer); pollTimer = null; }

async function fetchState() {
  try { applyState(await (await fetch(`${API}/state`)).json()); } catch {}
}

function setWsDot(cls) {
  const dot = qs('#ws-dot');
  dot.className = `ws-dot ${cls}`;
}

// ── State ─────────────────────────────────────────────────────────
function applyState(s) {
  const isFirstLoad = state === null;
  state = s;

  // Header stats
  qs('#battle-day').textContent = `J${s.battle_day} / 30`;
  const winners = s.leaderboard.filter(t => t.won).length;
  qs('#winners-count').textContent = winners > 0 ? `${winners} 👑` : '0';
  qs('#top-value').textContent = s.leaderboard[0]
    ? `€${fmt(s.leaderboard[0].value, 0)}`
    : '—';
  qs('#update-time').textContent = new Date().toLocaleTimeString('fr-FR', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });

  // Accumulate sparkline data per trader
  s.leaderboard.forEach(t => {
    if (!sparklineData.has(t.id)) sparklineData.set(t.id, []);
    const arr = sparklineData.get(t.id);
    arr.push(t.value);
    if (arr.length > MAX_HISTORY) arr.shift();
  });

  // Accumulate division history
  const divMap = {};
  s.leaderboard.forEach(t => {
    if (!divMap[t.division]) divMap[t.division] = [];
    divMap[t.division].push(t.value);
  });
  Object.entries(divMap).forEach(([div, values]) => {
    const avg = values.reduce((a, b) => a + b, 0) / values.length;
    if (!divisionHistory.has(div)) divisionHistory.set(div, []);
    const arr = divisionHistory.get(div);
    arr.push(avg);
    if (arr.length > MAX_HISTORY) arr.shift();
  });

  // Detect notable changes (skip on first load to avoid notification flood)
  if (!isFirstLoad) {
    s.leaderboard.forEach(t => {
      // New winner
      if (t.won && !wonTraders.has(t.id)) {
        wonTraders.add(t.id);
        notify('🏆', 'NOUVEAU WINNER !', `${t.name} atteint l'objectif de €10 000 !`, 'var(--gold)');
      }
      // Capital milestones
      if (!milestones.has(t.id)) milestones.set(t.id, new Set());
      const ms = milestones.get(t.id);
      MILESTONES.forEach(target => {
        if (!ms.has(target) && t.value >= target) {
          ms.add(target);
          const mult = (target / START).toFixed(0);
          notify('🚀', `${t.name}`, `Capital ×${mult} — atteint €${fmt(target, 0)} !`, divColor(t.division));
        }
      });
      // Rank jump ≥ 5
      const prev = prevTraderRanks.get(t.id);
      if (prev !== undefined && prev !== t.rank) {
        const delta = prev - t.rank; // positive = moved up
        if (delta >= 5) {
          notify('📈', `${t.name}`, `Remonte de ${delta} places ! Rang #${t.rank}`, 'var(--accent)');
        } else if (delta <= -5) {
          notify('📉', `${t.name}`, `Recule de ${Math.abs(delta)} places. Rang #${t.rank}`, 'var(--red)');
        }
      }
      prevTraderRanks.set(t.id, t.rank);
    });
  } else {
    // Seed won/ranks on first load without notifying
    s.leaderboard.forEach(t => {
      if (t.won) wonTraders.add(t.id);
      prevTraderRanks.set(t.id, t.rank);
      MILESTONES.forEach(target => {
        if (t.value >= target) {
          if (!milestones.has(t.id)) milestones.set(t.id, new Set());
          milestones.get(t.id).add(target);
        }
      });
    });
  }

  // Update ticker
  updateTicker(s.leaderboard);

  if (activeTab === 'classement') renderLeaderboard(s.leaderboard);
  if (activeTraderId !== null)    refreshModal();
  if (divisionsLoaded) loadDivisions(true);
  if (postmarketLoaded) loadPostMarket(true);
  if (activeTab === 'divisions') updateDivisionChart();
}

// ── Ticker tape ───────────────────────────────────────────────────
function updateTicker(traders) {
  const el = qs('#ticker-inner');
  if (!el) return;
  if (!traders || !traders.length) return;

  // Sort by |pnl_pct| to show biggest movers
  const sorted = [...traders].sort((a, b) => Math.abs(b.pnl_pct) - Math.abs(a.pnl_pct));
  const items  = sorted.slice(0, 12).map(t => {
    const sign = t.pnl >= 0 ? '+' : '';
    const cls  = t.pnl >= 0 ? 'ticker-up' : 'ticker-down';
    const arrow = t.pnl >= 0 ? '▲' : '▼';
    return `<span class="ticker-item">
      <span class="ticker-rank">#${t.rank}</span>
      <span class="ticker-name">${escHtml(t.name.split(' ').slice(0, 2).join(' '))}</span>
      <span class="${cls}">${arrow} ${sign}${t.pnl_pct}%</span>
    </span>`;
  }).join('');

  // Duplicate for seamless infinite loop
  el.innerHTML = items + items;
}

// ── Tab system ────────────────────────────────────────────────────
function switchTab(tab) {
  qsa('.tab-btn').forEach(b  => b.classList.toggle('active', b.dataset.tab === tab));
  qsa('.tab-pane').forEach(p => p.classList.toggle('hidden', p.id !== `tab-${tab}`));
  activeTab = tab;

  if (tab === 'classement' && state) renderLeaderboard(state.leaderboard);
  if (tab === 'divisions') { loadDivisions(); updateDivisionChart(); }
  if (tab === 'brief')               loadBrief();
  if (tab === 'postmarket')          loadPostMarket();
  if (tab === 'diplome')             loadDiplome();
  if (tab === 'liquidite')           loadLiquidite();
}

// ── Leaderboard ───────────────────────────────────────────────────
function renderLeaderboard(traders) {
  const container = qs('#leaderboard');
  const existing  = {};
  container.querySelectorAll('.card').forEach(el => { existing[el.dataset.id] = el; });

  traders.forEach(t => {
    let card   = existing[t.id];
    const isNew = !card;

    if (isNew) {
      card = document.createElement('div');
      card.dataset.id = t.id;
      card.addEventListener('click', () => openModal(+card.dataset.id));
    }

    const prevValue = prevTraderValues.get(t.id);
    const changed   = !isNew && prevValue !== undefined && prevValue !== t.value;
    const wentUp    = changed && t.value > prevValue;

    card.className = `card${t.won ? ' won' : ''}`;
    card.dataset.division = t.division || '';
    card.style.setProperty('--card-accent', divColor(t.division));
    card.innerHTML = cardHTML(t);
    container.appendChild(card);

    // Flash animation on value change
    if (changed) {
      requestAnimationFrame(() => {
        card.classList.remove('flash-up', 'flash-down');
        void card.offsetWidth; // force reflow
        card.classList.add(wentUp ? 'flash-up' : 'flash-down');
      });
    }

    prevTraderValues.set(t.id, t.value);
  });

  applyFilter();
}

// ── Sparkline SVG (inline, from accumulated data) ─────────────────
function makeSvgSparkline(values, color) {
  if (values.length < 3) return '';
  const W = 72, H = 26, PAD = 2;
  const min   = Math.min(...values);
  const max   = Math.max(...values);
  const range = max - min || 1;
  const pts   = values.map((v, i) => {
    const x = PAD + (i / (values.length - 1)) * (W - PAD * 2);
    const y = H - PAD - ((v - min) / range) * (H - PAD * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" fill="none">
    <polyline points="${pts}" stroke="${color}" stroke-width="1.5"
      stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

function cardHTML(t) {
  const pp       = pct(t.value);
  const sign     = t.pnl >= 0 ? '+' : '';
  const pnlCls   = t.pnl >= 0 ? 'green' : 'red';
  const fillCls  = t.won ? ' gold' : t.pnl < 0 ? ' red' : '';
  const dc       = divColor(t.division);
  const spkArr   = sparklineData.get(t.id) || [];
  const spkColor = t.pnl >= 0 ? '#00e5a0' : '#ff4466';
  const spkSvg   = makeSvgSparkline(spkArr, spkColor);

  return `
    <div class="card-top">
      <div class="card-rank">${rankIcon(t.rank)}</div>
      <div class="card-info">
        <div class="card-name">
          ${escHtml(t.name)}
          ${t.won ? '<span class="won-badge">WINNER</span>' : ''}
        </div>
        <div class="card-meta">
          <span class="card-strategy">${escHtml(t.strategy)}</span>
          <span class="div-chip" style="--chip-color:${dc}">${divIcon(t.division)} ${escHtml(t.division)}</span>
        </div>
      </div>
      <div class="card-right">
        ${spkSvg ? `<div class="card-sparkline">${spkSvg}</div>` : ''}
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

// ── Division filter ───────────────────────────────────────────────
function setFilter(divName) {
  activeFilter = (activeFilter === divName) ? null : divName;
  applyFilter();
}

function applyFilter() {
  const bar   = qs('#filter-bar');
  const badge = qs('#filter-badge');
  if (activeFilter) {
    const dc = divColor(activeFilter);
    badge.innerHTML =
      `<span class="div-chip" style="--chip-color:${dc}">${divIcon(activeFilter)} ${escHtml(activeFilter)}</span>`;
    bar.classList.remove('hidden');
  } else {
    bar.classList.add('hidden');
  }
  qsa('.card').forEach(c => {
    c.classList.toggle('filtered-out', !!activeFilter && c.dataset.division !== activeFilter);
  });
}

// ── Division performance chart ────────────────────────────────────
function updateDivisionChart() {
  const canvas = qs('#div-chart');
  if (!canvas) return;

  const wrap = canvas.parentElement;

  if (divisionHistory.size === 0) {
    if (!wrap.querySelector('.div-chart-empty')) {
      const msg = document.createElement('div');
      msg.className = 'div-chart-empty';
      msg.textContent = 'Accumulation des données…';
      wrap.appendChild(msg);
    }
    return;
  }

  // Remove placeholder if present
  const placeholder = wrap.querySelector('.div-chart-empty');
  if (placeholder) placeholder.remove();

  const maxLen   = Math.max(...Array.from(divisionHistory.values()).map(a => a.length));
  const labels   = Array.from({ length: maxLen }, (_, i) => i + 1);
  const datasets = Array.from(divisionHistory.entries()).map(([div, values]) => {
    const color = divColor(div);
    return {
      label: div,
      data: values,
      borderColor: color,
      backgroundColor: color + '12',
      borderWidth: 1.5,
      pointRadius: 0,
      fill: false,
      tension: 0.35,
    };
  });

  if (divisionChart) {
    divisionChart.data.labels   = labels;
    divisionChart.data.datasets = datasets;
    divisionChart.update('none');
    return;
  }

  const monoFont = { size: 9, family: "'JetBrains Mono', 'Courier New', monospace" };

  divisionChart = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: {
          display: true,
          labels: { color: '#52526a', font: monoFont, boxWidth: 10, padding: 10 },
        },
        tooltip: {
          mode: 'index',
          intersect: false,
          callbacks: { label: ctx => `${ctx.dataset.label}: €${ctx.parsed.y.toFixed(0)}` },
        },
      },
      scales: {
        x: { display: false },
        y: {
          ticks: { color: '#52526a', font: monoFont, callback: v => `€${v.toFixed(0)}` },
          grid:  { color: '#222230' },
        },
      },
    },
  });
}

// ── Divisions tab ─────────────────────────────────────────────────
async function loadDivisions(silent = false) {
  if (divisionsLoaded && !silent) return;
  try {
    divisionsData  = await (await fetch(`${API}/divisions`)).json();
    divisionsLoaded = true;
    renderDivisions(divisionsData);
  } catch {
    if (!silent)
      qs('#divisions-grid').innerHTML = '<div class="error-state" style="grid-column:1/-1">Impossible de charger les divisions.</div>';
  }
}

function renderDivisions(divs) {
  qs('#divisions-grid').innerHTML = divs.map(d => {
    const dc       = d.color || divColor(d.name);
    const ic       = d.icon  || divIcon(d.name);
    const pnlSign  = d.avg_pnl >= 0 ? '+' : '';
    const pnlCls   = d.avg_pnl >= 0 ? 'green' : 'red';
    const progress = pct(d.avg_value);
    const bestTxt  = d.best_trader
      ? `🥇 ${escHtml(d.best_trader.name)} · €${fmt(d.best_trader.value, 0)}`
      : '';
    return `
      <div class="division-card" style="--div-color:${dc}" data-div="${escHtml(d.name)}">
        <div class="div-card-header">
          <div class="div-card-icon">${ic}</div>
          <div class="div-card-count">${d.trader_count} trader${d.trader_count > 1 ? 's' : ''}</div>
        </div>
        <div class="div-card-name">${escHtml(d.name)}</div>
        <div class="div-card-value">€${fmt(d.avg_value, 0)}</div>
        <div class="div-card-pnl ${pnlCls}">${pnlSign}€${fmt(Math.abs(d.avg_pnl), 0)} (${pnlSign}${d.avg_pnl_pct.toFixed(1)}%)</div>
        <div class="div-progress-bg">
          <div class="div-progress-fill" style="width:${progress}%;background:${dc}"></div>
        </div>
        ${bestTxt ? `<div class="div-card-best">${bestTxt}</div>` : ''}
        ${d.wins > 0 ? `<div class="div-card-wins">👑 ${d.wins} winner${d.wins > 1 ? 's' : ''}</div>` : ''}
      </div>`;
  }).join('');

  qs('#divisions-grid').querySelectorAll('.division-card').forEach(card => {
    card.addEventListener('click', () => {
      switchTab('classement');
      setFilter(card.dataset.div);
    });
  });
}

// ── Morning Brief tab ─────────────────────────────────────────────
async function loadBrief() {
  if (briefLoaded) return;
  try {
    const brief = await (await fetch(`${API}/brief`)).json();
    briefLoaded = true;
    renderBrief(brief);
  } catch {
    qs('#brief-wrap').innerHTML = '<div class="error-state">Impossible de charger le Morning Brief.</div>';
  }
}

function renderBrief(brief) {
  const dir    = (brief.direction || 'neutral').toLowerCase();
  const conf   = Math.round((brief.confidence || 0.5) * 100);
  const emojis = { bullish: '📈', bearish: '📉', neutral: '➡️' };
  const labels = { bullish: 'HAUSSIER', bearish: 'BAISSIER', neutral: 'NEUTRE' };
  const today  = new Date().toLocaleDateString('fr-FR', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  });
  const isDemo = !brief.summary || brief.summary === 'API unavailable';

  qs('#brief-wrap').innerHTML = `
    <div class="brief-panel">
      <div class="brief-date">${today}</div>
      <div class="brief-title">MORNING BRIEF</div>

      <div class="brief-direction ${dir}">
        <div class="brief-dir-emoji">${emojis[dir] || '➡️'}</div>
        <div class="brief-dir-info">
          <div class="brief-dir-label ${dir}">${labels[dir] || dir.toUpperCase()}</div>
          <div class="brief-dir-conf">Conviction Claude</div>
        </div>
        <div class="brief-conf-pct" style="color:${dir === 'bullish' ? 'var(--accent)' : dir === 'bearish' ? 'var(--red)' : 'var(--muted)'}">
          ${conf}%
        </div>
      </div>

      <div class="brief-conf-bar">
        <div class="brief-conf-fill ${dir}" style="width:${conf}%"></div>
      </div>

      <div class="brief-summary-card">
        <div class="brief-summary-src">
          <div class="brief-summary-dot"></div>
          Claude · Analyse du marché
        </div>
        <p class="brief-summary-text">
          ${escHtml(brief.summary || 'Aucune analyse disponible.')}
        </p>
        ${isDemo ? `<p class="brief-no-key">Clé API Anthropic non configurée — brief de démonstration.</p>` : ''}
      </div>
    </div>`;
}

// ── Post-Market tab ───────────────────────────────────────────────
async function loadPostMarket(silent = false) {
  if (postmarketLoaded && !silent) return;
  try {
    const pm = await (await fetch(`${API}/post-market`)).json();
    postmarketLoaded = true;
    renderPostMarket(pm);
  } catch {
    if (!silent)
      qs('#postmarket-wrap').innerHTML = '<div class="error-state">Impossible de charger la revue post-marché.</div>';
  }
}

function renderPostMarket(pm) {
  const totalPnlSign = pm.total_pnl >= 0 ? '+' : '';
  const totalPnlCls  = pm.total_pnl >= 0 ? 'green' : 'red';

  const top5Html = (pm.top5 || []).map((t, i) => `
    <div class="pm-trader-row">
      <div class="pm-rank-num">${rankIcon(i + 1)}</div>
      <div class="pm-trader-name">
        ${escHtml(t.name)}
        <span class="div-chip" style="--chip-color:${divColor(t.division)};font-size:0.5rem;padding:0 4px">
          ${divIcon(t.division)}
        </span>
      </div>
      <div class="pm-trader-pnl ${t.pnl >= 0 ? 'green' : 'red'}">
        ${t.pnl >= 0 ? '+' : ''}€${fmt(Math.abs(t.pnl), 0)} (${t.pnl >= 0 ? '+' : ''}${t.pnl_pct}%)
      </div>
    </div>`).join('');

  const bottom5Html = (pm.bottom5 || []).map((t, i) => `
    <div class="pm-trader-row">
      <div class="pm-rank-num">#${30 - i}</div>
      <div class="pm-trader-name">
        ${escHtml(t.name)}
        <span class="div-chip" style="--chip-color:${divColor(t.division)};font-size:0.5rem;padding:0 4px">
          ${divIcon(t.division)}
        </span>
      </div>
      <div class="pm-trader-pnl red">
        ${t.pnl >= 0 ? '+' : ''}€${fmt(Math.abs(t.pnl), 0)} (${t.pnl_pct}%)
      </div>
    </div>`).join('');

  const divsHtml = (pm.divisions_ranked || []).map((d, i) => {
    const dc = d.color || divColor(d.name);
    return `
      <div class="div-rank-row">
        <div class="div-rank-pos">#${i + 1}</div>
        <div class="div-rank-icon" style="color:${dc}">${d.icon || divIcon(d.name)}</div>
        <div class="div-rank-name" style="color:${dc}">${escHtml(d.name)}</div>
        <div class="div-rank-val ${d.avg_pnl >= 0 ? 'green' : 'red'}">
          ${d.avg_pnl >= 0 ? '+' : ''}${d.avg_pnl_pct.toFixed(1)}%
        </div>
      </div>`;
  }).join('');

  qs('#postmarket-wrap').innerHTML = `
    <div class="postmarket-panel">
      <div class="pm-header">
        <div class="pm-title">REVUE DU MARCHÉ</div>
        <div class="pm-day-badge">Jour ${pm.battle_day} / 30</div>
      </div>

      <div class="pm-kpis">
        <div class="pm-kpi">
          <div class="pm-kpi-val">€${fmt(pm.avg_value, 0)}</div>
          <div class="pm-kpi-lbl">Moyenne</div>
        </div>
        <div class="pm-kpi">
          <div class="pm-kpi-val ${totalPnlCls}">${totalPnlSign}€${fmt(Math.abs(pm.total_pnl), 0)}</div>
          <div class="pm-kpi-lbl">P&L Total</div>
        </div>
        <div class="pm-kpi">
          <div class="pm-kpi-val green">€${fmt(pm.max_value, 0)}</div>
          <div class="pm-kpi-lbl">Meilleur</div>
        </div>
        <div class="pm-kpi">
          <div class="pm-kpi-val red">€${fmt(pm.min_value, 0)}</div>
          <div class="pm-kpi-lbl">Pire</div>
        </div>
      </div>

      <div class="pm-section">
        <div class="pm-section-title">Top 5 Performers</div>
        ${top5Html}
      </div>

      <div class="pm-section">
        <div class="pm-section-title">Bottom 5</div>
        ${bottom5Html}
      </div>

      <div class="pm-section">
        <div class="pm-section-title">Classement des Divisions</div>
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:4px 12px">
          ${divsHtml}
        </div>
      </div>

    </div>`;
}

// ── Diplôme tab ───────────────────────────────────────────────────
async function loadDiplome() {
  if (diplomeLoaded) return;
  try {
    const agent = await (await fetch(`${API}/weekly-agent`)).json();
    diplomeLoaded = true;
    renderDiplome(agent);
  } catch {
    qs('#diplome-wrap').innerHTML = '<div class="error-state">Impossible de charger le diplôme.</div>';
  }
}

function renderDiplome(agent) {
  const dc      = divColor(agent.division);
  const ic      = divIcon(agent.division);
  const pnlSign = agent.pnl >= 0 ? '+' : '';
  const pnlCls  = agent.pnl >= 0 ? 'green' : 'red';
  const podiumHtml = buildPodiumHtml();

  qs('#diplome-wrap').innerHTML = `
    <div class="diplome-panel">

      <div class="diploma">
        <div class="diploma-corner tl"></div>
        <div class="diploma-corner tr"></div>
        <div class="diploma-corner bl"></div>
        <div class="diploma-corner br"></div>

        <div class="diploma-ornament top">✦ &nbsp; ✦ &nbsp; ✦</div>

        <div class="diploma-crown">👑</div>
        <div class="diploma-cert-label">Certificat d'excellence</div>
        <div class="diploma-title">KING FUND</div>
        <div class="diploma-subtitle">AGENT DE LA SEMAINE · S${agent.week}</div>

        <div class="diploma-divider"></div>

        <div class="diploma-presents">Ce certificat est décerné à</div>
        <div class="diploma-agent-name">${escHtml(agent.name)}</div>
        <div class="diploma-div-pill" style="color:${dc};border-color:${dc};background:color-mix(in srgb,${dc} 10%,transparent)">
          ${ic} ${escHtml(agent.division)}
        </div>
        <div class="diploma-strategy">${escHtml(agent.strategy)}</div>

        <div class="diploma-divider"></div>

        <div class="diploma-stats">
          <div class="diploma-stat">
            <div class="diploma-stat-val">€${fmt(agent.value, 0)}</div>
            <div class="diploma-stat-lbl">Valeur</div>
          </div>
          <div class="diploma-stat">
            <div class="diploma-stat-val ${pnlCls}">${pnlSign}${agent.pnl_pct.toFixed(1)}%</div>
            <div class="diploma-stat-lbl">P&L Total</div>
          </div>
          <div class="diploma-stat">
            <div class="diploma-stat-val ${agent.weekly_gain >= 0 ? '' : 'red'}">
              ${agent.weekly_gain >= 0 ? '+' : ''}€${fmt(Math.abs(agent.weekly_gain), 0)}
            </div>
            <div class="diploma-stat-lbl">Gain Semaine</div>
          </div>
          <div class="diploma-stat">
            <div class="diploma-stat-val">${agent.trade_count}</div>
            <div class="diploma-stat-lbl">Trades</div>
          </div>
        </div>

        <div class="diploma-ornament bottom">✦ &nbsp; ✦ &nbsp; ✦</div>
      </div>

      ${podiumHtml}

    </div>`;
}

function buildPodiumHtml() {
  if (!state || !state.leaderboard) return '';
  const top3 = state.leaderboard.slice(0, 3);
  const rows = top3.map(t => `
    <div class="podium-row">
      <div class="podium-rank">${rankIcon(t.rank)}</div>
      <div class="podium-name">${escHtml(t.name)}</div>
      <div class="podium-value">€${fmt(t.value, 0)}</div>
    </div>`).join('');
  return `
    <div class="podium-section">
      <div class="podium-label">Podium actuel</div>
      ${rows}
    </div>`;
}

// ── Trader modal ──────────────────────────────────────────────────
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

  qs('#modal-name').textContent       = data.name;
  qs('#modal-strategy').textContent   = data.strategy;
  qs('#modal-rank-badge').textContent = ts
    ? (ts.rank <= 3 ? rankIcon(ts.rank) : `#${ts.rank}`)
    : '';

  const div = ts?.division || '';
  const dc  = divColor(div);
  qs('#modal-div-row').innerHTML = div
    ? `<span class="div-chip" style="--chip-color:${dc}">${divIcon(div)} ${escHtml(div)}</span>`
    : '';

  qs('#modal-value').textContent = `€${fmt(data.value, 2)}`;
  qs('#modal-pnl').innerHTML =
    `<span class="${cls}">${sign}€${fmt(Math.abs(pnl), 2)} (${sign}${((pnl / START) * 100).toFixed(2)}%)</span>`;

  const pp   = pct(data.value);
  const fill = qs('#modal-progress');
  fill.style.width = `${pp}%`;
  fill.className   = `progress-fill${data.value >= TARGET ? ' gold' : pnl < 0 ? ' red' : ''}`;
  qs('#modal-progress-pct').textContent = `${pp.toFixed(1)}%`;

  renderChart(data.history || []);
  renderPositions(data.positions || {}, data.cash ?? 0);
  renderTrades(data.trades || []);
}

// ── Chart (modal) ─────────────────────────────────────────────────
function renderChart(history) {
  if (modalChart) { modalChart.destroy(); modalChart = null; }
  if (history.length < 2) return;

  const labels = history.map(h => h.timestamp.slice(11, 16));
  const values = history.map(h => h.portfolio_value);
  const isUp   = values.at(-1) >= values[0];
  const color  = isUp ? '#00e5a0' : '#ff4466';
  const monoFont = { size: 10, family: "'JetBrains Mono', 'Courier New', monospace" };

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
          ticks: { color: '#52526a', maxTicksLimit: 6, font: monoFont },
          grid:  { color: '#222230' },
        },
        y: {
          ticks: { color: '#52526a', font: monoFont, callback: v => `€${v.toFixed(0)}` },
          grid:  { color: '#222230' },
        },
      },
    },
  });
}

// ── Positions ─────────────────────────────────────────────────────
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

// ── Trades ────────────────────────────────────────────────────────
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

// ── Notification system ───────────────────────────────────────────
function notify(icon, title, body, accent) {
  const notif = { icon, title, body, accent, ts: new Date() };
  NOTIFS.unshift(notif);
  if (NOTIFS.length > 50) NOTIFS.pop();
  unread++;
  updateBellBadge();
  showToast(notif);
  if (notifOpen) renderNotifList();
}

function updateBellBadge() {
  const badge = qs('#bell-badge');
  if (!badge) return;
  if (unread > 0) {
    badge.textContent = unread > 99 ? '99+' : String(unread);
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }
}

function showToast(n) {
  const container = qs('#toast-container');
  const el = document.createElement('div');
  el.className = 'toast';
  el.style.setProperty('--toast-accent', n.accent || 'var(--accent)');
  el.innerHTML = `
    <div class="toast-icon">${n.icon}</div>
    <div class="toast-body">
      <div class="toast-title">${escHtml(n.title)}</div>
      <div class="toast-msg">${escHtml(n.body)}</div>
    </div>
    <button class="toast-close" aria-label="Fermer">✕</button>`;
  el.querySelector('.toast-close').addEventListener('click', () => dismissToast(el));
  container.appendChild(el);
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add('toast-visible')));
  setTimeout(() => dismissToast(el), 5500);
}

function dismissToast(el) {
  el.classList.remove('toast-visible');
  el.addEventListener('transitionend', () => el.remove(), { once: true });
}

function renderNotifList() {
  const list = qs('#notif-list');
  if (!list) return;
  if (!NOTIFS.length) {
    list.innerHTML = '<div class="notif-empty">Aucune alerte</div>';
    return;
  }
  list.innerHTML = NOTIFS.map(n => `
    <div class="notif-item">
      <div class="notif-item-icon">${n.icon}</div>
      <div class="notif-item-body">
        <div class="notif-item-title">${escHtml(n.title)}</div>
        <div class="notif-item-msg">${escHtml(n.body)}</div>
        <div class="notif-item-ts">${n.ts.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</div>
      </div>
    </div>`).join('');
}

function toggleNotifPanel() {
  const panel = qs('#notif-panel');
  notifOpen = !notifOpen;
  panel.classList.toggle('open', notifOpen);
  if (notifOpen) {
    unread = 0;
    updateBellBadge();
    renderNotifList();
  }
}

// ── Liquidité tab ─────────────────────────────────────────────────
async function loadLiquidite(silent = false) {
  if (liquiditeLoaded && !silent) return;
  try {
    const data = await (await fetch(`${API}/liquidite`)).json();
    liquiditeLoaded = true;
    renderLiquidite(data);
  } catch {
    if (!silent)
      qs('#liquidite-wrap').innerHTML = '<div class="error-state">Impossible de charger le score de liquidité.</div>';
  }
}

function renderLiquidite(d) {
  const score    = d.global_liquidity_score;
  const regime   = (d.regime || 'neutre').toLowerCase();
  const hasScore = score !== null && score !== undefined;

  const regimeLabel = {
    critique: 'CRITIQUE', tendu: 'TENDU', neutre: 'NEUTRE', ample: 'AMPLE', abondant: 'ABONDANT',
  };
  const scoreColor = !hasScore         ? '#52526a'
    : score < 3                        ? '#ff4466'
    : score < 5                        ? '#ff9944'
    : score < 6.5                      ? '#aaaacc'
    : score < 8                        ? '#00e5a0'
    :                                    '#ffd700';

  const biasVal  = hasScore ? (score - 5) / 5 : 0;
  const biasStr  = (biasVal >= 0 ? '+' : '') + biasVal.toFixed(2);
  const biasDesc = biasVal > 0.3  ? 'Risk-ON — positions élargies'
    : biasVal < -0.3              ? 'Risk-OFF — positions réduites'
    :                               'Neutre — taille normale';
  const gaugeW   = hasScore ? Math.min(100, score / 10 * 100).toFixed(1) : 0;

  const agentsHtml = Object.entries(d.agent_scores || {}).map(([agent, sc]) => {
    const agColor = sc < 3 ? '#ff4466' : sc < 5 ? '#ff9944' : sc < 6.5 ? '#aaaacc' : sc < 8 ? '#00e5a0' : '#ffd700';
    const agW     = (sc / 10 * 100).toFixed(1);
    const summary = escHtml((d.agent_summaries || {})[agent] || '');
    return `
      <div class="liq-agent-row" title="${summary}">
        <div class="liq-agent-name">${escHtml(agent.replace(/_/g, ' '))}</div>
        <div class="liq-agent-bar-bg">
          <div class="liq-agent-bar-fill" style="width:${agW}%;background:${agColor}"></div>
        </div>
        <div class="liq-agent-score" style="color:${agColor}">${Number(sc).toFixed(1)}</div>
      </div>`;
  }).join('');

  const alertsHtml = (d.alerts || []).map(a => {
    const cls = a.startsWith('ALERTE') ? 'liq-alert-critique' : 'liq-alert-signal';
    return `<div class="liq-alert ${cls}">${escHtml(a)}</div>`;
  }).join('');

  const errorsHtml = (d.errors || []).map(e =>
    `<div class="liq-alert liq-alert-warn">${escHtml(e)}</div>`
  ).join('');

  const ts = d.timestamp
    ? new Date(d.timestamp + (d.timestamp.endsWith('Z') ? '' : 'Z'))
        .toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : '—';

  qs('#liquidite-wrap').innerHTML = `
    <div class="liq-panel">

      <div class="liq-score-card">
        <div class="liq-score-label">SCORE LIQUIDITÉ GLOBAL</div>
        <div class="liq-score-num" style="color:${scoreColor}">${hasScore ? Number(score).toFixed(1) : '—'}</div>
        <div class="liq-score-label">/ 10</div>
        <div class="liq-regime regime-${regime}">${regimeLabel[regime] || regime.toUpperCase()}</div>
        <div class="liq-gauge-wrap">
          <div class="liq-gauge">
            <div class="liq-gauge-fill" style="width:${gaugeW}%;background:${scoreColor}"></div>
          </div>
        </div>
        <div class="liq-trader-impact">
          Biais traders :
          <span style="color:${scoreColor};font-weight:700">${biasStr}</span>
          &nbsp;·&nbsp;${biasDesc}
        </div>
      </div>

      ${agentsHtml ? `
      <div class="liq-card">
        <div class="liq-section-title">Scores par agent (7 sources)</div>
        <div class="liq-agents">${agentsHtml}</div>
      </div>` : ''}

      ${alertsHtml ? `
      <div class="liq-card">
        <div class="liq-section-title">Alertes &amp; Signaux</div>
        <div class="liq-alerts">${alertsHtml}</div>
      </div>` : ''}

      ${errorsHtml ? `
      <div class="liq-card">
        <div class="liq-section-title" style="color:#ff9944">Erreurs agents</div>
        <div class="liq-alerts">${errorsHtml}</div>
      </div>` : ''}

      <div class="liq-timestamp">Données: ${ts}</div>

      <button class="liq-refresh-btn" id="liq-refresh-btn">↻ Actualiser le score liquidité</button>

    </div>`;

  qs('#liq-refresh-btn').addEventListener('click', async () => {
    if (_liqRefreshing) return;
    _liqRefreshing = true;
    const btn = qs('#liq-refresh-btn');
    btn.textContent = '⌛ Refresh en cours…';
    btn.disabled = true;
    try {
      await fetch(`${API}/liquidite/refresh`, { method: 'POST' });
      await new Promise(r => setTimeout(r, 4000));
      liquiditeLoaded = false;
      await loadLiquidite();
    } catch { /* silently fail */ }
    finally {
      _liqRefreshing = false;
      const b = qs('#liq-refresh-btn');
      if (b) { b.textContent = '↻ Actualiser le score liquidité'; b.disabled = false; }
    }
  });
}

// ── Helpers ───────────────────────────────────────────────────────
function pct(value) {
  return Math.min(100, Math.max(0, (value - START) / (TARGET - START) * 100));
}
function fmt(n, decimals) {
  return Number(n).toLocaleString('fr-FR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}
function trimQty(n) { return Number(n).toFixed(6).replace(/\.?0+$/, ''); }
function qs(sel)    { return document.querySelector(sel); }
function qsa(sel)   { return document.querySelectorAll(sel); }
function escHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function showBanner() { qs('#banner').classList.remove('hidden'); }
function hideBanner() { qs('#banner').classList.add('hidden'); }

// ── Event listeners ───────────────────────────────────────────────
qs('#btn-close').addEventListener('click', closeModal);
qs('#overlay').addEventListener('click', e => {
  if (e.target === qs('#overlay')) closeModal();
});

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

qs('#filter-clear').addEventListener('click', () => {
  activeFilter = null;
  applyFilter();
});

qs('#bell-btn').addEventListener('click', e => {
  e.stopPropagation();
  toggleNotifPanel();
});

document.addEventListener('click', e => {
  if (notifOpen && !qs('#notif-panel').contains(e.target) && e.target !== qs('#bell-btn')) {
    notifOpen = false;
    qs('#notif-panel').classList.remove('open');
  }
});

qs('#notif-clear-btn').addEventListener('click', () => {
  NOTIFS.length = 0;
  renderNotifList();
});

// ── Boot ──────────────────────────────────────────────────────────
startClock();
initWS();
startPolling();

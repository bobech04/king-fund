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
let diplomeLoaded           = false;
let investissementLoaded    = false;
let patrimoineLoaded        = false;
let liquiditeLoaded         = false;
let _liqRefreshing   = false;
let _patrimoineCharts       = {};   // {evolution: Chart, camembert: Chart, projection: Chart}

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

  // Bertez mode badge (stats bar — visible sur tous les onglets)
  const bEl = qs('#bertez-mode-val');
  if (bEl) {
    const bm = s.bertez_mode;
    const abbr = { DEFENSIF: 'DEF', NEUTRE: 'NEU', OFFENSIF: 'OFF' };
    bEl.textContent = abbr[bm] || '—';
    bEl.className = 'stat-value ' + (
      bm === 'DEFENSIF' ? 'red' :
      bm === 'OFFENSIF' ? 'green' :
      'muted'
    );
  }

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
  if (tab === 'investissement')      loadInvestissement();
  if (tab === 'patrimoine')          loadPatrimoine();
  if (tab === 'liquidite')           loadLiquidite();
  if (tab === 'gerant-delegue')      loadGerantDelegue();
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

function sitgClass(budget) {
  if (budget > 1.05) return 'sitg-bull';
  if (budget < 0.95) return 'sitg-bear';
  return 'sitg-neut';
}

function sitgLabel(budget) {
  const arrow = budget > 1.05 ? '▲' : budget < 0.95 ? '▼' : '—';
  return `${arrow} ×${budget.toFixed(2)}`;
}

const GRADE_META = {
  'RECRUE':  { cls: 'grade-recrue',  icon: '⚔️' },
  'JUNIOR':  { cls: 'grade-junior',  icon: '🔰' },
  'SENIOR':  { cls: 'grade-senior',  icon: '⭐' },
  'ELITE':   { cls: 'grade-elite',   icon: '💎' },
  'LÉGENDE': { cls: 'grade-legende', icon: '👑' },
};

function gradeClass(grade) {
  return GRADE_META[grade]?.cls || 'grade-recrue';
}

function gradeLabel(grade) {
  const m = GRADE_META[grade];
  return m ? `${m.icon} ${grade}` : grade || 'RECRUE';
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
  const sitg     = t.sitg_budget ?? 1.0;
  const grade    = t.grade || 'RECRUE';

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
        <div class="grade-pill ${gradeClass(grade)}">${gradeLabel(grade)}</div>
        <div class="sitg-pill ${sitgClass(sitg)}">${sitgLabel(sitg)}</div>
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
  const datasets = Array.from(divisionHistory.entries()).filter(([div]) => div !== 'Morning Brief').map(([div, values]) => {
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
  qs('#divisions-grid').innerHTML = divs.filter(d => d.name !== 'Morning Brief').map(d => {
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

  const sitg  = data.sitg_budget ?? ts?.sitg_budget ?? 1.0;
  const grade = data.grade ?? ts?.grade ?? 'RECRUE';
  qs('#modal-sitg-value').innerHTML =
    `<span class="${sitgClass(sitg)}">${sitgLabel(sitg)}</span>`;
  qs('#modal-grade-value').innerHTML =
    `<span class="${gradeClass(grade)}">${gradeLabel(grade)}</span>`;

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

// ── Investissement tab ────────────────────────────────────────────
async function loadInvestissement(silent = false) {
  if (investissementLoaded && !silent) return;
  const wrap = qs('#investissement-wrap');
  wrap.innerHTML = '<div class="loading-state">Analyse pipeline 17 étapes en cours…</div>';
  try {
    const [wlRes, thRes] = await Promise.allSettled([
      fetch(`${API}/investissement/watchlist`).then(r => r.json()),
      fetch(`${API}/investissement/theses`).then(r => r.json()),
    ]);
    const watchlist = wlRes.status === 'fulfilled' ? (wlRes.value.watchlist || []) : [];
    const theses    = thRes.status === 'fulfilled' ? (thRes.value.theses   || {}) : {};
    investissementLoaded = true;
    renderInvestissement(watchlist, theses);
  } catch {
    wrap.innerHTML = '<div class="error-state">Impossible de charger les analyses investissement.</div>';
  }
}

function renderInvestissement(watchlist, theses) {
  const nbBuy  = watchlist.filter(a => a.signal === 'BUY').length;
  const nbHold = watchlist.filter(a => a.signal === 'HOLD').length;
  const nbSell = watchlist.filter(a => a.signal === 'SELL').length;
  const scores = watchlist.map(a => a.score).filter(s => s != null);
  const avgScore = scores.length ? (scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1) : '—';

  const sigBadge = (sig) => {
    if (sig === 'BUY')  return '<span style="background:#1a3a1a;color:#4ade80;font-weight:700;padding:2px 9px;border-radius:4px;font-size:11px">BUY</span>';
    if (sig === 'SELL') return '<span style="background:#3a1a1a;color:#f87171;font-weight:700;padding:2px 9px;border-radius:4px;font-size:11px">SELL</span>';
    return '<span style="background:#2a2a14;color:#facc15;font-weight:700;padding:2px 9px;border-radius:4px;font-size:11px">HOLD</span>';
  };

  let rows = '';
  for (const a of watchlist) {
    if (a.erreur) {
      rows += `<tr>
        <td><strong>${a.ticker}</strong></td>
        <td style="font-size:11px">${a.nom}</td>
        <td style="font-size:10px;opacity:.6">${a.bourse}</td>
        <td colspan="8" style="color:#f87171;font-size:11px">${a.erreur}</td>
      </tr>`;
      continue;
    }
    const score   = a.score != null ? a.score.toFixed(1) : '—';
    const scoreCl = a.score == null ? '' : a.score >= 7 ? 'style="color:#4ade80;font-weight:700"' : a.score >= 4 ? '' : 'style="color:#f87171"';
    const marge   = a.marge_securite;
    const margeFmt = marge != null ? (marge * 100).toFixed(1) + '%' : '—';
    const margeCl  = marge == null ? '' : marge >= 0.20 ? 'style="color:#4ade80"' : marge >= 0 ? '' : 'style="color:#f87171"';
    const these    = theses[a.ticker] || '';
    const theseHtml = these
      ? `<span title="${these.replace(/"/g,'&quot;')}" style="font-size:11px;opacity:.75;cursor:help">${these.length > 85 ? these.slice(0,83)+'…' : these}</span>`
      : '<span style="opacity:.35;font-size:10px">—</span>';

    rows += `<tr>
      <td><strong>${a.ticker}</strong></td>
      <td style="font-size:11px">${a.nom}</td>
      <td style="font-size:10px;opacity:.6">${a.bourse}</td>
      <td ${scoreCl}>${score}/10</td>
      <td ${margeCl}>${margeFmt}</td>
      <td>${sigBadge(a.signal)}</td>
      <td style="font-size:11px">${a.prix_actuel != null ? a.prix_actuel.toLocaleString('fr-FR',{maximumFractionDigits:2}) : '—'}</td>
      <td style="font-size:11px">${a.per != null ? a.per.toFixed(1) : '—'}</td>
      <td style="font-size:11px">${a.pbr != null ? a.pbr.toFixed(2) : '—'}</td>
      <td>${theseHtml}</td>
    </tr>`;
  }

  qs('#investissement-wrap').innerHTML = `
    <div class="kpi-row" style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px">
      <div class="kpi-card" style="flex:1;min-width:110px;background:var(--surface,#1e1e2e);border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:11px;opacity:.6;margin-bottom:4px">Analysés</div>
        <div style="font-size:24px;font-weight:700">${watchlist.length}</div>
        <div style="font-size:10px;opacity:.5">13 titres</div>
      </div>
      <div class="kpi-card" style="flex:1;min-width:110px;background:#0d2010;border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:11px;opacity:.6;margin-bottom:4px">BUY</div>
        <div style="font-size:24px;font-weight:700;color:#4ade80">${nbBuy}</div>
        <div style="font-size:10px;opacity:.5">Achat recommandé</div>
      </div>
      <div class="kpi-card" style="flex:1;min-width:110px;background:#1e1e10;border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:11px;opacity:.6;margin-bottom:4px">HOLD</div>
        <div style="font-size:24px;font-weight:700;color:#facc15">${nbHold}</div>
        <div style="font-size:10px;opacity:.5">À surveiller</div>
      </div>
      <div class="kpi-card" style="flex:1;min-width:110px;background:#200d0d;border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:11px;opacity:.6;margin-bottom:4px">SELL</div>
        <div style="font-size:24px;font-weight:700;color:#f87171">${nbSell}</div>
        <div style="font-size:10px;opacity:.5">Éviter / Vendre</div>
      </div>
      <div class="kpi-card" style="flex:1;min-width:110px;background:var(--surface,#1e1e2e);border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:11px;opacity:.6;margin-bottom:4px">Score Moyen</div>
        <div style="font-size:24px;font-weight:700">${avgScore}</div>
        <div style="font-size:10px;opacity:.5">sur 10</div>
      </div>
    </div>

    <div style="overflow-x:auto">
      <table class="data-table" style="width:100%;border-collapse:collapse">
        <thead><tr>
          <th>Ticker</th><th>Nom</th><th>Bourse</th>
          <th>Score /10</th><th>Marge Sécu.</th><th>Signal</th>
          <th>Prix</th><th>PER</th><th>PBR</th>
          <th style="min-width:200px">Thèse d'investissement</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>

    <div style="font-size:10px;opacity:.4;margin-top:12px;text-align:right">
      Analyse pipeline 17 étapes · Graham · Buffett · Damodaran · Thèse Claude API
    </div>`;
}

// ── Patrimoine tab ────────────────────────────────────────────────
async function loadPatrimoine(silent = false) {
  if (patrimoineLoaded && !silent) return;
  try {
    const d = await (await fetch(`${API}/patrimoine`)).json();
    patrimoineLoaded = true;
    renderPatrimoine(d);
  } catch {
    if (!silent)
      qs('#patrimoine-wrap').innerHTML = '<div class="error-state">Impossible de charger le patrimoine.</div>';
  }
}

function renderPatrimoine(d) {
  const actifs   = d.actifs || [];
  const total    = d.total_eur || 0;
  const proj     = d.projection || [];
  const apports  = d.apports || [];
  const cfg      = d.config || {};
  const fisc     = d.fiscalite || {};
  const fscFra   = fisc.fsc_fra_01 || {};

  // ── KPI row ────────────────────────────────────────────────────
  const valRetraite = d.valeur_retraite || 0;
  const anneeRet    = cfg.annee_base + (cfg.age_retraite - cfg.age_actuel);
  const apportMens  = d.apport_mensuel_effectif || cfg.apport_mensuel || 500;
  const apport12m   = d.apports_cumules_12m || 0;

  // ── Camembert data (actifs > 0 seulement) ─────────────────────
  const actifsPie = actifs.filter(a => a.valeur_eur > 0);
  const pieLabels = actifsPie.map(a => a.nom);
  const pieValues = actifsPie.map(a => a.valeur_eur);
  const pieColors = actifsPie.map(a => a.couleur);

  // ── Projection data ────────────────────────────────────────────
  const projLabels   = proj.map(p => p.annee);
  const projTotal    = proj.map(p => p.valeur);
  const projGrowth   = proj.map(p => p.croissance);
  const projApports  = proj.map(p => p.apports_cumules);

  // ── Apports history table ──────────────────────────────────────
  const apportsHtml = apports.length === 0
    ? '<div style="color:var(--muted);font-size:.78rem;text-align:center;padding:20px">Aucun apport enregistré</div>'
    : apports.slice(0, 10).map(a => `
        <div class="pat-apport-row">
          <span class="pat-apport-date">${a.date || '—'}</span>
          <span class="pat-apport-note">${escHtml(a.note || 'Apport')}</span>
          <span class="pat-apport-montant">+${fmt(a.montant, 0)} €</span>
        </div>`).join('');

  // ── Or tax details ─────────────────────────────────────────────
  const orFisc  = fscFra.or || {};
  const orA     = orFisc.option_A || {};
  const orB     = orFisc.option_B || {};
  const stFisc  = fscFra.stellantis || {};
  const peaFisc = fisc.pea  || {};
  const immoFisc = fisc.immo || {};
  const immoRP   = immoFisc.residence_principale || {};
  const immoLoc  = immoFisc.locatif || {};
  const immoIfi  = immoFisc.ifi || {};
  const immoType = immoFisc.type || 'residence_principale';
  const immoVal  = immoFisc.valeur || 0;
  const immoNet  = immoFisc.valeur_nette || 0;
  const peaVal   = peaFisc.valeur || 0;
  const peaActif = actifs.find(a => a.id === 'pea') || {};
  const immoActif = actifs.find(a => a.id === 'immo') || {};

  qs('#patrimoine-wrap').innerHTML = `
  <div class="pat-panel">

    <!-- KPI row -->
    <div class="pat-kpi-row">
      <div class="pat-kpi">
        <div class="pat-kpi-label">PATRIMOINE TOTAL</div>
        <div class="pat-kpi-val" style="color:var(--accent)">${fmt(total, 0)} €</div>
      </div>
      <div class="pat-kpi">
        <div class="pat-kpi-label">OBJECTIF RETRAITE ${cfg.age_retraite || 56} ANS</div>
        <div class="pat-kpi-val" style="color:var(--gold)">${fmt(valRetraite, 0)} €</div>
        <div class="pat-kpi-sub">${anneeRet}</div>
      </div>
      <div class="pat-kpi">
        <div class="pat-kpi-label">APPORT MOYEN</div>
        <div class="pat-kpi-val">${fmt(apportMens, 0)} €<span style="font-size:.65rem;color:var(--muted)">/mois</span></div>
      </div>
      <div class="pat-kpi">
        <div class="pat-kpi-label">APPORTS 12M</div>
        <div class="pat-kpi-val">${fmt(apport12m, 0)} €</div>
      </div>
    </div>

    <!-- Graphique + Camembert -->
    <div class="pat-charts-row">
      <div class="pat-card" style="flex:1;min-width:0">
        <div class="pat-card-title">📈 Projection vers la retraite (${cfg.taux_annuel * 100 || 10}%/an)</div>
        <div style="position:relative;height:220px">
          <canvas id="pat-proj-chart"></canvas>
        </div>
      </div>
      <div class="pat-card" style="width:220px;flex-shrink:0">
        <div class="pat-card-title">🥧 Répartition patrimoine</div>
        <div style="position:relative;height:220px;display:flex;align-items:center;justify-content:center">
          <canvas id="pat-pie-chart"></canvas>
        </div>
      </div>
    </div>

    <!-- Apports -->
    <div class="pat-card">
      <div class="pat-card-header">
        <div class="pat-card-title">💰 Suivi des apports mensuels</div>
        <button class="pat-btn-add" id="pat-add-apport-btn">＋ Ajouter un apport</button>
      </div>
      <div class="pat-apports-list">${apportsHtml}</div>
    </div>

    <!-- Fiscalité FSC-FRA-01 -->
    <div class="pat-card">
      <div class="pat-fisc-header" onclick="this.nextElementSibling.classList.toggle('hidden')">
        <div class="pat-card-title">🇫🇷 FSC-FRA-01 — Flat Tax (PFU 30%)</div>
        <span class="pat-fisc-toggle">▼</span>
      </div>
      <div class="pat-fisc-body">
        <div class="pat-fisc-ref">${escHtml(fscFra.reference || '')}</div>
        <div class="pat-fisc-taux">${escHtml(fscFra.taux || '30% = 12.8% IR + 17.2% PS')}</div>

        <div class="pat-fisc-section">
          <div class="pat-fisc-actif">🥇 ${escHtml((orFisc.actif || 'Or physique'))}</div>
          <div class="pat-fisc-option">
            <span class="pat-fisc-badge">Option A</span>
            <span>${escHtml(orA.nom || '')} — <strong>${fmt(orA.impot || 0, 2)} €</strong></span>
            <div class="pat-fisc-detail">${escHtml(orA.detail || '')}</div>
          </div>
          <div class="pat-fisc-option">
            <span class="pat-fisc-badge ${orB.exonere ? 'exonere' : ''}">Option B</span>
            <span>${escHtml(orB.nom || '')}
              ${orB.exonere ? '→ <strong style="color:var(--accent)">EXONÉRÉ</strong>' : `— abattement ${escHtml(orB.abattement_acquis || '')} acquis`}
            </span>
            <div class="pat-fisc-detail">${escHtml(orB.detail || '')}</div>
          </div>
          <div class="pat-fisc-conseil">${escHtml(orFisc.conseil || '')}</div>
        </div>

        <div class="pat-fisc-section">
          <div class="pat-fisc-actif">🚗 ${escHtml(stFisc.actif || 'Stellantis')}</div>
          <div class="pat-fisc-option">
            Dividendes estimés : <strong>${fmt(stFisc.dividendes_estimes || 0, 2)} €/an</strong>
            → PFU : <strong>${fmt(stFisc.pfu_annuel || 0, 2)} €/an</strong>
          </div>
          <div class="pat-fisc-detail">${escHtml(stFisc.detail || '')}</div>
          <div class="pat-fisc-conseil">${escHtml(stFisc.conseil || '')}</div>
        </div>

        <div class="pat-fisc-section">
          <div class="pat-fisc-actif">💵 ${escHtml((fscFra.cash || {}).actif || 'Cash')}</div>
          <div class="pat-fisc-detail">${escHtml((fscFra.cash || {}).detail || '')}</div>
        </div>
      </div>
    </div>

    <!-- PEA -->
    <div class="pat-card">
      <div class="pat-fisc-header" onclick="this.nextElementSibling.classList.toggle('hidden')">
        <div class="pat-card-title">📊 PEA — Plan d'Épargne en Actions</div>
        <span class="pat-fisc-toggle">▼</span>
      </div>
      <div class="pat-fisc-body">
        <div class="pat-fisc-ref">${escHtml(peaFisc.reference || '')}</div>

        <div class="pat-kpi-row" style="margin-bottom:10px">
          <div class="pat-kpi">
            <div class="pat-kpi-label">VALEUR PEA</div>
            <div class="pat-kpi-val" style="color:var(--accent)">${fmt(peaVal, 0)} €</div>
          </div>
          <div class="pat-kpi">
            <div class="pat-kpi-label">PLAFOND RESTANT</div>
            <div class="pat-kpi-val" style="color:var(--gold)">${fmt(peaFisc.dispo || 0, 0)} €</div>
          </div>
          <div class="pat-kpi">
            <div class="pat-kpi-label">PLAFOND LÉGAL</div>
            <div class="pat-kpi-val">150 000 €</div>
          </div>
          <div class="pat-kpi">
            <div class="pat-kpi-label">PEA-PME</div>
            <div class="pat-kpi-val">+ 75 000 €</div>
          </div>
        </div>

        <div class="pat-fisc-section">
          <div class="pat-fisc-actif">⏳ Fiscalité selon ancienneté</div>
          <div class="pat-fisc-option">
            <span class="pat-fisc-badge critique">Avant 5 ans</span>${escHtml(peaFisc.avant_5ans || '')}
          </div>
          <div class="pat-fisc-option">
            <span class="pat-fisc-badge exonere">Après 5 ans</span>${escHtml(peaFisc.apres_5ans || '')}
          </div>
        </div>

        <div class="pat-fisc-section">
          <div class="pat-fisc-actif">🚗 Stellantis dans PEA — gain fiscal</div>
          <div class="pat-fisc-detail">${escHtml(peaFisc.detail_economie || '')}</div>
          <div class="pat-fisc-conseil">Économie annuelle estimée : +${fmt(peaFisc.economie_stellantis_an || 0, 2)} €/an</div>
        </div>

        <div class="pat-fisc-section">
          <div class="pat-fisc-actif">💡 Conseils</div>
          ${(peaFisc.conseil || []).map(c => `<div class="pat-fisc-option">· ${escHtml(c)}</div>`).join('')}
        </div>
      </div>
    </div>

    <!-- Immobilier -->
    <div class="pat-card">
      <div class="pat-fisc-header" onclick="this.nextElementSibling.classList.toggle('hidden')">
        <div class="pat-card-title">🏠 Immobilier — Fiscalité et Plus-Values</div>
        <span class="pat-fisc-toggle">▼</span>
      </div>
      <div class="pat-fisc-body">
        <div class="pat-fisc-ref">${escHtml(immoFisc.reference || '')}</div>

        <div class="pat-kpi-row" style="margin-bottom:10px">
          <div class="pat-kpi">
            <div class="pat-kpi-label">VALEUR BIEN</div>
            <div class="pat-kpi-val" style="color:var(--accent)">${fmt(immoVal, 0)} €</div>
          </div>
          <div class="pat-kpi">
            <div class="pat-kpi-label">CRÉDIT RESTANT</div>
            <div class="pat-kpi-val" style="color:var(--red)">${fmt(immoFisc.credit_restant || 0, 0)} €</div>
          </div>
          <div class="pat-kpi">
            <div class="pat-kpi-label">VALEUR NETTE</div>
            <div class="pat-kpi-val" style="color:var(--gold)">${fmt(immoNet, 0)} €</div>
          </div>
          <div class="pat-kpi">
            <div class="pat-kpi-label">DÉTENTION</div>
            <div class="pat-kpi-val">${immoFisc.annees_detention || 0} ans</div>
          </div>
        </div>

        <div class="pat-fisc-section">
          <div class="pat-fisc-actif">🏡 Résidence principale</div>
          <div class="pat-fisc-option">
            <span class="pat-fisc-badge exonere">EXONÉRÉ</span>${escHtml(immoRP.regime || '')}
          </div>
          <div class="pat-fisc-detail">${escHtml(immoRP.detail || '')}</div>
          <div class="pat-fisc-conseil">${escHtml(immoRP.conseil || '')}</div>
        </div>

        <div class="pat-fisc-section">
          <div class="pat-fisc-actif">🏢 Investissement locatif — PV</div>
          <div class="pat-fisc-option">
            Taux PV applicable actuellement :
            <strong style="color:${immoLoc.taux_pv_applicable === 0 ? 'var(--accent)' : 'var(--red)'}">
              ${immoLoc.taux_pv_applicable ?? 36.2}%
            </strong>
            ${immoLoc.exonere_ir && immoLoc.exonere_ps
              ? '<span class="pat-fisc-badge exonere">EXONÉRÉ TOTAL</span>'
              : immoLoc.exonere_ir ? '<span class="pat-fisc-badge exonere">IR EXONÉRÉ</span>' : ''}
          </div>
          <div class="pat-fisc-option" style="gap:8px;display:flex;flex-wrap:wrap">
            <span>Abattement IR : <strong>${escHtml(immoLoc.abattement_ir_acquis || '0%')}</strong></span>
            <span>Abattement PS : <strong>${escHtml(immoLoc.abattement_ps_acquis || '0%')}</strong></span>
            <span>IR net : <strong>${immoLoc.ir_net_pct ?? 19}%</strong></span>
            <span>PS net : <strong>${immoLoc.ps_net_pct ?? 17.2}%</strong></span>
          </div>
          <div class="pat-fisc-detail">${escHtml(immoLoc.detail_abattements || '')}</div>
          <div class="pat-fisc-section" style="margin-top:6px">
            <div class="pat-fisc-actif" style="font-size:.65rem">Revenus locatifs — Micro-foncier</div>
            <div class="pat-fisc-detail">
              Seuil : ${escHtml((immoLoc.micro_foncier || {}).seuil || '')} →
              abattement ${escHtml((immoLoc.micro_foncier || {}).abattement || '')}
            </div>
            <div class="pat-fisc-detail">${escHtml((immoLoc.micro_foncier || {}).detail || '')}</div>
          </div>
          <div class="pat-fisc-conseil">${escHtml(immoLoc.conseil || '')}</div>
        </div>

        <div class="pat-fisc-section">
          <div class="pat-fisc-actif">⚡ IFI — Impôt sur la Fortune Immobilière</div>
          <div class="pat-fisc-detail">${escHtml(immoIfi.seuil || '')}</div>
          <div class="pat-fisc-detail">${escHtml(immoIfi.detail || '')}</div>
        </div>
      </div>
    </div>

  </div>`;

  // ── Draw charts ────────────────────────────────────────────────
  _drawPatrimoinePie(pieLabels, pieValues, pieColors);
  _drawPatrimoineProjection(projLabels, projGrowth, projApports, projTotal, cfg);

  // ── Events ────────────────────────────────────────────────────
  qs('#pat-add-apport-btn').addEventListener('click', () => {
    qs('#apport-overlay').classList.remove('hidden');
    qs('#apport-montant').focus();
  });
}

function _destroyChart(key) {
  if (_patrimoineCharts[key]) {
    _patrimoineCharts[key].destroy();
    _patrimoineCharts[key] = null;
  }
}

function _drawPatrimoinePie(labels, values, colors) {
  _destroyChart('pie');
  const ctx = qs('#pat-pie-chart');
  if (!ctx) return;
  _patrimoineCharts.pie = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: colors, borderWidth: 2, borderColor: '#0a0a0f' }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      cutout: '62%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: '#dddded', font: { size: 10 }, padding: 8, boxWidth: 12 },
        },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.label}: ${fmt(ctx.parsed, 0)} €`,
          },
        },
      },
    },
  });
}

function _drawPatrimoineProjection(labels, growth, apports, total, cfg) {
  _destroyChart('proj');
  const ctx = qs('#pat-proj-chart');
  if (!ctx) return;

  // Ligne verticale "retraite" via un dataset sparse
  const retIdx   = cfg.age_retraite - cfg.age_actuel;
  const retMax   = total[retIdx] || Math.max(...total);
  const retLine  = labels.map((_, i) => (i === retIdx ? retMax : null));

  _patrimoineCharts.proj = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Patrimoine total',
          data: total,
          borderColor: '#ffd700',
          backgroundColor: 'rgba(255,215,0,.08)',
          borderWidth: 2,
          fill: true,
          tension: 0.3,
          pointRadius: (ctx) => ctx.dataIndex === retIdx ? 6 : 2,
          pointBackgroundColor: (ctx) => ctx.dataIndex === retIdx ? '#ff4466' : '#ffd700',
        },
        {
          label: 'Croissance naturelle',
          data: growth,
          borderColor: '#00e5a0',
          borderWidth: 1.5,
          borderDash: [4, 3],
          fill: false,
          tension: 0.3,
          pointRadius: 0,
        },
        {
          label: 'Apports cumulés',
          data: apports,
          borderColor: '#b44cff',
          borderWidth: 1.5,
          borderDash: [2, 4],
          fill: false,
          tension: 0.3,
          pointRadius: 0,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          labels: { color: '#dddded', font: { size: 10 }, boxWidth: 12 },
        },
        tooltip: {
          callbacks: {
            title: (items) => {
              const yr = items[0]?.label;
              return yr == String(cfg.annee_base + retIdx) ? `${yr} 🎯 Retraite ${cfg.age_retraite} ans` : yr;
            },
            label: (c) => ` ${c.dataset.label}: ${fmt(c.parsed.y, 0)} €`,
          },
        },
      },
      scales: {
        x: {
          ticks: {
            color: (ctx) => ctx.tick?.label == String(cfg.annee_base + retIdx) ? '#ff4466' : '#52526a',
            font: { size: 10 },
          },
          grid: { color: '#1e1e2a' },
        },
        y: {
          ticks: {
            color: '#52526a', font: { size: 10 },
            callback: v => v >= 1000 ? `${(v/1000).toFixed(0)}k€` : `${v}€`,
          },
          grid: { color: '#1e1e2a' },
        },
      },
    },
  });
}

// ── Apport modal events ───────────────────────────────────────────
function fmtNum(n) { return Number(n).toLocaleString('fr-FR'); }

function _initApportModal() {
  qs('#apport-close').addEventListener('click', () => {
    qs('#apport-overlay').classList.add('hidden');
  });
  qs('#apport-overlay').addEventListener('click', e => {
    if (e.target === qs('#apport-overlay')) qs('#apport-overlay').classList.add('hidden');
  });
  qs('#apport-submit').addEventListener('click', async () => {
    const montant = parseFloat(qs('#apport-montant').value);
    const note    = qs('#apport-note').value.trim();
    const fb      = qs('#apport-feedback');
    if (!montant || montant <= 0) {
      fb.style.color = 'var(--red)';
      fb.textContent = 'Montant invalide';
      return;
    }
    fb.style.color = 'var(--muted)';
    fb.textContent = 'Envoi en cours…';
    try {
      const r = await fetch(`${API}/patrimoine/apport`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ montant, note }),
      });
      const res = await r.json();
      if (res.status === 'ok') {
        fb.style.color = 'var(--accent)';
        fb.textContent = `✓ Apport de ${fmt(montant, 0)} € enregistré`;
        qs('#apport-montant').value = '';
        qs('#apport-note').value    = '';
        setTimeout(() => {
          qs('#apport-overlay').classList.add('hidden');
          patrimoineLoaded = false;
          loadPatrimoine(true);
        }, 1200);
      } else {
        throw new Error(res.erreur || 'Erreur');
      }
    } catch (err) {
      fb.style.color = 'var(--red)';
      fb.textContent = `Erreur : ${err.message}`;
    }
  });
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

  // Bertez card
  const bSig  = d.bertez_signal;
  const bMode = d.bertez_mode;
  const bSum  = (d.agent_summaries || {})['Bertez_Energy'] || '';
  const hasBertez = bSig !== null && bSig !== undefined;
  const modeRegime = { DEFENSIF: 'critique', NEUTRE: 'neutre', OFFENSIF: 'ample' }[bMode] || 'neutre';
  const sigColor = !hasBertez ? 'var(--muted)' : bSig > 0 ? 'var(--accent)' : bSig < 0 ? 'var(--red)' : 'var(--muted)';
  const sigStr   = hasBertez ? (bSig >= 0 ? '+' : '') + Number(bSig).toFixed(3) : '—';
  const gaugePos = hasBertez && bSig > 0 ? Math.min(bSig * 50, 50).toFixed(1) : '0';
  const gaugeNeg = hasBertez && bSig < 0 ? Math.min(-bSig * 50, 50).toFixed(1) : '0';

  const bertezHtml = `
    <div class="bertez-card">
      <div class="liq-section-title">⚡ Signal Bertez — Économie / Énergie</div>
      <div class="bertez-header">
        <div class="liq-regime regime-${modeRegime}">${bMode || 'INCONNU'}</div>
        <div class="bertez-signal-num" style="color:${sigColor}">${sigStr}</div>
        <div style="font-size:0.52rem;color:var(--muted);font-family:var(--font-mono)">[-1 / +1]</div>
      </div>
      <div class="bertez-gauge-labels">
        <span>DÉFENSIF ◄</span><span>NEUTRE</span><span>► OFFENSIF</span>
      </div>
      <div class="bertez-gauge-track">
        <div class="bertez-gauge-center"></div>
        <div class="bertez-gauge-pos" style="width:${gaugePos}%"></div>
        <div class="bertez-gauge-neg" style="width:${gaugeNeg}%"></div>
      </div>
      <div class="bertez-axis-labels"><span>-1</span><span>0</span><span>+1</span></div>
      ${bSum ? `<div class="bertez-summary">${escHtml(bSum)}</div>` : ''}
    </div>`;

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

      ${bertezHtml}

      ${agentsHtml ? `
      <div class="liq-card">
        <div class="liq-section-title">Scores par agent (8 sources)</div>
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

// ── Gérant Délégué tab ────────────────────────────────────────────
let gerantDelegueLoaded = false;

async function loadGerantDelegue(silent = false) {
  if (gerantDelegueLoaded && !silent) return;
  try {
    const [etatR, actuR, divR, rpR, benchR, comiteR] = await Promise.allSettled([
      fetch(`${API}/gerant-delegue/etat`).then(r => r.json()),
      fetch(`${API}/actualites`).then(r => r.json()),
      fetch(`${API}/dividendes`).then(r => r.json()),
      fetch(`${API}/risk-parity`).then(r => r.json()),
      fetch(`${API}/benchmark`).then(r => r.json()),
      fetch(`${API}/comite-selection/historique`).then(r => r.json()),
    ]);
    gerantDelegueLoaded = true;
    renderGerantDelegue(
      etatR.status    === 'fulfilled' ? etatR.value    : null,
      actuR.status    === 'fulfilled' ? actuR.value    : null,
      divR.status     === 'fulfilled' ? divR.value     : null,
      rpR.status      === 'fulfilled' ? rpR.value      : null,
      benchR.status   === 'fulfilled' ? benchR.value   : null,
      comiteR.status  === 'fulfilled' ? comiteR.value  : null,
    );
  } catch(e) {
    if (!silent)
      qs('#agd-wrap').innerHTML = '<div class="error-state">Impossible de charger le Gérant Délégué.</div>';
  }
}

function renderGerantDelegue(etat, actuData, divData, rpData, benchData, comiteList) {
  const agd01 = etat?.agd_01 || {};
  const howell = agd01.howell_regime || 'HOWELL_SEREIN';
  const howellResume = agd01.howell_resume || 'Environnement favorable';
  const howellCls = {
    HOWELL_SEREIN:    'serein',
    HOWELL_ATTENTION: 'attention',
    HOWELL_VIGILANCE: 'vigilance',
    HOWELL_DANGER:    'danger',
  }[howell] || 'serein';
  const howellIcon = {
    HOWELL_SEREIN: '✅', HOWELL_ATTENTION: '⚠️', HOWELL_VIGILANCE: '🟠', HOWELL_DANGER: '🚨',
  }[howell] || '✅';

  // SITG
  const sitgGrille = agd01.sitg_grille || [{perf_min:25,mult:2},{perf_min:15,mult:1.5},{perf_min:10,mult:1.25}];
  const sitgHtml = sitgGrille.map(g => {
    const cls = g.mult >= 2 ? 'x200' : g.mult >= 1.5 ? 'x150' : g.mult >= 1.25 ? 'x125' : 'x1';
    return `<div class="agd-sitg-cell">
      <div class="agd-sitg-val ${cls}">×${g.mult.toFixed(2)}</div>
      <div class="agd-sitg-lbl">≥ +${g.perf_min}%/an</div>
    </div>`;
  }).join('') + `<div class="agd-sitg-cell">
    <div class="agd-sitg-val x1">×1.00</div>
    <div class="agd-sitg-lbl">&lt; +10%/an</div>
  </div>`;

  // Retraite
  const objR = agd01.objectif_retraite || {annee: 2041, montant: 500000};
  const patActuel = etat?.agd_01 ? (divData?.revenu_annuel_total ? 18082 : 18082) : 18082;
  const annesRestants = objR.annee - new Date().getFullYear();
  const projEstimee = patActuel * Math.pow(1.10, annesRestants);
  const pctRetraite = Math.min(100, (patActuel / objR.montant * 100)).toFixed(1);

  // Section Actualités
  const articles = (actuData?.articles || []).slice(0, 8);
  const actuHtml = articles.length ? articles.map(a => `
    <div class="agd-actu-item">
      <span class="agd-niveau ${a.niveau}">${a.niveau}</span>
      <div>
        <div class="agd-actu-titre">${escHtml(a.titre || '')}</div>
        <div class="agd-actu-src">${escHtml(a.source || '')} · ${_fmtTs(a.publie_a)}</div>
      </div>
    </div>`).join('') : '<div style="font-size:.7rem;color:var(--muted);padding:10px 0">Aucune actualité chargée</div>';

  // Section Dividendes
  const divPositions = (divData?.positions || [])
    .filter(p => (p.rev_annuel || 0) > 0)
    .sort((a,b) => (b.rev_annuel||0) - (a.rev_annuel||0))
    .slice(0, 8);
  const divCoupes = (divData?.positions || []).filter(p => p.coupe_detectee);
  const coupesHtml = divCoupes.length
    ? `<div class="agd-coupe-alert">🚨 COUPE DÉTECTÉE sur ${divCoupes.map(c => c.ticker).join(', ')}</div>` : '';
  const revMensuel = divData?.revenu_mensuel_total || 0;
  const revAnnuel  = divData?.revenu_annuel_total  || 0;
  const ecartObj   = divData?.ecart_objectif ?? (revMensuel - 500);
  const ecartCls   = ecartObj >= 0 ? 'pos' : 'neg';
  const ecartStr   = (ecartObj >= 0 ? '+' : '') + ecartObj.toFixed(0) + '€';
  const divRowsHtml = divPositions.map(p => {
    const score = p.scoring?.score ?? '—';
    return `<div class="agd-div-row">
      <span class="agd-div-ticker">${escHtml(p.ticker)}</span>
      <span style="font-size:.62rem;color:var(--muted)">${escHtml(p.nom || '')}</span>
      <span class="agd-div-rev">${fmt(p.rev_annuel, 0)}€/an</span>
      <span class="agd-div-score">${score}/10</span>
    </div>`;
  }).join('');

  // Section Risk Parity
  const rpClasses = rpData?.classes || [];
  const rpRebal   = rpData?.rebalancement || [];
  const rpRowsHtml = rpClasses.map(c => {
    const w = Math.min(c.contribution_risque_pct, 100);
    const barColor = c.statut === 'CRITIQUE' ? '#ff4466' : c.statut === 'WARNING' ? '#ff9900' : '#00e5a0';
    return `<div class="agd-rp-row">
      <span class="agd-rp-label">${escHtml(c.classe)}</span>
      <div class="agd-rp-bar-bg">
        <div class="agd-rp-bar-fill" style="width:${w.toFixed(1)}%;background:${barColor}"></div>
      </div>
      <span class="agd-rp-pct" style="color:${barColor}">${c.contribution_risque_pct.toFixed(1)}%</span>
      <span class="agd-rp-status ${c.statut}">${c.statut}</span>
    </div>`;
  }).join('');
  const rpRebalHtml = rpRebal.length ? `<div class="agd-rp-rebal">
    ${rpRebal.map(r => `${r.action} ${r.classe} (${r.ticker}) : ${r.delta_pct > 0 ? '+' : ''}${r.delta_pct}pp`).join('<br>')}
  </div>` : '';

  // Section Benchmark
  const benchmarks = benchData?.benchmarks || {};
  const portPerfs  = benchData?.portfolio?.performances || {};
  const alpha      = benchData?.alpha_reel || {};
  const sharpe     = benchData?.portfolio?.sharpe;
  const drawdown   = benchData?.portfolio?.max_drawdown;
  const benchRows  = Object.entries(benchmarks).map(([label, b]) => {
    const perf1m = b.performances?.['1m'];
    const perfYTD = b.performances?.['YTD'];
    const a = alpha[label];
    const aCls = a == null ? 'neu' : a > 0 ? 'pos' : 'neg';
    const aStr = a == null ? '—' : (a > 0 ? '+' : '') + a.toFixed(2) + '%';
    return `<tr>
      <td>${escHtml(label)}</td>
      <td>${perf1m != null ? (perf1m > 0 ? '+' : '') + perf1m.toFixed(2) + '%' : '—'}</td>
      <td>${perfYTD != null ? (perfYTD > 0 ? '+' : '') + perfYTD.toFixed(2) + '%' : '—'}</td>
      <td class="${aCls}">${aStr}</td>
    </tr>`;
  }).join('');
  const portPerf1m = portPerfs['1m'];
  const portPerfAnn = portPerfs['annualise'];

  // Section Comité
  const votes = (comiteList || []).slice(0, 6);
  const voteDecCls = dec => {
    if (!dec) return 'hold';
    if (dec.includes('CONFIRMÉ')) return 'confirm';
    if (dec.includes('CONDITIONNEL')) return 'cond';
    if (dec.includes('VETO')) return 'veto';
    return 'hold';
  };
  const voteDecIcon = dec => {
    if (!dec) return '🔵';
    if (dec.includes('CONFIRMÉ'))    return '✅';
    if (dec.includes('CONDITIONNEL')) return '🟡';
    if (dec.includes('VETO'))        return '🛑';
    return '🔵';
  };
  const votesHtml = votes.length ? votes.map(v => {
    const votesStr = (v.votes || []).map(vv => `${vv.votant[0]}:${vv.vote === 'OUI' ? '✓' : vv.vote === 'NON' ? '✗' : '—'}`).join(' ');
    return `<div class="agd-vote-row">
      <span class="agd-vote-ticker">${escHtml(v.ticker || '?')}</span>
      <span class="agd-vote-dec ${voteDecCls(v.decision)}">${voteDecIcon(v.decision)} ${escHtml(v.decision || '?')}</span>
      <span class="agd-vote-votes">${escHtml(votesStr)}</span>
      <span class="agd-vote-ts">${_fmtTs(v.timestamp)}</span>
    </div>`;
  }).join('') : '<div style="font-size:.7rem;color:var(--muted);padding:8px 0">Aucune séance enregistrée</div>';

  qs('#agd-wrap').innerHTML = `
    <div class="agd-panel">

      <!-- Identity -->
      <div class="agd-identity">
        <div class="agd-identity-top">
          <div class="agd-avatar">🏛</div>
          <div>
            <div class="agd-name">Dr Alexandre Redon</div>
            <div class="agd-title">Gérant Délégué — AGD-01</div>
            <div class="agd-xp">Bridgewater Associates · Goldman Sachs · Scion Capital · Berkshire Hathaway<br>20 ans d'expérience institutionnelle · Sérénité · Rigueur · Humilité · Discipline</div>
          </div>
        </div>
        <div class="agd-badges">
          <span class="agd-badge phd">PhD Finance MIT</span>
          <span class="agd-badge cfa">CFA Level 3</span>
          <span class="agd-badge frm">FRM</span>
          <span class="agd-badge bw">Bridgewater</span>
        </div>

        <!-- Howell -->
        <div class="agd-howell ${howellCls}">
          <span class="agd-howell-label">${howellIcon} ${howell.replace('HOWELL_', '')}</span>
          <span class="agd-howell-resume">${escHtml(howellResume)}</span>
        </div>

        <!-- SITG Grille -->
        <div>
          <div style="font-size:.56rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px">Grille SITG — Skin In The Game</div>
          <div class="agd-sitg-row">${sitgHtml}</div>
        </div>

        <!-- Objectif Retraite -->
        <div class="agd-retraite">
          <div class="agd-retraite-header">
            <span>Objectif Retraite Zoubida — 56 ans (2041)</span>
            <span class="agd-retraite-val">${fmt(patActuel, 0)}€ / 500 000€</span>
          </div>
          <div style="font-size:.6rem;color:var(--muted)">
            Projection à 10%/an dans ${annesRestants} ans : <b style="color:var(--accent)">${fmt(Math.round(projEstimee), 0)}€</b>
            &nbsp;·&nbsp; Progression : <b style="color:var(--gold)">${pctRetraite}%</b>
          </div>
          <div class="agd-retraite-bar">
            <div class="agd-retraite-fill" style="width:${pctRetraite}%"></div>
          </div>
        </div>
      </div>

      <!-- Actualités -->
      <div class="agd-card">
        <div class="agd-card-title">📰 Actualités pertinentes</div>
        ${actuHtml}
        <button class="agd-refresh-btn" id="agd-actu-refresh">↻ Actualiser</button>
      </div>

      <!-- Dividendes -->
      <div class="agd-card">
        <div class="agd-card-title">💰 Revenus passifs — Dividendes</div>
        ${coupesHtml}
        <div class="agd-div-kpi">
          <div class="agd-div-kpi-cell">
            <div class="agd-div-kpi-val">${fmt(revMensuel, 0)}€</div>
            <div class="agd-div-kpi-lbl">/ mois</div>
          </div>
          <div class="agd-div-kpi-cell">
            <div class="agd-div-kpi-val">${fmt(revAnnuel, 0)}€</div>
            <div class="agd-div-kpi-lbl">/ an</div>
          </div>
          <div class="agd-div-kpi-cell">
            <div class="agd-div-kpi-val" style="color:${ecartCls === 'pos' ? 'var(--accent)' : 'var(--red)'}">${ecartStr}</div>
            <div class="agd-div-kpi-lbl">vs obj 500€/m</div>
          </div>
        </div>
        ${divRowsHtml || '<div style="font-size:.7rem;color:var(--muted);padding:6px 0">Données indisponibles</div>'}
      </div>

      <!-- Risk Parity -->
      <div class="agd-card">
        <div class="agd-card-title">⚖️ Risk Parity — Dalio All Weather</div>
        ${rpRowsHtml || '<div style="font-size:.7rem;color:var(--muted);padding:6px 0">Données indisponibles</div>'}
        ${rpRebalHtml}
        ${rpData?.vol_portefeuille_pct != null
          ? `<div style="font-size:.6rem;color:var(--muted);margin-top:8px">Vol. portefeuille : <b style="color:var(--text)">${rpData.vol_portefeuille_pct}%/an</b> · Cible équipondérée : <b style="color:var(--text)">${rpData.contribution_cible_pct?.toFixed(1)}%</b> par classe</div>`
          : ''}
      </div>

      <!-- Benchmark -->
      <div class="agd-card">
        <div class="agd-card-title">📊 Benchmark — Alpha réel</div>
        <table class="agd-bench-table">
          <thead><tr>
            <th>Indice</th><th>1 mois</th><th>YTD</th><th>Alpha</th>
          </tr></thead>
          <tbody>
            ${benchRows || '<tr><td colspan="4" style="color:var(--muted);font-size:.65rem">Données indisponibles</td></tr>'}
          </tbody>
        </table>
        ${portPerf1m != null || sharpe != null ? `
        <div style="display:flex;gap:12px;margin-top:10px;font-size:.62rem;color:var(--muted)">
          ${portPerf1m != null ? `<span>Portefeuille 1m : <b style="color:${portPerf1m>=0?'var(--accent)':'var(--red)'}">${portPerf1m>=0?'+':''}${portPerf1m.toFixed(2)}%</b></span>` : ''}
          ${portPerfAnn != null ? `<span>Annualisé : <b style="color:var(--gold)">${portPerfAnn>=0?'+':''}${portPerfAnn.toFixed(2)}%</b></span>` : ''}
          ${sharpe != null ? `<span>Sharpe : <b style="color:var(--text)">${sharpe.toFixed(2)}</b></span>` : ''}
          ${drawdown != null ? `<span>Max DD : <b style="color:var(--red)">${drawdown.toFixed(2)}%</b></span>` : ''}
        </div>` : ''}
      </div>

      <!-- Comité Sélection -->
      <div class="agd-card">
        <div class="agd-card-title">🏛️ Comité Sélection — Votes 3/3</div>
        ${votesHtml}
        <div style="margin-top:12px;border-top:1px solid var(--surface2);padding-top:12px">
          <div style="font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">Soumettre un ticker au Comité</div>
          <div class="agd-form">
            <div class="agd-form-row">
              <input id="agd-comite-ticker" class="agd-input" placeholder="Ex: VPK.AS, TTE.PA, O…" style="text-transform:uppercase" />
              <button id="agd-comite-submit" class="agd-btn" style="white-space:nowrap">Voter →</button>
            </div>
            <div id="agd-comite-result" class="agd-result"></div>
          </div>
        </div>
      </div>

      <!-- Veto décision émotionnelle -->
      <div class="agd-card">
        <div class="agd-card-title">🛑 Veto — Évaluation décision par AGD-01</div>
        <div style="font-size:.62rem;color:var(--muted);margin-bottom:10px">
          Soumets une décision au Gérant Délégué. Il peut opposer un VETO si elle est émotionnelle ou irrationnelle.
        </div>
        <div class="agd-form">
          <div class="agd-form-row">
            <input id="agd-veto-ticker" class="agd-input" placeholder="Ticker (ex: NVDA)" style="width:120px;flex-shrink:0;text-transform:uppercase" />
            <select id="agd-veto-action" class="agd-select">
              <option value="buy">ACHETER</option>
              <option value="sell">VENDRE</option>
              <option value="hold">CONSERVER</option>
            </select>
            <input id="agd-veto-montant" class="agd-input" type="number" min="1" placeholder="Montant €" style="width:110px;flex-shrink:0" />
          </div>
          <input id="agd-veto-contexte" class="agd-input" placeholder="Pourquoi cette décision ? (optionnel)" />
          <button id="agd-veto-submit" class="agd-btn">Soumettre au Gérant Délégué</button>
          <div id="agd-veto-result" class="agd-result"></div>
        </div>
      </div>

      <div class="agd-timestamp">Gérant Délégué AGD-01 · Objectif retraite 2041 — non négociable</div>
    </div>`;

  // Event : refresh actualités
  const actuBtn = qs('#agd-actu-refresh');
  if (actuBtn) {
    actuBtn.addEventListener('click', async () => {
      actuBtn.textContent = '⌛…';
      actuBtn.disabled = true;
      gerantDelegueLoaded = false;
      await loadGerantDelegue(true);
      const b = qs('#agd-actu-refresh');
      if (b) { b.textContent = '↻ Actualiser'; b.disabled = false; }
    });
  }

  // Event : Comité Sélection voter
  const comiteSubmit = qs('#agd-comite-submit');
  if (comiteSubmit) {
    comiteSubmit.addEventListener('click', async () => {
      const ticker = (qs('#agd-comite-ticker')?.value || '').trim().toUpperCase();
      if (!ticker) return;
      comiteSubmit.disabled = true;
      comiteSubmit.textContent = '⌛…';
      const resEl = qs('#agd-comite-result');
      try {
        const resp = await fetch(`${API}/comite-selection/voter`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticker }),
        });
        const data = await resp.json();
        if (resEl) {
          const dec = data.decision || '?';
          const cls = dec.includes('CONFIRMÉ') ? 'valide' : dec.includes('VETO') ? 'veto' : 'valide';
          resEl.className = `agd-result show ${cls}`;
          const votesStr = (data.votes || []).map(v => `${v.votant} : ${v.vote} — ${v.motif?.slice(0,60) || ''}`).join('\n');
          resEl.textContent = `${dec}\n${votesStr}`;
        }
        gerantDelegueLoaded = false;
        setTimeout(() => loadGerantDelegue(true), 1500);
      } catch(e) {
        if (resEl) { resEl.className = 'agd-result show veto'; resEl.textContent = 'Erreur: ' + e.message; }
      } finally {
        comiteSubmit.disabled = false;
        comiteSubmit.textContent = 'Voter →';
      }
    });
  }

  // Event : Veto décision
  const vetoSubmit = qs('#agd-veto-submit');
  if (vetoSubmit) {
    vetoSubmit.addEventListener('click', async () => {
      const ticker  = (qs('#agd-veto-ticker')?.value || '').trim().toUpperCase();
      const action  = qs('#agd-veto-action')?.value || 'buy';
      const montant = parseFloat(qs('#agd-veto-montant')?.value || '0');
      const contexte= qs('#agd-veto-contexte')?.value || '';
      if (!ticker || !montant) return;
      vetoSubmit.disabled = true;
      vetoSubmit.textContent = '⌛ Analyse AGD-01…';
      const resEl = qs('#agd-veto-result');
      try {
        const resp = await fetch(`${API}/gerant-delegue/evaluer-decision`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticker, action, montant, contexte }),
        });
        const data = await resp.json();
        if (resEl) {
          const dec = data.decision || '?';
          const cls = dec === 'VETO' ? 'veto' : 'valide';
          const icon = dec === 'VETO' ? '🛑' : '✅';
          resEl.className = `agd-result show ${cls}`;
          resEl.textContent = `${icon} ${dec} — Confiance ${((data.confiance||0)*100).toFixed(0)}%\n${data.raison || ''}\n${data.recommandation ? 'Conseil: ' + data.recommandation : ''}`;
        }
      } catch(e) {
        if (resEl) { resEl.className = 'agd-result show veto'; resEl.textContent = 'Erreur: ' + e.message; }
      } finally {
        vetoSubmit.disabled = false;
        vetoSubmit.textContent = 'Soumettre au Gérant Délégué';
      }
    });
  }
}

function _fmtTs(ts) {
  if (!ts) return '—';
  try {
    const d = new Date(ts.includes('T') ? ts : ts + 'Z');
    return d.toLocaleString('fr-FR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' });
  } catch { return ts.slice(0, 16); }
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
_initApportModal();

'use strict';

const _apiOverride = (typeof window.KING_API !== 'undefined' && window.KING_API)
  || new URLSearchParams(location.search).get('api');
const API    = _apiOverride ? _apiOverride.replace(/\/+$/, '') : '/api';
const _remoteMode = Boolean(_apiOverride);

const TARGET = 10_000;
const START  = 500;

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
let activeTab      = 'dashboard';
let activeFilter   = null;

// Loaded flags
let dashboardLoaded    = false;
let protectionLoaded   = false;
let divisionsLoaded    = false;
let divisionsData      = null;
let fiscaliteLoaded    = false;
let intelligenceLoaded = false;
let retraiteLoaded     = false;
let marchesLoaded      = false;
let secteursLoaded     = false;
let liquiditeLoaded    = false;
let _liqRefreshing     = false;
let morningBriefLoaded = false;

// Retraite charts
let _retraiteCharts = {};

// Change detection
const prevTraderValues = new Map();
const prevTraderRanks  = new Map();
const wonTraders       = new Set();
const milestones       = new Map();
const MILESTONES       = [1_000, 2_500, 5_000];

// Sparkline data
const sparklineData   = new Map();
const divisionHistory = new Map();
const MAX_HISTORY     = 60;

// Notifications
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
  if (_remoteMode) return API.replace(/^http/, 'ws').replace(/\/api\/?$/, '/ws');
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}/ws`;
}

function initWS() {
  ws = new WebSocket(_wsUrl());
  ws.onopen  = () => { stopPolling(); hideBanner(); setWsDot('live'); notify('🔌','CONNECTÉ','Flux temps réel établi.','var(--accent)'); };
  ws.onclose = () => { showBanner(); setWsDot('offline'); startPolling(); setTimeout(initWS, 5000); notify('⚠','DÉCONNECTÉ','Mode polling activé.','var(--red)'); };
  ws.onerror = () => ws.close();
  ws.onmessage = ({ data }) => {
    const msg = JSON.parse(data);
    if (msg.type !== 'heartbeat') applyState(msg);
  };
}

function startPolling() { if (pollTimer) return; fetchState(); pollTimer = setInterval(fetchState, 5000); }
function stopPolling()  { clearInterval(pollTimer); pollTimer = null; }
async function fetchState() { try { applyState(await (await fetch(`${API}/state`)).json()); } catch {} }
function setWsDot(cls) { const dot = qs('#ws-dot'); dot.className = `ws-dot ${cls}`; }

// ── State ─────────────────────────────────────────────────────────
function applyState(s) {
  const isFirstLoad = state === null;
  state = s;

  qs('#battle-day').textContent = `J${s.battle_day} / 30`;
  const winners = s.leaderboard.filter(t => t.won).length;
  qs('#winners-count').textContent = winners > 0 ? `${winners} 👑` : '0';
  qs('#top-value').textContent = s.leaderboard[0] ? `€${fmt(s.leaderboard[0].value, 0)}` : '—';
  qs('#update-time').textContent = new Date().toLocaleTimeString('fr-FR', { hour:'2-digit', minute:'2-digit', second:'2-digit' });

  // NAV totale
  const navTotal = s.leaderboard.reduce((sum, t) => sum + t.value, 0);
  const navEl = qs('#nav-total');
  if (navEl) navEl.textContent = `€${fmt(navTotal, 0)}`;

  // Bertez badge
  const bEl = qs('#bertez-mode-val');
  if (bEl) {
    const bm = s.bertez_mode;
    const abbr = { DEFENSIF: 'DEF', NEUTRE: 'NEU', OFFENSIF: 'OFF' };
    bEl.textContent = abbr[bm] || '—';
    bEl.className = 'stat-value ' + (bm === 'DEFENSIF' ? 'red' : bm === 'OFFENSIF' ? 'green' : 'muted');
  }

  // Sparklines
  s.leaderboard.forEach(t => {
    if (!sparklineData.has(t.id)) sparklineData.set(t.id, []);
    const arr = sparklineData.get(t.id);
    arr.push(t.value);
    if (arr.length > MAX_HISTORY) arr.shift();
  });

  // Division history
  const divMap = {};
  s.leaderboard.forEach(t => { if (!divMap[t.division]) divMap[t.division] = []; divMap[t.division].push(t.value); });
  Object.entries(divMap).forEach(([div, vals]) => {
    const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
    if (!divisionHistory.has(div)) divisionHistory.set(div, []);
    const arr = divisionHistory.get(div);
    arr.push(avg);
    if (arr.length > MAX_HISTORY) arr.shift();
  });

  if (!isFirstLoad) {
    s.leaderboard.forEach(t => {
      if (t.won && !wonTraders.has(t.id)) { wonTraders.add(t.id); notify('🏆','NOUVEAU WINNER !',`${t.name} atteint €10 000 !`,'var(--gold)'); }
      if (!milestones.has(t.id)) milestones.set(t.id, new Set());
      const ms = milestones.get(t.id);
      MILESTONES.forEach(target => {
        if (!ms.has(target) && t.value >= target) { ms.add(target); notify('🚀',`${t.name}`,`Capital ×${(target/START).toFixed(0)} — €${fmt(target,0)} !`, divColor(t.division)); }
      });
      const prev = prevTraderRanks.get(t.id);
      if (prev !== undefined && prev !== t.rank) {
        const delta = prev - t.rank;
        if (delta >= 5) notify('📈',`${t.name}`,`Remonte de ${delta} places ! Rang #${t.rank}`,'var(--accent)');
        else if (delta <= -5) notify('📉',`${t.name}`,`Recule de ${Math.abs(delta)} places. Rang #${t.rank}`,'var(--red)');
      }
      prevTraderRanks.set(t.id, t.rank);
    });
  } else {
    s.leaderboard.forEach(t => {
      if (t.won) wonTraders.add(t.id);
      prevTraderRanks.set(t.id, t.rank);
      MILESTONES.forEach(target => {
        if (t.value >= target) { if (!milestones.has(t.id)) milestones.set(t.id, new Set()); milestones.get(t.id).add(target); }
      });
    });
  }

  updateTicker(s.leaderboard);

  if (activeTab === 'croissance')   renderCroissanceLeaderboard(s.leaderboard);
  if (activeTab === 'dashboard')    refreshDashboardState(s);
  if (activeTraderId !== null)      refreshModal();
  if (divisionsLoaded)              loadDivisions(true);
  if (activeTab === 'croissance')   updateDivisionChart();
}

// ── Ticker tape ───────────────────────────────────────────────────
function updateTicker(traders) {
  const el = qs('#ticker-inner');
  if (!el || !traders || !traders.length) return;
  const sorted = [...traders].sort((a, b) => Math.abs(b.pnl_pct) - Math.abs(a.pnl_pct));
  const items  = sorted.slice(0, 12).map(t => {
    const sign = t.pnl >= 0 ? '+' : '';
    const cls  = t.pnl >= 0 ? 'ticker-up' : 'ticker-down';
    const arrow = t.pnl >= 0 ? '▲' : '▼';
    return `<span class="ticker-item"><span class="ticker-rank">#${t.rank}</span><span class="ticker-name">${escHtml(t.name.split(' ').slice(0,2).join(' '))}</span><span class="${cls}">${arrow} ${sign}${t.pnl_pct}%</span></span>`;
  }).join('');
  el.innerHTML = items + items;
}

// ── Tab system ────────────────────────────────────────────────────
function switchTab(tab) {
  qsa('.tab-btn').forEach(b  => b.classList.toggle('active', b.dataset.tab === tab));
  qsa('.tab-pane').forEach(p => p.classList.toggle('hidden', p.id !== `tab-${tab}`));
  activeTab = tab;

  if (tab === 'dashboard')      loadDashboard();
  if (tab === 'protection')     loadProtection();
  if (tab === 'croissance')     { loadCroissance(); updateDivisionChart(); }
  if (tab === 'fiscalite')      loadFiscalite();
  if (tab === 'intelligence')   loadIntelligence();
  if (tab === 'retraite')       loadRetraite();
  if (tab === 'marches')        loadMarches();
  if (tab === 'secteurs')       loadSecteurs();
  if (tab === 'liquidite')      loadLiquidite();
  if (tab === 'morning-brief')  loadMorningBrief();
}

// ═══════════════════════════════════════════════════════════════════
// TAB 1 — TABLEAU DE BORD
// ═══════════════════════════════════════════════════════════════════

async function loadDashboard(silent = false) {
  if (dashboardLoaded && !silent) return;
  try {
    const [busRes, briefRes] = await Promise.allSettled([
      fetch(`${API}/bus/state`).then(r => r.json()),
      fetch(`${API}/brief`).then(r => r.json()),
    ]);
    const bus   = busRes.status   === 'fulfilled' ? busRes.value   : null;
    const brief = briefRes.status === 'fulfilled' ? briefRes.value : null;
    dashboardLoaded = true;
    renderDashboard(state, bus, brief);
  } catch {
    if (!silent) qs('#dashboard-wrap').innerHTML = '<div class="error-state">Erreur chargement tableau de bord.</div>';
  }
}

function refreshDashboardState(s) {
  if (!dashboardLoaded) return;
  const navEl = qs('#dash-nav-val');
  if (navEl) {
    const navTotal = s.leaderboard.reduce((sum, t) => sum + t.value, 0);
    navEl.textContent = `€${fmt(navTotal, 0)}`;
  }
  const top5El = qs('#dash-top5');
  if (top5El) top5El.innerHTML = buildTop5Html(s.leaderboard.slice(0, 5));
}

function buildTop5Html(traders) {
  return traders.map(t => {
    const sign = t.pnl >= 0 ? '+' : '';
    const cls  = t.pnl >= 0 ? 'green' : 'red';
    const dc   = divColor(t.division);
    return `<div class="dash-trader-row">
      <span class="dash-rank">${rankIcon(t.rank)}</span>
      <span class="dash-tname">${escHtml(t.name.split(' ').slice(0,2).join(' '))}</span>
      <span class="dash-tval">€${fmt(t.value, 0)}</span>
      <span class="dash-tpnl ${cls}">${sign}${t.pnl_pct}%</span>
      <span class="div-chip" style="--chip-color:${dc};padding:1px 5px;font-size:.5rem">${divIcon(t.division)}</span>
    </div>`;
  }).join('');
}

function renderDashboard(s, bus, brief) {
  const wrap = qs('#dashboard-wrap');

  const navTotal = s ? s.leaderboard.reduce((sum, t) => sum + t.value, 0) : 0;
  const top5     = s ? s.leaderboard.slice(0, 5) : [];
  const bm       = s?.bertez_mode || '—';
  const bmCls    = bm === 'DEFENSIF' ? 'red' : bm === 'OFFENSIF' ? 'green' : 'muted';

  // Black swan
  const halt     = bus?.black_swan_halt ?? false;
  const vix      = bus?.vix ?? null;
  const liqFactor= bus?.liq_budget_factor ?? 1.0;
  const bsCls    = halt ? 'red' : vix != null && vix >= 30 ? 'yellow' : 'green';
  const bsLabel  = halt ? '🚨 HALT' : vix != null ? `VIX ${Number(vix).toFixed(1)}` : '—';

  // Howell (from bus or agd)
  const howell   = bus?.howell_regime || '—';
  const howellMap= { HOWELL_SEREIN:'SEREIN', HOWELL_ATTENTION:'ATTENTION', HOWELL_VIGILANCE:'VIGILANCE', HOWELL_DANGER:'DANGER' };
  const howellCls= { HOWELL_SEREIN:'green', HOWELL_ATTENTION:'yellow', HOWELL_VIGILANCE:'orange', HOWELL_DANGER:'red' };

  // Brief
  const dir      = (brief?.direction || 'neutral').toLowerCase();
  const conf     = Math.round((brief?.confidence || 0.5) * 100);
  const dirEmoji = { bullish:'📈', bearish:'📉', neutral:'➡️' };
  const dirLabel = { bullish:'HAUSSIER', bearish:'BAISSIER', neutral:'NEUTRE' };
  const dirColor = dir === 'bullish' ? 'var(--accent)' : dir === 'bearish' ? 'var(--red)' : 'var(--muted)';

  // CB signals summary
  const cbSignals = bus?.central_banks || {};
  const cbList = Object.values(cbSignals).filter(cb => cb && cb.sentiment != null).slice(0, 6);
  const hawkish = cbList.filter(cb => cb.sentiment > 0.3).length;
  const dovish  = cbList.filter(cb => cb.sentiment < -0.3).length;

  wrap.innerHTML = `
<div class="dash-panel">

  <div class="dash-pillar-header">
    <span class="dash-fo-label">FAMILY OFFICE — KING FUND</span>
    <span class="dash-battle-badge">Jour ${s?.battle_day || '—'} / 30</span>
  </div>

  <!-- KPI row principale -->
  <div class="dash-kpi-row">
    <div class="dash-kpi">
      <div class="dash-kpi-label">NAV FUND</div>
      <div class="dash-kpi-val accent" id="dash-nav-val">€${fmt(navTotal, 0)}</div>
      <div class="dash-kpi-sub">30 traders · ${fmt(navTotal / 30, 0)}€ moy.</div>
    </div>
    <div class="dash-kpi">
      <div class="dash-kpi-label">BERTEZ</div>
      <div class="dash-kpi-val ${bmCls}">${bm}</div>
      <div class="dash-kpi-sub">Régime macro</div>
    </div>
    <div class="dash-kpi">
      <div class="dash-kpi-label">BLACK SWAN</div>
      <div class="dash-kpi-val ${bsCls}" id="dash-bs-val">${bsLabel}</div>
      <div class="dash-kpi-sub">Budget ×${liqFactor.toFixed(2)}</div>
    </div>
    <div class="dash-kpi">
      <div class="dash-kpi-label">HOWELL</div>
      <div class="dash-kpi-val ${howellCls[howell] || 'muted'}">${howellMap[howell] || howell}</div>
      <div class="dash-kpi-sub">Liquidité mondiale</div>
    </div>
  </div>

  <!-- Morning Brief signal -->
  <div class="dash-brief-card ${dir}">
    <div class="dash-brief-left">
      <div class="dash-brief-emoji">${dirEmoji[dir] || '➡️'}</div>
      <div>
        <div class="dash-brief-label" style="color:${dirColor}">${dirLabel[dir] || dir.toUpperCase()}</div>
        <div class="dash-brief-sub">Morning Brief — Conviction Claude</div>
      </div>
    </div>
    <div class="dash-brief-right">
      <div class="dash-conf-num" style="color:${dirColor}">${conf}%</div>
      <div class="dash-conf-bar-bg"><div class="dash-conf-bar-fill ${dir}" style="width:${conf}%"></div></div>
    </div>
  </div>
  ${brief?.summary ? `<div class="dash-brief-summary">${escHtml(brief.summary.slice(0, 180))}${brief.summary.length > 180 ? '…' : ''}</div>` : ''}

  <!-- Top 5 performers -->
  <div class="dash-section">
    <div class="dash-section-title">🏆 Top 5 Performers</div>
    <div id="dash-top5">${buildTop5Html(top5)}</div>
  </div>

  <!-- Banques Centrales résumé -->
  <div class="dash-section">
    <div class="dash-section-title">🏦 Banques Centrales (${cbList.length} actives)</div>
    <div class="dash-cb-row">
      <div class="dash-cb-chip hawkish">🦅 Hawkish : ${hawkish}</div>
      <div class="dash-cb-chip dovish">🕊 Dovish : ${dovish}</div>
      <div class="dash-cb-chip neutral">⚖ Neutre : ${cbList.length - hawkish - dovish}</div>
    </div>
    <div class="dash-cb-list">
      ${cbList.map(cb => {
        const s2 = cb.sentiment || 0;
        const c2 = s2 > 0.3 ? '#ff9944' : s2 < -0.3 ? '#4488ff' : 'var(--muted)';
        const lbl = s2 > 0.3 ? '▲' : s2 < -0.3 ? '▼' : '—';
        return `<div class="dash-cb-item">
          <span class="dash-cb-name">${escHtml(cb.name || '')}</span>
          <span style="color:${c2};font-weight:700">${lbl} ${Number(s2).toFixed(2)}</span>
        </div>`;
      }).join('')}
    </div>
  </div>

  <!-- Navigation rapide -->
  <div class="dash-section">
    <div class="dash-section-title">Navigation</div>
    <div class="dash-nav-grid">
      ${[
        ['protection', '🛡', 'Protection', 'Cash & Or'],
        ['croissance', '📈', 'Croissance', 'Traders A/B/C'],
        ['fiscalite',  '📋', 'Fiscalité', 'FSC-FRA/ALG'],
        ['intelligence','🧠','Intelligence','Actualités & IA'],
        ['retraite',   '🎯', 'Retraite', 'Projection 56 ans'],
        ['marches',    '🌍', 'Marchés', 'Géo EU/US/Asie'],
        ['secteurs',   '🏭', 'Secteurs', 'Énergie/Tech/Santé'],
        ['liquidite',  '💧', 'Liquidité', 'DSPX & Corr.'],
        ['morning-brief','🌅','Morning Brief','Actualités filtrées'],
      ].map(([tab, ic, name, sub]) => `
        <button class="dash-nav-btn" onclick="switchTab('${tab}')">
          <span class="dash-nav-icon">${ic}</span>
          <span class="dash-nav-name">${name}</span>
          <span class="dash-nav-sub">${sub}</span>
        </button>`).join('')}
    </div>
  </div>

</div>`;

  // Update black swan from bus state live
  const bsEl2 = qs('#black-swan-val');
  if (bsEl2) { bsEl2.textContent = bsLabel; bsEl2.className = `stat-value ${bsCls}`; }
}

// ═══════════════════════════════════════════════════════════════════
// TAB 2 — PILIER 1 : PROTECTION
// ═══════════════════════════════════════════════════════════════════

async function loadProtection(silent = false) {
  if (protectionLoaded && !silent) return;
  try {
    const [patRes, busRes] = await Promise.allSettled([
      fetch(`${API}/patrimoine`).then(r => r.json()),
      fetch(`${API}/bus/state`).then(r => r.json()),
    ]);
    const pat = patRes.status === 'fulfilled' ? patRes.value : null;
    const bus = busRes.status === 'fulfilled' ? busRes.value : null;
    protectionLoaded = true;
    renderProtection(pat, bus);
  } catch {
    if (!silent) qs('#protection-wrap').innerHTML = '<div class="error-state">Erreur chargement Protection.</div>';
  }
}

function renderProtection(pat, bus) {
  const actifs  = pat?.actifs || [];
  const total   = pat?.total_eur || 0;
  const halt    = bus?.black_swan_halt ?? false;
  const vix     = bus?.vix ?? null;
  const liqF    = bus?.liq_budget_factor ?? 1.0;

  // Actifs défensifs
  const cashActif = actifs.find(a => a.id === 'cash') || {};
  const orActif   = actifs.find(a => a.id === 'or_physique') || {};
  const dzdActif  = actifs.find(a => a.id === 'epargne_dzd') || {};

  const cashVal = cashActif.valeur_eur || 0;
  const orVal   = orActif.valeur_eur   || 0;
  const dzdVal  = dzdActif.valeur_eur  || 0;
  const totalDefensif = cashVal + orVal + dzdVal;
  const pctDefensif   = total > 0 ? (totalDefensif / total * 100).toFixed(1) : 0;

  // Black Swan score
  const vixLevel = vix != null ? Number(vix) : 0;
  const bsScore  = halt ? 0 : vixLevel >= 35 ? 2 : vixLevel >= 25 ? 5 : vixLevel >= 20 ? 7 : 9;
  const bsColor  = bsScore >= 7 ? 'var(--accent)' : bsScore >= 4 ? '#ff9944' : 'var(--red)';
  const bsLabel  = halt ? '🚨 HALT ACTIF' : vixLevel >= 35 ? '⚠ ALERTE' : vixLevel >= 25 ? '⚡ VIGILANCE' : '✅ SEREIN';

  // Howell
  const howell    = bus?.howell_regime || 'HOWELL_SEREIN';
  const howellMap = { HOWELL_SEREIN:'✅ SEREIN', HOWELL_ATTENTION:'⚠️ ATTENTION', HOWELL_VIGILANCE:'🟠 VIGILANCE', HOWELL_DANGER:'🚨 DANGER' };
  const howellRes = bus?.howell_resume || 'Signal liquidité mondiale';
  const howellCl  = { HOWELL_SEREIN:'serein', HOWELL_ATTENTION:'attention', HOWELL_VIGILANCE:'vigilance', HOWELL_DANGER:'danger' }[howell] || 'serein';

  // Expert signals
  const expSig    = bus?.expert_signals || {};
  const expKeys   = Object.keys(expSig).slice(0, 6);

  qs('#protection-wrap').innerHTML = `
<div class="prot-panel">

  <div class="prot-header">
    <div class="pillar-badge">PILIER 1</div>
    <div class="pillar-title">🛡 Protection — Capital défensif</div>
    <div class="pillar-sub">Cash · Or · Épargne DZD · Black Swan · Howell</div>
  </div>

  <!-- Score sécurité global -->
  <div class="prot-score-card">
    <div class="prot-score-label">SCORE SÉCURITÉ</div>
    <div class="prot-score-num" style="color:${bsColor}">${bsScore}/10</div>
    <div class="prot-score-regime">${bsLabel}</div>
    ${vix != null ? `<div class="prot-score-sub">VIX : <b style="color:${vixLevel>=30?'var(--red)':vixLevel>=20?'#ff9944':'var(--accent)'}">${vixLevel.toFixed(1)}</b> · Budget trade ×${liqF.toFixed(2)}</div>` : ''}
    <div class="prot-gauge-bg"><div class="prot-gauge-fill" style="width:${bsScore*10}%;background:${bsColor}"></div></div>
  </div>

  <!-- Actifs défensifs -->
  <div class="prot-card">
    <div class="prot-card-title">🏦 Actifs défensifs — ${fmt(totalDefensif, 0)} € (${pctDefensif}% du patrimoine)</div>
    <div class="prot-actif-row">
      <div class="prot-actif">
        <div class="prot-actif-icon">💶</div>
        <div class="prot-actif-name">Cash</div>
        <div class="prot-actif-val">${fmt(cashVal, 0)} €</div>
        <div class="prot-actif-pct">${total>0?(cashVal/total*100).toFixed(1):'0'}%</div>
      </div>
      <div class="prot-actif">
        <div class="prot-actif-icon">🥇</div>
        <div class="prot-actif-name">Or physique</div>
        <div class="prot-actif-val">${fmt(orVal, 0)} €</div>
        <div class="prot-actif-pct">${total>0?(orVal/total*100).toFixed(1):'0'}%</div>
      </div>
      <div class="prot-actif">
        <div class="prot-actif-icon">🇩🇿</div>
        <div class="prot-actif-name">Épargne DZD</div>
        <div class="prot-actif-val">${fmt(dzdVal, 0)} €</div>
        <div class="prot-actif-pct">${total>0?(dzdVal/total*100).toFixed(1):'0'}%</div>
      </div>
    </div>
    <div class="prot-bar-bg">
      <div class="prot-bar-fill" style="width:${pctDefensif}%;background:var(--accent)"></div>
    </div>
    <div style="font-size:.58rem;color:var(--muted);margin-top:6px">Patrimoine total : ${fmt(total, 0)} €</div>
  </div>

  <!-- Agent Black Swan -->
  <div class="prot-card">
    <div class="prot-card-title">🦢 Agent Black Swan — Surveillance VIX</div>
    ${halt ? '<div class="prot-halt-banner">🚨 HALT ACTIF — Tous les traders sont arrêtés (VIX ≥ 35)</div>' : ''}
    <div class="prot-bs-grid">
      <div class="prot-bs-item">
        <div class="prot-bs-label">VIX actuel</div>
        <div class="prot-bs-val" style="color:${vixLevel>=30?'var(--red)':vixLevel>=25?'#ff9944':'var(--accent)'}">${vix!=null?vixLevel.toFixed(1):'—'}</div>
      </div>
      <div class="prot-bs-item">
        <div class="prot-bs-label">Seuil HALT</div>
        <div class="prot-bs-val" style="color:var(--red)">≥ 35</div>
      </div>
      <div class="prot-bs-item">
        <div class="prot-bs-label">Seuil Reset</div>
        <div class="prot-bs-val" style="color:var(--accent)">≤ 30</div>
      </div>
      <div class="prot-bs-item">
        <div class="prot-bs-label">Budget trades</div>
        <div class="prot-bs-val" style="color:${liqF>=1?'var(--accent)':'#ff9944'}">×${liqF.toFixed(2)}</div>
      </div>
    </div>
    <div style="font-size:.58rem;color:var(--muted);margin-top:8px">Signal actualisé toutes les 20 ticks — données ^VIX via Yahoo Finance</div>
  </div>

  <!-- Signal Howell -->
  <div class="prot-card agd-howell ${howellCl}" style="border-radius:var(--radius);padding:14px">
    <div class="prot-card-title">🌊 Signal Howell — Liquidité mondiale</div>
    <div class="agd-howell-label" style="font-size:1rem;margin:8px 0">${howellMap[howell] || howell}</div>
    <div class="agd-howell-resume">${escHtml(howellRes)}</div>
    <div style="font-size:.58rem;color:var(--muted);margin-top:8px">Basé sur DXY (seuil 103) · VIX · EEM/SPY ratio · LiquidityClient</div>
  </div>

  <!-- Expert signals résumé -->
  ${expKeys.length ? `
  <div class="prot-card">
    <div class="prot-card-title">⚡ Signaux experts — Influence sur traders</div>
    ${expKeys.map(k => {
      const v = expSig[k] || 0;
      const vc = v > 0.3 ? 'var(--accent)' : v < -0.3 ? 'var(--red)' : 'var(--muted)';
      const bw = Math.min(Math.abs(v) * 50, 50).toFixed(1);
      return `<div class="prot-exp-row">
        <span class="prot-exp-name">${escHtml(k.replace(/_/g,' '))}</span>
        <div class="prot-exp-bar-bg">
          <div style="width:calc(50% + ${v>0?bw+'%':'0%'});height:100%;background:${v>0?'var(--accent)':'transparent'}"></div>
        </div>
        <span style="color:${vc};font-weight:700;min-width:40px;text-align:right">${v>=0?'+':''}${Number(v).toFixed(2)}</span>
      </div>`;
    }).join('')}
  </div>` : ''}

</div>`;
}

// ═══════════════════════════════════════════════════════════════════
// TAB 3 — PILIER 2 : CROISSANCE
// ═══════════════════════════════════════════════════════════════════

async function loadCroissance() {
  loadDivisions();
  if (state) renderCroissanceLeaderboard(state.leaderboard);
}

function renderCroissanceLeaderboard(traders) {
  if (!traders || !traders.length) return;
  const groupA = traders.filter(t => t.rank <= 10);
  const groupB = traders.filter(t => t.rank > 10 && t.rank <= 20);
  const groupC = traders.filter(t => t.rank > 20);
  function gStat(g) {
    const avg = g.reduce((s,t) => s+t.value, 0) / g.length;
    const pnl = g.reduce((s,t) => s+t.pnl, 0);
    const wins = g.filter(t => t.won).length;
    return { avg, pnl, wins };
  }
  const sA = gStat(groupA), sB = gStat(groupB), sC = gStat(groupC);
  const grEl = qs('#croissance-groups');
  if (grEl) {
    grEl.innerHTML = '<div class="cro-groups-row">' +
      [['Groupe A','Rang 1–10',sA,'group-a',groupA],
       ['Groupe B','Rang 11–20',sB,'group-b',groupB],
       ['Groupe C','Rang 21–30',sC,'group-c',groupC]].map(([label,sub,st,cls,grp]) =>
      '<div class="cro-group-card ' + cls + '">' +
      '<div class="cro-group-label">' + label + '</div>' +
      '<div class="cro-group-sub">' + sub + '</div>' +
      '<div class="cro-group-avg">€' + fmt(st.avg,0) + '</div>' +
      '<div class="cro-group-pnl ' + (st.pnl>=0?'green':'red') + '">' + (st.pnl>=0?'+':'') + '€' + fmt(Math.abs(st.pnl),0) + '</div>' +
      (st.wins > 0 ? '<div style="font-size:.55rem;color:var(--gold)">👑 ' + st.wins + '</div>' : '') +
      '<div class="cro-group-traders">' +
      grp.slice(0,4).map(t =>
        '<div class="cro-mini-trader"><span class="cro-mini-rank">' + rankIcon(t.rank) + '</span>' +
        '<span class="cro-mini-name">' + escHtml(t.name.split(" ")[0]) + '</span>' +
        '<span class="cro-mini-val" style="color:' + (t.pnl>=0?'var(--accent)':'var(--red)') + '">€' + fmt(t.value,0) + '</span></div>'
      ).join('') +
      (grp.length > 4 ? '<div style="font-size:.5rem;color:var(--muted);text-align:center">+' + (grp.length-4) + '</div>' : '') +
      '</div></div>').join('') +
      '</div>';
  }
  const container = qs('#leaderboard');
  if (!container) return;
  const existing = {};
  container.querySelectorAll('.card').forEach(el => { existing[el.dataset.id] = el; });
  traders.forEach(t => {
    let card = existing[t.id];
    const isNew = !card;
    if (isNew) {
      card = document.createElement('div');
      card.dataset.id = t.id;
      card.addEventListener('click', () => openModal(+card.dataset.id));
    }
    const prevValue = prevTraderValues.get(t.id);
    const changed = !isNew && prevValue !== undefined && prevValue !== t.value;
    const wentUp  = changed && t.value > prevValue;
    card.className = 'card' + (t.won ? ' won' : '');
    card.dataset.division = t.division || '';
    card.style.setProperty('--card-accent', divColor(t.division));
    card.innerHTML = cardHTML(t);
    container.appendChild(card);
    if (changed) {
      requestAnimationFrame(() => {
        card.classList.remove('flash-up','flash-down');
        void card.offsetWidth;
        card.classList.add(wentUp ? 'flash-up' : 'flash-down');
      });
    }
    prevTraderValues.set(t.id, t.value);
  });
  applyFilter();
}

function setFilter(divName) { activeFilter = (activeFilter === divName) ? null : divName; applyFilter(); }
function applyFilter() {
  const bar = qs('#filter-bar'), badge = qs('#filter-badge');
  if (!bar) return;
  if (activeFilter) {
    const dc = divColor(activeFilter);
    badge.innerHTML = '<span class="div-chip" style="--chip-color:' + dc + '">' + divIcon(activeFilter) + ' ' + escHtml(activeFilter) + '</span>';
    bar.classList.remove('hidden');
  } else { bar.classList.add('hidden'); }
  qsa('.card').forEach(c => c.classList.toggle('filtered-out', !!activeFilter && c.dataset.division !== activeFilter));
}

function updateDivisionChart() {
  const canvas = qs('#div-chart');
  if (!canvas) return;
  const wrap = canvas.parentElement;
  if (divisionHistory.size === 0) {
    if (!wrap.querySelector('.div-chart-empty')) {
      const msg = document.createElement('div'); msg.className = 'div-chart-empty'; msg.textContent = 'Accumulation des données…'; wrap.appendChild(msg);
    }
    return;
  }
  wrap.querySelector('.div-chart-empty')?.remove();
  const maxLen = Math.max(...Array.from(divisionHistory.values()).map(a => a.length));
  const labels = Array.from({length:maxLen}, (_,i) => i+1);
  const datasets = Array.from(divisionHistory.entries()).filter(([d]) => d !== 'Morning Brief').map(([d,vals]) => {
    const color = divColor(d);
    return {label:d, data:vals, borderColor:color, backgroundColor:color+'12', borderWidth:1.5, pointRadius:0, fill:false, tension:0.35};
  });
  if (divisionChart) { divisionChart.data.labels = labels; divisionChart.data.datasets = datasets; divisionChart.update('none'); return; }
  const monoFont = {size:9, family:"'JetBrains Mono','Courier New',monospace"};
  divisionChart = new Chart(canvas.getContext('2d'), {
    type:'line', data:{labels,datasets},
    options:{responsive:true, maintainAspectRatio:false, animation:false,
      plugins:{legend:{display:true,labels:{color:'#52526a',font:monoFont,boxWidth:10,padding:10}},
        tooltip:{mode:'index',intersect:false,callbacks:{label:ctx => ctx.dataset.label+': €'+ctx.parsed.y.toFixed(0)}}},
      scales:{x:{display:false},y:{ticks:{color:'#52526a',font:monoFont,callback:v=>'€'+v.toFixed(0)},grid:{color:'#222230'}}}}
  });
}

async function loadDivisions(silent = false) {
  if (divisionsLoaded && !silent) return;
  try {
    divisionsData = await (await fetch(API+'/divisions')).json();
    divisionsLoaded = true;
    renderDivisions(divisionsData);
  } catch {
    if (!silent) { const el = qs('#divisions-grid'); if (el) el.innerHTML = '<div class="error-state" style="grid-column:1/-1">Impossible de charger les divisions.</div>'; }
  }
}

function renderDivisions(divs) {
  const el = qs('#divisions-grid');
  if (!el) return;
  el.innerHTML = divs.filter(d => d.name !== 'Morning Brief').map(d => {
    const dc = d.color || divColor(d.name), ic = d.icon || divIcon(d.name);
    const pnlSign = d.avg_pnl >= 0 ? '+' : '', pnlCls = d.avg_pnl >= 0 ? 'green' : 'red';
    const progress = pct(d.avg_value);
    const bestTxt = d.best_trader ? '🥇 ' + escHtml(d.best_trader.name) + ' · €' + fmt(d.best_trader.value,0) : '';
    return '<div class="division-card" style="--div-color:' + dc + '" data-div="' + escHtml(d.name) + '">' +
      '<div class="div-card-header"><div class="div-card-icon">' + ic + '</div><div class="div-card-count">' + d.trader_count + ' traders</div></div>' +
      '<div class="div-card-name">' + escHtml(d.name) + '</div>' +
      '<div class="div-card-value">€' + fmt(d.avg_value,0) + '</div>' +
      '<div class="div-card-pnl ' + pnlCls + '">' + pnlSign + '€' + fmt(Math.abs(d.avg_pnl),0) + ' (' + pnlSign + d.avg_pnl_pct.toFixed(1) + '%)</div>' +
      '<div class="div-progress-bg"><div class="div-progress-fill" style="width:' + progress + '%;background:' + dc + '"></div></div>' +
      (bestTxt ? '<div class="div-card-best">' + bestTxt + '</div>' : '') +
      (d.wins > 0 ? '<div class="div-card-wins">👑 ' + d.wins + '</div>' : '') +
      '</div>';
  }).join('');
  el.querySelectorAll('.division-card').forEach(card => {
    card.addEventListener('click', () => { switchTab('croissance'); setFilter(card.dataset.div); });
  });
}

// ═══════════════════════════════════════════════════════════════════
// TAB 4 — PILIER 3 : FISCALITÉ
// ═══════════════════════════════════════════════════════════════════

async function loadFiscalite(silent = false) {
  if (fiscaliteLoaded && !silent) return;
  try {
    const d = await (await fetch(API+'/patrimoine')).json();
    fiscaliteLoaded = true;
    renderFiscalite(d);
  } catch {
    if (!silent) qs('#fiscalite-wrap').innerHTML = '<div class="error-state">Impossible de charger les données fiscales.</div>';
  }
}

function renderFiscalite(d) {
  const fisc    = d.fiscalite || {};
  const fscFra  = fisc.fsc_fra_01 || {};
  const peaFisc = fisc.pea   || {};
  const orFisc  = fscFra.or  || {};
  const orA     = orFisc.option_A || {};
  const orB     = orFisc.option_B || {};
  const stFisc  = fscFra.stellantis || {};
  const cfg     = d.config || {};
  const anneeRet= (cfg.annee_base || 2026) + ((cfg.age_retraite || 56) - (cfg.age_actuel || 35));
  const peaVal  = peaFisc.valeur || 0;

  qs('#fiscalite-wrap').innerHTML =
    '<div class="fisc-panel">' +
    '<div class="prot-header"><div class="pillar-badge">PILIER 3</div>' +
    '<div class="pillar-title">📋 Fiscalité — Optimisation légale</div>' +
    '<div class="pillar-sub">FSC-FRA-01 · FSC-ALG-02 · FSC-INT-03</div></div>' +

    // FSC-FRA-01
    '<div class="fisc-card"><div class="fisc-code-badge fra">FSC-FRA-01</div>' +
    '<div class="fisc-card-title">🇫🇷 Flat Tax PFU 30% — Or · Stellantis · Cash</div>' +
    '<div class="fisc-ref">' + escHtml(fscFra.reference || 'CGI Art. 200 A — PFU 30% = 12.8% IR + 17.2% PS') + '</div>' +
    '<div class="fisc-actif-section">' +
    '<div class="fisc-actif-label">🥇 ' + escHtml(orFisc.actif || 'Or physique') + '</div>' +
    '<div class="fisc-option"><span class="fisc-badge">Option A</span>' + escHtml(orA.nom || 'Taxe forfaitaire') + ' — <strong>' + fmt(orA.impot||0,2) + ' €</strong><div class="fisc-detail">' + escHtml(orA.detail||'') + '</div></div>' +
    '<div class="fisc-option"><span class="fisc-badge ' + (orB.exonere?'exonere':'') + '">Option B</span>' +
    (orB.exonere ? '<span class="green">EXONÉRÉ</span>' : 'Abattement ' + escHtml(orB.abattement_acquis||'') + ' acquis') +
    '<div class="fisc-detail">' + escHtml(orB.detail||'') + '</div></div>' +
    '<div class="fisc-conseil">' + escHtml(orFisc.conseil||'') + '</div></div>' +
    '<div class="fisc-actif-section"><div class="fisc-actif-label">🚗 ' + escHtml(stFisc.actif||'Stellantis') + '</div>' +
    '<div class="fisc-option">Dividendes : <strong>' + fmt(stFisc.dividendes_estimes||0,2) + ' €/an</strong> → PFU : <strong>' + fmt(stFisc.pfu_annuel||0,2) + ' €/an</strong></div>' +
    '<div class="fisc-detail">' + escHtml(stFisc.detail||'') + '</div></div></div>' +

    // PEA
    '<div class="fisc-card"><div class="fisc-code-badge fra">PEA</div>' +
    '<div class="fisc-card-title">📊 PEA — Plan d\'Épargne en Actions</div>' +
    '<div class="fisc-ref">' + escHtml(peaFisc.reference||'CGI Art. 163 quinquies D — Plafond 150 000 €') + '</div>' +
    '<div class="fisc-kpi-row">' +
    '<div class="fisc-kpi"><div class="fisc-kpi-lbl">Valeur PEA</div><div class="fisc-kpi-val accent">' + fmt(peaVal,0) + ' €</div></div>' +
    '<div class="fisc-kpi"><div class="fisc-kpi-lbl">Disponible</div><div class="fisc-kpi-val gold">' + fmt(peaFisc.dispo||0,0) + ' €</div></div>' +
    '<div class="fisc-kpi"><div class="fisc-kpi-lbl">Plafond</div><div class="fisc-kpi-val">150 000 €</div></div></div>' +
    '<div class="fisc-option"><span class="fisc-badge critique">Avant 5 ans</span>' + escHtml(peaFisc.avant_5ans||'IR 12.8% + PS 17.2%') + '</div>' +
    '<div class="fisc-option"><span class="fisc-badge exonere">Après 5 ans</span>' + escHtml(peaFisc.apres_5ans||'Exonéré IR — PS 17.2% uniquement') + '</div>' +
    (peaFisc.conseil||[]).map(c => '<div class="fisc-conseil">· ' + escHtml(c) + '</div>').join('') + '</div>' +

    // FSC-ALG-02
    '<div class="fisc-card"><div class="fisc-code-badge alg">FSC-ALG-02</div>' +
    '<div class="fisc-card-title">🇩🇿 Convention fiscale DZ-FR — Rapatriement DZD</div>' +
    '<div class="fisc-ref">Convention DZ-FR du 17/10/1999 — CERFA 3916 obligatoire</div>' +
    '<div class="fisc-kpi-row">' +
    '<div class="fisc-kpi"><div class="fisc-kpi-lbl">Plafond annuel</div><div class="fisc-kpi-val gold">15 000 €/an</div></div>' +
    '<div class="fisc-kpi"><div class="fisc-kpi-lbl">Frais virement</div><div class="fisc-kpi-val">3 – 7 %</div></div>' +
    '<div class="fisc-kpi"><div class="fisc-kpi-lbl">Déclaration</div><div class="fisc-kpi-val accent">CERFA 3916</div></div></div>' +
    '<div class="fisc-option"><span class="fisc-badge">Banques agréées</span>CPA · BEA · BNA · BADR</div>' +
    '<div class="fisc-option"><span class="fisc-badge">Double imposition</span>Évitée — Convention art. 18 : revenus imposés en France (résidence)</div>' +
    '<div class="fisc-option"><span class="fisc-badge">Obligations</span>Déclaration impots.gouv · CERFA 3916 tout compte étranger > 1 000 €</div>' +
    '<div class="fisc-conseil">Stratégie : rapatrier 15 000 €/an max → réinvestir en PEA ou SCPI.</div></div>' +

    // FSC-INT-03
    '<div class="fisc-card"><div class="fisc-code-badge int">FSC-INT-03</div>' +
    '<div class="fisc-card-title">🎯 Retraite 56 ans (' + anneeRet + ') — Stratégie fiscale intégrée</div>' +
    '<div class="fisc-ref">Optimisation multi-enveloppes — objectif revenu passif 500 €/mois dès ' + anneeRet + '</div>' +
    '<div class="fisc-actif-section"><div class="fisc-actif-label">📊 Ordre de liquidation optimal</div>' +
    '<div class="fisc-option"><span class="fisc-badge exonere">1. PEA (après 5 ans)</span>Retraits exonérés IR — PS 17.2% uniquement — priorité absolue</div>' +
    '<div class="fisc-option"><span class="fisc-badge">2. Or (après 22 ans)</span>Exonération totale — abattement annuel 5% par année de détention</div>' +
    '<div class="fisc-option"><span class="fisc-badge">3. CTO actions</span>PFU 30% ou barème progressif si TMI < 30% — abattement 40% dividendes éligibles</div>' +
    '<div class="fisc-option"><span class="fisc-badge">4. DZD rapatriement</span>15 000 €/an maximum — planifier sur plusieurs années</div></div>' +
    '<div class="fisc-actif-section"><div class="fisc-actif-label">💡 Optimisations clés</div>' +
    '<div class="fisc-option">· Maximiser PEA avant retraite (plafond 150 000 €) — croissance en franchise IR</div>' +
    '<div class="fisc-option">· Stellantis dans PEA : économie estimée +' + fmt(peaFisc.economie_stellantis_an||0,2) + ' €/an vs CTO</div>' +
    '<div class="fisc-option">· Micro-foncier locatif : abattement 30% si revenus < 15 000 €/an</div>' +
    '<div class="fisc-option">· IFI : seuil 1.3 M€ net — résidence principale exonérée à 30%</div></div></div>' +
    '</div>';
}

// ═══════════════════════════════════════════════════════════════════
// TAB 5 — PILIER 4 : INTELLIGENCE
// ═══════════════════════════════════════════════════════════════════

async function loadIntelligence(silent = false) {
  if (intelligenceLoaded && !silent) return;
  try {
    const [actuRes, dspxRes, corrRes, wlRes, comiteRes, screenerRes] = await Promise.allSettled([
      fetch(API+'/actualites').then(r => r.json()),
      fetch(API+'/dspx/etat').then(r => r.json()),
      fetch(API+'/correlations/actoblig').then(r => r.json()),
      fetch(API+'/investissement/watchlist').then(r => r.json()),
      fetch(API+'/comite-selection/historique').then(r => r.json()),
      fetch(API+'/investissement/screener').then(r => r.json()),
    ]);
    intelligenceLoaded = true;
    renderIntelligence(
      actuRes.status==='fulfilled'    ? actuRes.value    : null,
      dspxRes.status==='fulfilled'    ? dspxRes.value    : null,
      corrRes.status==='fulfilled'    ? corrRes.value    : null,
      wlRes.status==='fulfilled'      ? wlRes.value      : null,
      comiteRes.status==='fulfilled'  ? comiteRes.value  : null,
      screenerRes.status==='fulfilled'? screenerRes.value: null,
    );
  } catch {
    if (!silent) qs('#intelligence-wrap').innerHTML = '<div class="error-state">Erreur Intelligence.</div>';
  }
}

function renderIntelligence(actu, dspx, corr, wl, comite, screener) {
  const articles  = (actu?.articles || []).slice(0,10);
  const watchlist = wl?.watchlist || [];
  const nbBuy  = watchlist.filter(a => a.signal==='BUY').length;
  const nbHold = watchlist.filter(a => a.signal==='HOLD').length;
  const nbSell = watchlist.filter(a => a.signal==='SELL').length;
  const dspxVal = dspx?.dspx ?? null;
  const dspxReg = (dspx?.regime || '').toUpperCase();
  const dspxSig = dspx?.signal || '—';
  const dspxPct = dspx?.percentile_50j ?? null;
  const corrVal = corr?.correlation_20j ?? null;
  const corrReg = corr?.regime || '—';
  const corrInfla = corr?.inflation_us ?? null;
  const corrActifs= corr?.actifs_recommandes || [];
  const votes = (comite || []).slice(0,5);
  const nCls  = n => n==='CRITIQUE'?'critique':n==='IMPORTANT'?'important':'info';
  const dspxCol = dspxReg.includes('FORTE')?'var(--red)':dspxReg.includes('FAIBLE')?'var(--accent)':'#ff9944';

  let html = '<div class="intel-panel">' +
    '<div class="prot-header"><div class="pillar-badge">PILIER 4</div>' +
    '<div class="pillar-title">🧠 Intelligence — Division Research</div>' +
    '<div class="pillar-sub">Actualités filtrées · Corrélations IA · Watchlist · Comité</div></div>' +

    // Actualités
    '<div class="intel-card"><div class="intel-card-title">📰 Actualités filtrées — ' + articles.length + ' articles</div>' +
    (articles.length ? articles.map(a =>
      '<div class="intel-actu-item"><span class="intel-niveau ' + nCls(a.niveau) + '">' + a.niveau + '</span>' +
      '<div><div class="intel-actu-titre">' + escHtml(a.titre||'') + '</div>' +
      '<div class="intel-actu-src">' + escHtml(a.source||'') + ' · ' + _fmtTs(a.publie_a) + '</div></div></div>'
    ).join('') : '<div class="empty-state">Aucune actualité disponible</div>') +
    '<button class="agd-refresh-btn" id="intel-actu-refresh">↻ Actualiser</button></div>' +

    // DSPX
    '<div class="intel-card"><div class="intel-card-title">📊 Agent DSPX — Dispersion & Corrélations</div>' +
    (dspxVal != null ?
      '<div class="intel-dspx-row">' +
      '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">^DSPX</div><div class="intel-kpi-val">' + Number(dspxVal).toFixed(2) + '</div></div>' +
      '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Percentile 50j</div><div class="intel-kpi-val">' + (dspxPct!=null?dspxPct.toFixed(0)+'%':'—') + '</div></div>' +
      '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Régime</div><div class="intel-kpi-val" style="color:' + dspxCol + '">' + dspxReg + '</div></div>' +
      '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Signal</div><div class="intel-kpi-val gold">' + escHtml(dspxSig) + '</div></div>' +
      '</div>' +
      (dspx?.correlations ? '<div class="intel-corr-grid">' + Object.entries(dspx.correlations).map(([sym,val]) => {
        const v = Number(val), c = v>0.5?'#ff9944':v<0?'var(--accent)':'var(--muted)';
        return '<div class="intel-corr-item"><span>' + sym + '</span><span style="color:' + c + '">' + v.toFixed(2) + '</span></div>';
      }).join('') + '</div>' : '') +
      '<div style="font-size:.55rem;color:var(--muted);margin-top:6px">FORTE dispersion → stock-picking · FAIBLE → beta seul (ETF)</div>'
    : '<div class="empty-state">Données DSPX indisponibles</div>') +
    '</div>' +

    // Corrélations
    '<div class="intel-card"><div class="intel-card-title">📐 Corrélations Actions/Obligations (FRED)</div>' +
    (corrVal != null ?
      '<div class="intel-dspx-row">' +
      '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Corr. SPY/TLT 20j</div><div class="intel-kpi-val" style="color:' + (corrVal>0?'var(--red)':'var(--accent)') + '">' + corrVal.toFixed(2) + '</div></div>' +
      '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Régime</div><div class="intel-kpi-val">' + escHtml(corrReg) + '</div></div>' +
      '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Inflation US</div><div class="intel-kpi-val" style="color:' + (corrInfla!=null&&corrInfla>2.5?'var(--red)':'var(--muted)') + '">' + (corrInfla!=null?corrInfla.toFixed(1)+'%':'—') + '</div></div>' +
      '</div>' +
      (corrActifs.length ? '<div style="font-size:.62rem;color:var(--muted);margin-top:8px">Actifs recommandés : ' + corrActifs.map(a => '<span style="color:var(--accent)">' + a + '</span>').join(' · ') + '</div>' : '') +
      '<div style="font-size:.55rem;color:var(--muted);margin-top:4px">Corr > 0 + inflation > 2.5% → REGIME_INFLATION → rotation Or + Infrastructure</div>'
    : '<div class="empty-state">Données corrélations indisponibles</div>') +
    '</div>' +

    // Watchlist résumé
    '<div class="intel-card"><div class="intel-card-title">🔍 Watchlist — ' + watchlist.length + ' actifs · Pipeline Graham 17 étapes</div>' +
    '<div class="intel-wl-kpis">' +
    '<div class="intel-wl-kpi" style="background:#0d2010"><span class="green" style="font-size:1.2rem;font-weight:700">' + nbBuy + '</span><span style="font-size:.6rem">BUY</span></div>' +
    '<div class="intel-wl-kpi" style="background:#1e1e10"><span style="color:#facc15;font-size:1.2rem;font-weight:700">' + nbHold + '</span><span style="font-size:.6rem">HOLD</span></div>' +
    '<div class="intel-wl-kpi" style="background:#200d0d"><span style="color:#f87171;font-size:1.2rem;font-weight:700">' + nbSell + '</span><span style="font-size:.6rem">SELL</span></div>' +
    '</div>' +
    watchlist.filter(a => a.signal==='BUY').slice(0,5).map(a =>
      '<div class="intel-wl-row"><span class="intel-wl-ticker">' + a.ticker + '</span>' +
      '<span style="font-size:.6rem;color:var(--muted)">' + (a.nom||'') + '</span>' +
      '<span style="background:#1a3a1a;color:#4ade80;font-size:.6rem;padding:1px 6px;border-radius:3px;font-weight:700">BUY</span>' +
      '<span style="font-size:.6rem;color:var(--accent)">' + (a.score!=null?a.score.toFixed(1)+'/10':'') + '</span></div>'
    ).join('') + '</div>' +

    // Comité
    '<div class="intel-card"><div class="intel-card-title">🏛️ Comité Sélection — Votes 3/3</div>' +
    (votes.length ? votes.map(v => {
      const dec = v.decision || '?';
      const cls = dec.includes('CONFIRMÉ')?'confirm':dec.includes('VETO')?'veto':dec.includes('CONDITIONNEL')?'cond':'hold';
      const icon= dec.includes('CONFIRMÉ')?'✅':dec.includes('VETO')?'🛑':'🟡';
      const vStr= (v.votes||[]).map(vv => (vv.votant?.[0]||'?')+':'+(vv.vote==='OUI'?'✓':'✗')).join(' ');
      return '<div class="agd-vote-row"><span class="agd-vote-ticker">' + escHtml(v.ticker||'?') + '</span>' +
        '<span class="agd-vote-dec ' + cls + '">' + icon + ' ' + escHtml(dec) + '</span>' +
        '<span class="agd-vote-votes">' + escHtml(vStr) + '</span>' +
        '<span class="agd-vote-ts">' + _fmtTs(v.timestamp) + '</span></div>';
    }).join('') : '<div class="empty-state">Aucune séance enregistrée</div>') +
    '<div style="margin-top:12px;border-top:1px solid var(--surface2);padding-top:10px">' +
    '<div style="font-size:.58rem;color:var(--muted);margin-bottom:6px">Soumettre un ticker au Comité</div>' +
    '<div class="agd-form-row"><input id="intel-comite-ticker" class="agd-input" placeholder="Ex: VPK.AS" style="text-transform:uppercase" />' +
    '<button id="intel-comite-submit" class="agd-btn">Voter →</button></div>' +
    '<div id="intel-comite-result" class="agd-result"></div></div></div>' +

    // ── Screener Mondial ──────────────────────────────────────────
    (() => {
      const candidats  = screener?.candidats || [];
      const tsRun      = screener?.ts_run || null;
      const nbUnivers  = screener?.nb_univers || 150;
      let s = '<div class="intel-card"><div class="intel-card-title">🌍 Screener Mondial — Top Graham (' + nbUnivers + ' titres)</div>';
      s += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">';
      s += '<div style="font-size:.58rem;color:var(--muted)">Dernier scan : ' + (tsRun ? _fmtTs(tsRun) : 'Jamais effectué') + '</div>';
      s += '<button id="intel-screener-run" class="agd-refresh-btn" style="margin:0">▶ Lancer le screener</button>';
      s += '</div>';
      s += '<div id="intel-screener-status"></div>';
      if (candidats.length) {
        s += '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:.58rem">';
        s += '<thead><tr style="color:var(--muted);border-bottom:1px solid var(--surface2)">' +
          '<th style="text-align:left;padding:4px 3px">#</th>' +
          '<th style="text-align:left;padding:4px 3px">Ticker</th>' +
          '<th style="text-align:left;padding:4px 3px">Nom</th>' +
          '<th style="text-align:left;padding:4px 3px">Marché</th>' +
          '<th style="text-align:right;padding:4px 3px">Graham</th>' +
          '<th style="text-align:right;padding:4px 3px">PER</th>' +
          '<th style="text-align:right;padding:4px 3px">PBR</th>' +
          '<th style="text-align:right;padding:4px 3px">Div%</th>' +
          '</tr></thead><tbody>';
        candidats.forEach((c, i) => {
          const sc = c.score_graham != null ? c.score_graham : 0;
          const scColor = sc >= 60 ? 'var(--accent)' : sc >= 40 ? '#ff9944' : 'var(--muted)';
          s += '<tr style="border-top:1px solid var(--surface2)">' +
            '<td style="padding:4px 3px;color:var(--muted)">' + (i+1) + '</td>' +
            '<td style="padding:4px 3px;font-weight:700;color:var(--accent)">' + escHtml(c.ticker) + '</td>' +
            '<td style="padding:4px 3px">' + escHtml(c.nom || '') + '</td>' +
            '<td style="padding:4px 3px;color:var(--muted);font-size:.54rem">' + escHtml(c.marche || '') + '</td>' +
            '<td style="text-align:right;padding:4px 3px;color:' + scColor + ';font-weight:700">' + (c.score_graham != null ? c.score_graham.toFixed(1) : '—') + '</td>' +
            '<td style="text-align:right;padding:4px 3px">' + (c.per != null ? Number(c.per).toFixed(1) : '—') + '</td>' +
            '<td style="text-align:right;padding:4px 3px">' + (c.pbr != null ? Number(c.pbr).toFixed(2) : '—') + '</td>' +
            '<td style="text-align:right;padding:4px 3px;color:var(--accent)">' + (c.dividende != null ? Number(c.dividende).toFixed(1) + '%' : '—') + '</td>' +
            '</tr>';
        });
        s += '</tbody></table></div>';
      } else {
        s += '<div class="empty-state" style="padding:16px 0">Aucun scan effectué — lancez le screener pour voir les opportunités Graham.</div>';
      }
      s += '</div>';
      return s;
    })() +

    '</div>';

  qs('#intelligence-wrap').innerHTML = html;

  qs('#intel-actu-refresh')?.addEventListener('click', async () => {
    intelligenceLoaded = false; await loadIntelligence(true);
  });
  qs('#intel-comite-submit')?.addEventListener('click', async () => {
    const ticker = (qs('#intel-comite-ticker')?.value||'').trim().toUpperCase();
    if (!ticker) return;
    const btn = qs('#intel-comite-submit'); btn.disabled = true; btn.textContent = '⌛…';
    const resEl = qs('#intel-comite-result');
    try {
      const resp = await fetch(API+'/comite-selection/voter', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker})});
      const data = await resp.json();
      if (resEl) { resEl.className = 'agd-result show valide'; resEl.textContent = data.decision || '?'; }
      intelligenceLoaded = false;
      setTimeout(() => loadIntelligence(true), 1500);
    } catch(e) {
      if (resEl) { resEl.className = 'agd-result show veto'; resEl.textContent = 'Erreur: '+e.message; }
    } finally { btn.disabled = false; btn.textContent = 'Voter →'; }
  });

  qs('#intel-screener-run')?.addEventListener('click', async () => {
    const btn    = qs('#intel-screener-run');
    const statEl = qs('#intel-screener-status');
    btn.disabled = true; btn.textContent = '⌛ Scan en cours…';
    if (statEl) { statEl.className = 'agd-result show valide'; statEl.textContent = '⏳ Scan lancé — ~2 min pour ' + (screener?.nb_univers||150) + ' titres. Revenez actualiser dans 2 min.'; }
    try {
      await fetch(API+'/investissement/screener/run', {method:'POST'});
    } catch(e) {
      if (statEl) { statEl.className = 'agd-result show veto'; statEl.textContent = 'Erreur: '+e.message; }
    } finally {
      setTimeout(() => {
        const b = qs('#intel-screener-run');
        if (b) { b.disabled = false; b.textContent = '▶ Lancer le screener'; }
      }, 5000);
    }
  });
}

// ═══════════════════════════════════════════════════════════════════
// TAB 6 — PILIER 5 : RETRAITE
// ═══════════════════════════════════════════════════════════════════

async function loadRetraite(silent = false) {
  if (retraiteLoaded && !silent) return;
  try {
    const [patRes, divRes] = await Promise.allSettled([
      fetch(API+'/patrimoine').then(r => r.json()),
      fetch(API+'/dividendes').then(r => r.json()),
    ]);
    retraiteLoaded = true;
    renderRetraite(
      patRes.status==='fulfilled' ? patRes.value : null,
      divRes.status==='fulfilled' ? divRes.value : null,
    );
  } catch {
    if (!silent) qs('#retraite-wrap').innerHTML = '<div class="error-state">Erreur Retraite.</div>';
  }
}

function renderRetraite(d, divData) {
  if (!d) { qs('#retraite-wrap').innerHTML = '<div class="error-state">Données patrimoine indisponibles.</div>'; return; }
  const actifs   = d.actifs   || [];
  const total    = d.total_eur || 0;
  const proj     = d.projection || [];
  const apports  = d.apports  || [];
  const cfg      = d.config   || {};
  const valRet   = d.valeur_retraite || 0;
  const anneeRet = (cfg.annee_base||2026) + ((cfg.age_retraite||56) - (cfg.age_actuel||35));
  const apportMens = d.apport_mensuel_effectif || cfg.apport_mensuel || 500;
  const pctRet   = Math.min(100, (total / (valRet||500000) * 100)).toFixed(1);

  const revMensuel = divData?.revenu_mensuel_total || 0;
  const revAnnuel  = divData?.revenu_annuel_total  || 0;
  const ecartObj   = divData?.ecart_objectif ?? (revMensuel - 500);
  const ecartCls   = ecartObj >= 0 ? 'pos' : 'neg';

  const divPositions = (divData?.positions || []).filter(p => (p.rev_annuel||0) > 0).sort((a,b) => (b.rev_annuel||0)-(a.rev_annuel||0)).slice(0,8);
  const divCoupes    = (divData?.positions || []).filter(p => p.coupe_detectee);

  const apportsHtml = apports.length === 0
    ? '<div style="color:var(--muted);font-size:.78rem;text-align:center;padding:16px">Aucun apport enregistré</div>'
    : apports.slice(0,8).map(a =>
        '<div class="pat-apport-row"><span class="pat-apport-date">' + (a.date||'—') + '</span>' +
        '<span class="pat-apport-note">' + escHtml(a.note||'Apport') + '</span>' +
        '<span class="pat-apport-montant">+' + fmt(a.montant,0) + ' €</span></div>'
      ).join('');

  qs('#retraite-wrap').innerHTML =
    '<div class="ret-panel">' +
    '<div class="prot-header"><div class="pillar-badge">PILIER 5</div>' +
    '<div class="pillar-title">🎯 Retraite — Objectif 56 ans (' + anneeRet + ')</div>' +
    '<div class="pillar-sub">Projection patrimoine · Dividendes passifs · Apports mensuels</div></div>' +

    // KPIs
    '<div class="pat-kpi-row">' +
    '<div class="pat-kpi"><div class="pat-kpi-label">PATRIMOINE ACTUEL</div><div class="pat-kpi-val" style="color:var(--accent)">' + fmt(total,0) + ' €</div></div>' +
    '<div class="pat-kpi"><div class="pat-kpi-label">OBJECTIF RETRAITE</div><div class="pat-kpi-val" style="color:var(--gold)">' + fmt(valRet,0) + ' €</div><div class="pat-kpi-sub">' + anneeRet + '</div></div>' +
    '<div class="pat-kpi"><div class="pat-kpi-label">APPORT MENSUEL</div><div class="pat-kpi-val">' + fmt(apportMens,0) + ' €<span style="font-size:.6rem;color:var(--muted)">/mois</span></div></div>' +
    '<div class="pat-kpi"><div class="pat-kpi-label">PROGRESSION</div><div class="pat-kpi-val" style="color:var(--accent)">' + pctRet + '%</div></div>' +
    '</div>' +

    // Barre progression
    '<div class="ret-prog-card">' +
    '<div style="font-size:.6rem;color:var(--muted);margin-bottom:6px">Progression vers objectif retraite ' + (cfg.age_retraite||56) + ' ans</div>' +
    '<div class="ret-prog-bar"><div class="ret-prog-fill" style="width:' + pctRet + '%"></div></div>' +
    '<div style="display:flex;justify-content:space-between;font-size:.6rem;color:var(--muted);margin-top:4px">' +
    '<span>' + fmt(total,0) + ' € actuel</span><span>' + fmt(valRet,0) + ' € objectif</span></div>' +
    '</div>' +

    // Graphiques
    '<div class="pat-charts-row">' +
    '<div class="pat-card" style="flex:1;min-width:0"><div class="pat-card-title">📈 Projection ' + ((cfg.taux_annuel||0.1)*100) + '%/an</div>' +
    '<div style="position:relative;height:220px"><canvas id="ret-proj-chart"></canvas></div></div>' +
    '<div class="pat-card" style="width:200px;flex-shrink:0"><div class="pat-card-title">🥧 Répartition</div>' +
    '<div style="position:relative;height:220px;display:flex;align-items:center;justify-content:center"><canvas id="ret-pie-chart"></canvas></div></div>' +
    '</div>' +

    // Dividendes
    '<div class="pat-card">' +
    '<div class="pat-card-title">💰 Revenus passifs — Dividendes</div>' +
    (divCoupes.length ? '<div class="agd-coupe-alert">🚨 COUPE DÉTECTÉE : ' + divCoupes.map(c=>c.ticker).join(', ') + '</div>' : '') +
    '<div class="agd-div-kpi">' +
    '<div class="agd-div-kpi-cell"><div class="agd-div-kpi-val">' + fmt(revMensuel,0) + '€</div><div class="agd-div-kpi-lbl">/ mois</div></div>' +
    '<div class="agd-div-kpi-cell"><div class="agd-div-kpi-val">' + fmt(revAnnuel,0) + '€</div><div class="agd-div-kpi-lbl">/ an</div></div>' +
    '<div class="agd-div-kpi-cell"><div class="agd-div-kpi-val" style="color:' + (ecartCls==='pos'?'var(--accent)':'var(--red)') + '">' + (ecartObj>=0?'+':'') + ecartObj.toFixed(0) + '€</div><div class="agd-div-kpi-lbl">vs obj 500€/m</div></div>' +
    '</div>' +
    (divPositions.length ? divPositions.map(p =>
      '<div class="agd-div-row"><span class="agd-div-ticker">' + escHtml(p.ticker) + '</span>' +
      '<span style="font-size:.62rem;color:var(--muted)">' + escHtml(p.nom||'') + '</span>' +
      '<span class="agd-div-rev">' + fmt(p.rev_annuel,0) + '€/an</span>' +
      '<span class="agd-div-score">' + (p.scoring?.score??'—') + '/10</span></div>'
    ).join('') : '<div style="font-size:.7rem;color:var(--muted);padding:6px">Données dividendes indisponibles</div>') +
    '</div>' +

    // Apports
    '<div class="pat-card">' +
    '<div class="pat-card-header"><div class="pat-card-title">💵 Suivi des apports</div>' +
    '<button class="pat-btn-add" id="ret-add-apport-btn">＋ Ajouter</button></div>' +
    '<div class="pat-apports-list">' + apportsHtml + '</div>' +
    '</div>' +

    '</div>';

  // Draw charts
  _drawRetPie(actifs, total);
  _drawRetProj(proj, cfg);

  qs('#ret-add-apport-btn')?.addEventListener('click', () => {
    qs('#apport-overlay').classList.remove('hidden');
    qs('#apport-montant').focus();
  });
}

function _destroyRetChart(key) {
  if (_retraiteCharts[key]) { _retraiteCharts[key].destroy(); _retraiteCharts[key] = null; }
}

function _drawRetPie(actifs, total) {
  _destroyRetChart('pie');
  const ctx = qs('#ret-pie-chart'); if (!ctx) return;
  const items = actifs.filter(a => (a.valeur_eur||0) > 0);
  _retraiteCharts.pie = new Chart(ctx, {
    type:'doughnut',
    data:{labels:items.map(a=>a.nom), datasets:[{data:items.map(a=>a.valeur_eur),backgroundColor:items.map(a=>a.couleur||'#888'),borderWidth:2,borderColor:'#0a0a0f'}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'60%',
      plugins:{legend:{position:'bottom',labels:{color:'#dddded',font:{size:9},padding:6,boxWidth:10}},
        tooltip:{callbacks:{label:ctx2=>' '+ctx2.label+': '+fmt(ctx2.parsed,0)+' €'}}}},
  });
}

function _drawRetProj(proj, cfg) {
  _destroyRetChart('proj');
  const ctx = qs('#ret-proj-chart'); if (!ctx) return;
  const labels = proj.map(p => p.annee);
  const total  = proj.map(p => p.valeur);
  const growth = proj.map(p => p.croissance);
  const apps   = proj.map(p => p.apports_cumules);
  const retIdx = (cfg.age_retraite||56) - (cfg.age_actuel||35);
  _retraiteCharts.proj = new Chart(ctx, {
    type:'line',
    data:{labels, datasets:[
      {label:'Total',data:total,borderColor:'#ffd700',backgroundColor:'rgba(255,215,0,.08)',borderWidth:2,fill:true,tension:0.3,pointRadius:ctx2=>ctx2.dataIndex===retIdx?6:2,pointBackgroundColor:ctx2=>ctx2.dataIndex===retIdx?'#ff4466':'#ffd700'},
      {label:'Croissance',data:growth,borderColor:'#00e5a0',borderWidth:1.5,borderDash:[4,3],fill:false,tension:0.3,pointRadius:0},
      {label:'Apports',data:apps,borderColor:'#b44cff',borderWidth:1.5,borderDash:[2,4],fill:false,tension:0.3,pointRadius:0},
    ]},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{legend:{labels:{color:'#dddded',font:{size:9},boxWidth:10}},
        tooltip:{callbacks:{title:items=>{const yr=items[0]?.label;return yr==String((cfg.annee_base||2026)+retIdx)?yr+' 🎯 Retraite':''+yr;},label:c=>' '+c.dataset.label+': '+fmt(c.parsed.y,0)+' €'}}},
      scales:{
        x:{ticks:{color:ctx2=>ctx2.tick?.label==String((cfg.annee_base||2026)+retIdx)?'#ff4466':'#52526a',font:{size:9}},grid:{color:'#1e1e2a'}},
        y:{ticks:{color:'#52526a',font:{size:9},callback:v=>v>=1000?(v/1000).toFixed(0)+'k€':v+'€'},grid:{color:'#1e1e2a'}},
      }},
  });
}

// ═══════════════════════════════════════════════════════════════════
// TAB 7 — MARCHÉS (vue géographique)
// ═══════════════════════════════════════════════════════════════════

const REGION_CB = {
  'EU':       ['BCE','SNB','NORGES','RIKSBANK','BOE'],
  'Americas': ['FED','BOC','BCB'],
  'Asie':     ['BOJ','PBC','RBI','RBA','BOK'],
  'Emergents':['TCMB','SARB','CBN','SAMA','CBUAE'],
  'Intl':     ['FMI','BRI'],
};
const REGION_META = {
  'EU':       { icon:'🇪🇺', color:'#4488ff', indices:'CAC40 · DAX · AEX · FTSE', desc:'Zone Euro + UK + Nordiques' },
  'Americas': { icon:'🌎', color:'#00e5a0', indices:'S&P500 · NASDAQ · Dow · TSX', desc:'USA · Canada · Brésil' },
  'Asie':     { icon:'🌏', color:'#ffd700', indices:'Nikkei · Hang Seng · Nifty · ASX', desc:'Japon · Chine · Inde · Australie' },
  'Emergents':{ icon:'🌍', color:'#ff6b35', indices:'MSCI EM · EEM · BIST · JSE', desc:'Turquie · Afrique du Sud · Golfe' },
  'Intl':     { icon:'🌐', color:'#b44cff', indices:'FMI · BRI · BM', desc:'Institutions mondiales' },
};

async function loadMarches(silent = false) {
  if (marchesLoaded && !silent) return;
  try {
    const [busRes, cioRes] = await Promise.allSettled([
      fetch(API+'/bus/state').then(r => r.json()),
      fetch(API+'/cio/allocation').then(r => r.json()),
    ]);
    marchesLoaded = true;
    renderMarches(
      busRes.status==='fulfilled' ? busRes.value : null,
      cioRes.status==='fulfilled' ? cioRes.value : null,
    );
  } catch {
    if (!silent) qs('#marches-wrap').innerHTML = '<div class="error-state">Erreur Marchés.</div>';
  }
}

function renderMarches(bus, cio) {
  const cbSignals = bus?.central_banks || {};
  const regime    = cio?.regime || '—';
  const alloc     = cio?.allocation || {};
  const regimeCls = regime==='RISK_ON'?'green':regime==='RISK_OFF'?'red':'muted';
  const regimeIcon= regime==='RISK_ON'?'🟢':regime==='RISK_OFF'?'🔴':'🟡';

  // Build region cards
  const regionCards = Object.entries(REGION_CB).map(([region, codes]) => {
    const meta = REGION_META[region] || {};
    const cbs  = codes.map(c => cbSignals[c]).filter(Boolean);
    const avgSent = cbs.length ? cbs.reduce((s,c) => s+(c.sentiment||0),0)/cbs.length : null;
    const sentColor = avgSent==null?'var(--muted)':avgSent>0.3?'#ff9944':avgSent<-0.3?'#4488ff':'var(--muted)';
    const sentLabel = avgSent==null?'—':avgSent>0.3?'🦅 Hawkish':avgSent<-0.3?'🕊 Dovish':'⚖ Neutre';
    const topCB = cbs.sort((a,b) => Math.abs(b.sentiment||0)-Math.abs(a.sentiment||0)).slice(0,2);
    return '<div class="mkt-region-card" style="--region-color:'+meta.color+'">' +
      '<div class="mkt-region-header">' +
      '<span class="mkt-region-icon">' + meta.icon + '</span>' +
      '<div><div class="mkt-region-name">' + region + '</div><div class="mkt-region-desc">' + meta.desc + '</div></div>' +
      '</div>' +
      '<div class="mkt-region-indices">' + meta.indices + '</div>' +
      '<div class="mkt-region-sent" style="color:'+sentColor+'">' + sentLabel + '</div>' +
      (avgSent!=null ? '<div class="mkt-region-sent-num" style="color:'+sentColor+'">' + (avgSent>=0?'+':'') + avgSent.toFixed(2) + '</div>' : '') +
      (topCB.length ? '<div class="mkt-region-cbs">' + topCB.map(cb => {
        const sc = cb.sentiment||0;
        const cc = sc>0.3?'#ff9944':sc<-0.3?'#4488ff':'var(--muted)';
        return '<div class="mkt-cb-row"><span class="mkt-cb-name">' + escHtml(cb.name||cb.code||'') + '</span>' +
          (cb.rate!=null?'<span class="mkt-cb-rate">'+Number(cb.rate).toFixed(2)+'%</span>':'') +
          '<span style="color:'+cc+';font-weight:700">' + (sc>=0?'+':'') + sc.toFixed(2) + '</span></div>';
      }).join('') + '</div>' : '') +
      '</div>';
  }).join('');

  // CIO allocation macro
  const allocEntries = Object.entries(alloc);
  const allocHtml = allocEntries.length ? allocEntries.map(([k,v]) => {
    const w = Math.min(Number(v)||0, 100);
    const c = k==='or'?'#ffd700':k==='cash'?'var(--accent)':k.includes('oblig')?'#4488ff':k.includes('action')?'#00e5a0':'#ff6b35';
    return '<div class="mkt-alloc-row">' +
      '<span class="mkt-alloc-label">' + k + '</span>' +
      '<div class="mkt-alloc-bar-bg"><div class="mkt-alloc-bar-fill" style="width:'+w+'%;background:'+c+'"></div></div>' +
      '<span class="mkt-alloc-pct" style="color:'+c+'">' + Number(v).toFixed(0) + '%</span>' +
      '</div>';
  }).join('') : '<div class="empty-state">Données CIO indisponibles</div>';

  // Short signals
  const shorts = cio?.short_signals || [];
  const shortHtml = shorts.length ? '<div class="mkt-short-alert">⚠ SHORT signals: ' + shorts.join(' · ') + '</div>' : '';

  qs('#marches-wrap').innerHTML =
    '<div class="mkt-panel">' +
    '<div class="mkt-header">' +
    '<div class="mkt-regime ' + regimeCls + '">' + regimeIcon + ' CIO Regime: ' + regime + '</div>' +
    '<div style="font-size:.58rem;color:var(--muted)">Allocation macro dynamique — ' + (cio?.updated_at ? _fmtTs(cio.updated_at) : 'cache') + '</div>' +
    '</div>' +
    shortHtml +
    '<div class="mkt-alloc-section">' +
    '<div class="intel-card-title">📊 Allocation CIO macro</div>' +
    allocHtml +
    '</div>' +
    '<div class="intel-card-title" style="margin:12px 16px 8px">🌍 Marchés par zone géographique</div>' +
    '<div class="mkt-regions-grid">' + regionCards + '</div>' +
    '</div>';
}

// ═══════════════════════════════════════════════════════════════════
// TAB 8 — SECTEURS
// ═══════════════════════════════════════════════════════════════════

const SECTEUR_META = [
  { id:'energie',  icon:'⚡', label:'Énergie',  desc:'Pétrole · Gaz · Renouvelables', tickers:'XOM · CVX · TTE.PA · SU.PA' },
  { id:'tech',     icon:'💻', label:'Tech',     desc:'Logiciel · Semi-conducteurs · IA', tickers:'MSFT · NVDA · GOOGL · AAPL' },
  { id:'finance',  icon:'🏦', label:'Finance',  desc:'Banques · Assurances · Asset Mgmt', tickers:'JPM · BNP.PA · AXA.PA · GS' },
  { id:'sante',    icon:'🏥', label:'Santé',    desc:'Pharma · Biotech · Dispositifs médicaux', tickers:'JNJ · RDSA · SAN.PA · MRK' },
  { id:'defense',  icon:'🛡', label:'Défense',  desc:'Aérospatiale · Sécurité · Cyber', tickers:'LMT · RTX · AIR.PA · BA' },
];

async function loadSecteurs(silent = false) {
  if (secteursLoaded && !silent) return;
  try {
    const [cioRes, bertezRes] = await Promise.allSettled([
      fetch(API+'/cio/allocation').then(r => r.json()),
      fetch(API+'/bertez/analyse').then(r => r.json()),
    ]);
    secteursLoaded = true;
    renderSecteurs(
      cioRes.status==='fulfilled' ? cioRes.value : null,
      bertezRes.status==='fulfilled' ? bertezRes.value : null,
    );
  } catch {
    if (!silent) qs('#secteurs-wrap').innerHTML = '<div class="error-state">Erreur Secteurs.</div>';
  }
}

function renderSecteurs(cio, bertez) {
  const regime = cio?.regime || 'NEUTRAL';
  const alloc  = cio?.allocation || {};
  const shorts = cio?.short_signals || [];

  // Bertez
  const wtiVal   = bertez?.wti_price ?? null;
  const bMode    = bertez?.mode || '—';
  const bSig     = bertez?.signal ?? null;
  const bThese   = bertez?.these || '—';
  const bModeCls = bMode==='STAGFLATION'?'red':bMode==='REFLATION'?'green':'muted';

  // Sector scores based on regime + Bertez
  function sectorScore(secteurId) {
    let score = 5;
    if (regime==='RISK_ON')  { if (secteurId==='tech') score=8; if (secteurId==='finance') score=7; if (secteurId==='sante') score=4; }
    if (regime==='RISK_OFF') { if (secteurId==='sante') score=8; if (secteurId==='defense') score=7; if (secteurId==='tech') score=3; }
    if (bMode==='STAGFLATION') { if (secteurId==='energie') score=9; if (secteurId==='tech') score=Math.max(score-2,1); }
    if (bMode==='REFLATION')   { if (secteurId==='energie') score=7; if (secteurId==='finance') score=8; }
    return score;
  }

  const secteurCards = SECTEUR_META.map(s => {
    const score = sectorScore(s.id);
    const scoreColor = score>=7?'var(--accent)':score>=5?'#ff9944':'var(--red)';
    const recLabel = score>=7?'SURPONDÉRER':score>=5?'PONDÉRATION NEUTRE':'SOUS-PONDÉRER';
    const recCls   = score>=7?'green':score>=5?'muted':'red';
    return '<div class="sect-card">' +
      '<div class="sect-header"><span class="sect-icon">' + s.icon + '</span>' +
      '<div><div class="sect-label">' + s.label + '</div><div class="sect-desc">' + s.desc + '</div></div>' +
      '<div class="sect-score" style="color:'+scoreColor+'">' + score + '/10</div>' +
      '</div>' +
      '<div class="sect-tickers">' + s.tickers + '</div>' +
      '<div class="sect-rec ' + recCls + '">' + recLabel + '</div>' +
      '<div class="sect-bar-bg"><div class="sect-bar-fill" style="width:' + (score*10) + '%;background:' + scoreColor + '"></div></div>' +
      '</div>';
  }).join('');

  qs('#secteurs-wrap').innerHTML =
    '<div class="sect-panel">' +
    '<div class="mkt-header">' +
    '<div class="mkt-regime ' + (regime==='RISK_ON'?'green':regime==='RISK_OFF'?'red':'muted') + '">' +
    (regime==='RISK_ON'?'🟢':regime==='RISK_OFF'?'🔴':'🟡') + ' Régime CIO: ' + regime +
    '</div></div>' +

    // Bertez
    '<div class="intel-card">' +
    '<div class="intel-card-title">⚡ Signal Bertez — Énergie & Macro WTI</div>' +
    '<div class="intel-dspx-row">' +
    '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">WTI</div><div class="intel-kpi-val">' + (wtiVal!=null?'$'+Number(wtiVal).toFixed(1):'—') + '</div></div>' +
    '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Mode</div><div class="intel-kpi-val ' + bModeCls + '">' + bMode + '</div></div>' +
    '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Signal</div><div class="intel-kpi-val">' + (bSig!=null?(bSig>=0?'+':'')+Number(bSig).toFixed(3):'—') + '</div></div>' +
    '</div>' +
    '<div style="font-size:.62rem;color:var(--muted);margin-top:6px">' + escHtml(bThese) + '</div>' +
    (shorts.length ? '<div class="mkt-short-alert" style="margin-top:8px">⚠ SHORT: ' + shorts.join(' · ') + '</div>' : '') +
    '</div>' +

    '<div class="intel-card-title" style="margin:8px 16px">🏭 Allocation sectorielle recommandée</div>' +
    '<div class="sect-grid">' + secteurCards + '</div>' +
    '</div>';
}

// ═══════════════════════════════════════════════════════════════════
// TAB 9 — LIQUIDITÉ (amélioré avec DSPX + corrélations)
// ═══════════════════════════════════════════════════════════════════

async function loadLiquidite(silent = false) {
  if (liquiditeLoaded && !silent) return;
  try {
    const [liqRes, dspxRes, corrRes, busRes] = await Promise.allSettled([
      fetch(API+'/liquidite').then(r => r.json()),
      fetch(API+'/dspx/etat').then(r => r.json()),
      fetch(API+'/correlations/actoblig').then(r => r.json()),
      fetch(API+'/bus/state').then(r => r.json()),
    ]);
    liquiditeLoaded = true;
    renderLiquidite(
      liqRes.status==='fulfilled'  ? liqRes.value  : null,
      dspxRes.status==='fulfilled' ? dspxRes.value : null,
      corrRes.status==='fulfilled' ? corrRes.value : null,
      busRes.status==='fulfilled'  ? busRes.value  : null,
    );
  } catch {
    if (!silent) qs('#liquidite-wrap').innerHTML = '<div class="error-state">Impossible de charger la liquidité.</div>';
  }
}

function renderLiquidite(d, dspx, corr, bus) {
  if (!d) { qs('#liquidite-wrap').innerHTML = '<div class="error-state">Données liquidité indisponibles.</div>'; return; }
  const score    = d.global_liquidity_score;
  const regime   = (d.regime || 'neutre').toLowerCase();
  const hasScore = score !== null && score !== undefined;
  const regimeLabel = {critique:'CRITIQUE',tendu:'TENDU',neutre:'NEUTRE',ample:'AMPLE',abondant:'ABONDANT'};
  const scoreColor = !hasScore?'#52526a':score<3?'#ff4466':score<5?'#ff9944':score<6.5?'#aaaacc':score<8?'#00e5a0':'#ffd700';
  const biasVal  = hasScore ? (score-5)/5 : 0;
  const biasStr  = (biasVal>=0?'+':'')+biasVal.toFixed(2);
  const biasDesc = biasVal>0.3?'Risk-ON — positions élargies':biasVal<-0.3?'Risk-OFF — positions réduites':'Neutre';
  const gaugeW   = hasScore ? Math.min(100, score/10*100).toFixed(1) : 0;

  // Bertez card
  const bSig = d.bertez_signal, bMode = d.bertez_mode, bSum = (d.agent_summaries||{})['Bertez_Energy']||'';
  const hasBertez = bSig !== null && bSig !== undefined;
  const modeRegime = {DEFENSIF:'critique',NEUTRE:'neutre',OFFENSIF:'ample'}[bMode]||'neutre';
  const sigColor = !hasBertez?'var(--muted)':bSig>0?'var(--accent)':bSig<0?'var(--red)':'var(--muted)';
  const sigStr   = hasBertez?(bSig>=0?'+':'')+Number(bSig).toFixed(3):'—';
  const gaugePos = hasBertez&&bSig>0?Math.min(bSig*50,50).toFixed(1):'0';
  const gaugeNeg = hasBertez&&bSig<0?Math.min(-bSig*50,50).toFixed(1):'0';

  const agentsHtml = Object.entries(d.agent_scores||{}).map(([agent,sc]) => {
    const agColor = sc<3?'#ff4466':sc<5?'#ff9944':sc<6.5?'#aaaacc':sc<8?'#00e5a0':'#ffd700';
    const agW = (sc/10*100).toFixed(1);
    const summary = escHtml((d.agent_summaries||{})[agent]||'');
    return '<div class="liq-agent-row" title="'+summary+'">' +
      '<div class="liq-agent-name">'+escHtml(agent.replace(/_/g,' '))+'</div>' +
      '<div class="liq-agent-bar-bg"><div class="liq-agent-bar-fill" style="width:'+agW+'%;background:'+agColor+'"></div></div>' +
      '<div class="liq-agent-score" style="color:'+agColor+'">'+Number(sc).toFixed(1)+'</div></div>';
  }).join('');

  const alertsHtml = (d.alerts||[]).map(a => {
    const cls = a.startsWith('ALERTE')?'liq-alert-critique':'liq-alert-signal';
    return '<div class="liq-alert '+cls+'">'+escHtml(a)+'</div>';
  }).join('');

  // DSPX section
  const dspxVal = dspx?.dspx ?? null;
  const dspxReg = (dspx?.regime||'').toUpperCase();
  const dspxPct = dspx?.percentile_50j ?? null;
  const corrVal = corr?.correlation_20j ?? null;
  const corrInfla = corr?.inflation_us ?? null;
  const corrReg = corr?.regime || '—';
  const corrActifs = corr?.actifs_recommandes || [];

  const ts = d.timestamp
    ? new Date(d.timestamp+(d.timestamp.endsWith('Z')?'':'Z')).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit',second:'2-digit'})
    : '—';

  qs('#liquidite-wrap').innerHTML =
    '<div class="liq-panel">' +

    // Score global
    '<div class="liq-score-card">' +
    '<div class="liq-score-label">SCORE LIQUIDITÉ GLOBAL</div>' +
    '<div class="liq-score-num" style="color:'+scoreColor+'">'+(hasScore?Number(score).toFixed(1):'—')+'</div>' +
    '<div class="liq-score-label">/ 10</div>' +
    '<div class="liq-regime regime-'+regime+'">'+(regimeLabel[regime]||regime.toUpperCase())+'</div>' +
    '<div class="liq-gauge-wrap"><div class="liq-gauge"><div class="liq-gauge-fill" style="width:'+gaugeW+'%;background:'+scoreColor+'"></div></div></div>' +
    '<div class="liq-trader-impact">Biais traders : <span style="color:'+scoreColor+';font-weight:700">'+biasStr+'</span> &nbsp;·&nbsp;'+biasDesc+'</div>' +
    '</div>' +

    // Bertez
    '<div class="bertez-card">' +
    '<div class="liq-section-title">⚡ Signal Bertez — Économie / Énergie</div>' +
    '<div class="bertez-header"><div class="liq-regime regime-'+modeRegime+'">'+(bMode||'INCONNU')+'</div>' +
    '<div class="bertez-signal-num" style="color:'+sigColor+'">'+sigStr+'</div>' +
    '<div style="font-size:.52rem;color:var(--muted);font-family:var(--font-mono)">[-1 / +1]</div></div>' +
    '<div class="bertez-gauge-labels"><span>DÉFENSIF ◄</span><span>NEUTRE</span><span>► OFFENSIF</span></div>' +
    '<div class="bertez-gauge-track"><div class="bertez-gauge-center"></div>' +
    '<div class="bertez-gauge-pos" style="width:'+gaugePos+'%"></div>' +
    '<div class="bertez-gauge-neg" style="width:'+gaugeNeg+'%"></div></div>' +
    '<div class="bertez-axis-labels"><span>-1</span><span>0</span><span>+1</span></div>' +
    (bSum?'<div class="bertez-summary">'+escHtml(bSum)+'</div>':'') +
    '</div>' +

    // DSPX amélioré
    (dspxVal!=null ? '<div class="liq-card">' +
    '<div class="liq-section-title">📊 DSPX Dispersion — Corrélations Asie</div>' +
    '<div class="intel-dspx-row">' +
    '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">^DSPX</div><div class="intel-kpi-val">'+Number(dspxVal).toFixed(2)+'</div></div>' +
    '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Percentile</div><div class="intel-kpi-val">'+(dspxPct!=null?dspxPct.toFixed(0)+'%':'—')+'</div></div>' +
    '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Régime</div><div class="intel-kpi-val" style="color:'+(dspxReg.includes('FORTE')?'var(--red)':dspxReg.includes('FAIBLE')?'var(--accent)':'#ff9944')+'">'+dspxReg+'</div></div>' +
    '</div>' +
    (dspx?.correlations?'<div class="intel-corr-grid">'+Object.entries(dspx.correlations).map(([sym,val])=>{
      const v=Number(val),c=v>0.5?'#ff9944':v<0?'var(--accent)':'var(--muted)';
      return '<div class="intel-corr-item"><span>'+sym+'</span><span style="color:'+c+'">'+v.toFixed(2)+'</span></div>';
    }).join('')+'</div>':'') +
    '</div>' : '') +

    // Corrélations actions/obligations
    (corrVal!=null ? '<div class="liq-card">' +
    '<div class="liq-section-title">📐 Corrélations Actions/Obligations</div>' +
    '<div class="intel-dspx-row">' +
    '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Corr 20j</div><div class="intel-kpi-val" style="color:'+(corrVal>0?'var(--red)':'var(--accent)')+'">'+corrVal.toFixed(2)+'</div></div>' +
    '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Régime</div><div class="intel-kpi-val">'+escHtml(corrReg)+'</div></div>' +
    '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Inflation US</div><div class="intel-kpi-val" style="color:'+(corrInfla!=null&&corrInfla>2.5?'var(--red)':'var(--muted)')+'">'+( corrInfla!=null?corrInfla.toFixed(1)+'%':'—')+'</div></div>' +
    '</div>' +
    (corrActifs.length?'<div style="font-size:.62rem;color:var(--muted);margin-top:6px">Actifs recommandés : '+corrActifs.map(a=>'<span style="color:var(--accent)">'+a+'</span>').join(' · ')+'</div>':'') +
    '</div>' : '') +

    // Agents
    (agentsHtml?'<div class="liq-card"><div class="liq-section-title">Scores par agent (8 sources)</div><div class="liq-agents">'+agentsHtml+'</div></div>':'') +
    (alertsHtml?'<div class="liq-card"><div class="liq-section-title">Alertes &amp; Signaux</div><div class="liq-alerts">'+alertsHtml+'</div></div>':'') +

    // Bus inter-agent
    (() => {
      if (!bus) return '';
      const busHalt  = bus.black_swan_halt ?? false;
      const busVix   = bus.vix ?? null;
      const busLiqF  = bus.liq_budget_factor ?? 1.0;
      const busHowell= bus.howell_regime || '—';
      const howellTxt= { HOWELL_SEREIN:'✅ SEREIN', HOWELL_ATTENTION:'⚠ ATTENTION', HOWELL_VIGILANCE:'🟠 VIGILANCE', HOWELL_DANGER:'🚨 DANGER' }[busHowell] || busHowell;
      const vixColor = busVix!=null&&busVix>=30?'var(--red)':busVix!=null&&busVix>=20?'#ff9944':'var(--accent)';
      const liqFColor= busLiqF>=1.0?'var(--accent)':'#ff9944';
      const cbActifs = Object.values(bus.central_banks||{}).filter(c=>Math.abs(c.sentiment||0)>=0.3).length;
      const expActifs= Object.values(bus.expert_signals||{}).filter(v=>Math.abs(v||0)>=0.55).length;
      const busBusStats = bus.bus_stats || {};
      const nbMsg = busBusStats.total_messages || '—';
      return '<div class="liq-card"><div class="liq-section-title">⚙️ Bus inter-agent — Influence systémique</div>' +
        '<div class="intel-dspx-row">' +
        '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Black Swan</div><div class="intel-kpi-val" style="color:'+(busHalt?'var(--red)':'var(--accent)')+'">'+(busHalt?'🚨 HALT':'✅ OK')+'</div></div>' +
        '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">VIX</div><div class="intel-kpi-val" style="color:'+vixColor+'">'+(busVix!=null?Number(busVix).toFixed(1):'—')+'</div></div>' +
        '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Budget ×</div><div class="intel-kpi-val" style="color:'+liqFColor+'">'+busLiqF.toFixed(2)+'</div></div>' +
        '</div>' +
        '<div class="intel-dspx-row" style="margin-top:8px">' +
        '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Howell</div><div class="intel-kpi-val" style="font-size:.6rem">'+howellTxt+'</div></div>' +
        '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">CB actives</div><div class="intel-kpi-val">'+cbActifs+'</div></div>' +
        '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Experts</div><div class="intel-kpi-val">'+expActifs+'</div></div>' +
        '</div>' +
        (nbMsg!=='—'?'<div style="font-size:.52rem;color:var(--muted);margin-top:6px">Messages bus: '+nbMsg+'</div>':'') +
        '</div>';
    })() +

    '<div class="liq-timestamp">Données: '+ts+'</div>' +
    '<button class="liq-refresh-btn" id="liq-refresh-btn">↻ Actualiser la liquidité</button>' +
    '</div>';

  qs('#liq-refresh-btn')?.addEventListener('click', async () => {
    if (_liqRefreshing) return;
    _liqRefreshing = true;
    const btn = qs('#liq-refresh-btn');
    btn.textContent = '⌛ Refresh en cours…'; btn.disabled = true;
    try {
      await fetch(API+'/liquidite/refresh', {method:'POST'});
      await new Promise(r => setTimeout(r,4000));
      liquiditeLoaded = false;
      await loadLiquidite();
    } catch {}
    finally {
      _liqRefreshing = false;
      const b = qs('#liq-refresh-btn');
      if (b) { b.textContent = '↻ Actualiser la liquidité'; b.disabled = false; }
    }
  });
}

// ═══════════════════════════════════════════════════════════════════
// TAB 10 — MORNING BRIEF (amélioré)
// ═══════════════════════════════════════════════════════════════════

async function loadMorningBrief(silent = false) {
  if (morningBriefLoaded && !silent) return;
  try {
    const [briefRes, actuRes, pmRes, benchRes, rpRes] = await Promise.allSettled([
      fetch(API+'/brief').then(r => r.json()),
      fetch(API+'/actualites').then(r => r.json()),
      fetch(API+'/post-market').then(r => r.json()),
      fetch(API+'/benchmark').then(r => r.json()),
      fetch(API+'/risk-parity').then(r => r.json()),
    ]);
    morningBriefLoaded = true;
    renderMorningBrief(
      briefRes.status==='fulfilled' ? briefRes.value : null,
      actuRes.status==='fulfilled'  ? actuRes.value  : null,
      pmRes.status==='fulfilled'    ? pmRes.value     : null,
      benchRes.status==='fulfilled' ? benchRes.value  : null,
      rpRes.status==='fulfilled'    ? rpRes.value     : null,
    );
  } catch {
    if (!silent) qs('#morning-brief-wrap').innerHTML = '<div class="error-state">Erreur Morning Brief.</div>';
  }
}

function renderMorningBrief(brief, actu, pm, bench, rp) {
  const dir    = (brief?.direction || 'neutral').toLowerCase();
  const conf   = Math.round((brief?.confidence || 0.5) * 100);
  const emojis = {bullish:'📈',bearish:'📉',neutral:'➡️'};
  const labels = {bullish:'HAUSSIER',bearish:'BAISSIER',neutral:'NEUTRE'};
  const today  = new Date().toLocaleDateString('fr-FR',{weekday:'long',year:'numeric',month:'long',day:'numeric'});
  const dirColor = dir==='bullish'?'var(--accent)':dir==='bearish'?'var(--red)':'var(--muted)';

  // Actualités critiques/importantes
  const articles   = (actu?.articles || []);
  const critiques  = articles.filter(a => a.niveau==='CRITIQUE').slice(0,5);
  const importantes = articles.filter(a => a.niveau==='IMPORTANT').slice(0,5);
  const nCls = n => n==='CRITIQUE'?'critique':n==='IMPORTANT'?'important':'info';

  // Post-market
  const totalPnlSign = (pm?.total_pnl||0) >= 0 ? '+' : '';
  const totalPnlCls  = (pm?.total_pnl||0) >= 0 ? 'green' : 'red';
  const top5pm = (pm?.top5||[]).slice(0,3).map((t,i) =>
    '<div class="pm-trader-row"><div class="pm-rank-num">'+rankIcon(i+1)+'</div>' +
    '<div class="pm-trader-name">'+escHtml(t.name)+'</div>' +
    '<div class="pm-trader-pnl '+(t.pnl>=0?'green':'red')+'">'+(t.pnl>=0?'+':'')+'€'+fmt(Math.abs(t.pnl),0)+'</div></div>'
  ).join('');

  qs('#morning-brief-wrap').innerHTML =
    '<div class="brief-panel">' +
    '<div class="brief-date">'+today+'</div>' +
    '<div class="brief-title">MORNING BRIEF — KING FUND</div>' +

    // Direction signal
    '<div class="brief-direction '+dir+'">' +
    '<div class="brief-dir-emoji">'+(emojis[dir]||'➡️')+'</div>' +
    '<div class="brief-dir-info">' +
    '<div class="brief-dir-label '+dir+'">'+(labels[dir]||dir.toUpperCase())+'</div>' +
    '<div class="brief-dir-conf">Conviction Claude</div>' +
    '</div>' +
    '<div class="brief-conf-pct" style="color:'+dirColor+'">'+conf+'%</div>' +
    '</div>' +
    '<div class="brief-conf-bar"><div class="brief-conf-fill '+dir+'" style="width:'+conf+'%"></div></div>' +

    // Résumé
    '<div class="brief-summary-card">' +
    '<div class="brief-summary-src"><div class="brief-summary-dot"></div>Claude · Analyse du marché</div>' +
    '<p class="brief-summary-text">'+escHtml(brief?.summary || 'Aucune analyse disponible.')+'</p>' +
    (!brief?.summary || brief.summary==='API unavailable' ? '<p class="brief-no-key">Clé API Anthropic non configurée.</p>' : '') +
    '</div>' +

    // Actualités critiques
    (critiques.length ? '<div class="liq-card" style="margin-top:12px"><div class="liq-section-title">🚨 Actualités CRITIQUES</div>' +
    critiques.map(a =>
      '<div class="intel-actu-item"><span class="intel-niveau critique">CRITIQUE</span>' +
      '<div><div class="intel-actu-titre">'+escHtml(a.titre||'')+'</div>' +
      '<div class="intel-actu-src">'+escHtml(a.source||'')+' · '+_fmtTs(a.publie_a)+'</div></div></div>'
    ).join('') + '</div>' : '') +

    // Actualités importantes
    (importantes.length ? '<div class="liq-card" style="margin-top:8px"><div class="liq-section-title">⚠️ Actualités IMPORTANTES</div>' +
    importantes.map(a =>
      '<div class="intel-actu-item"><span class="intel-niveau important">IMPORTANT</span>' +
      '<div><div class="intel-actu-titre">'+escHtml(a.titre||'')+'</div>' +
      '<div class="intel-actu-src">'+escHtml(a.source||'')+' · '+_fmtTs(a.publie_a)+'</div></div></div>'
    ).join('') + '</div>' : '') +

    // Benchmark vs indices
    (() => {
      if (!bench) return '';
      const portPerfs = bench.portfolio?.performances || {};
      const alpha     = bench.alpha_reel || {};
      const portSharpe= bench.portfolio?.sharpe ?? null;
      const portDD    = bench.portfolio?.max_drawdown ?? null;
      const benchList = Object.values(bench.benchmarks || {});
      const periodes  = ['1j','1s','1m','YTD'];
      const fmtPerf   = v => v==null ? '—' : (v>=0?'<span style="color:var(--accent)">+'+v.toFixed(1)+'%</span>':'<span style="color:var(--red)">'+v.toFixed(1)+'%</span>');
      const fmtAlpha  = v => v==null ? '—' : (v>=0?'<span style="color:var(--accent)">+'+v.toFixed(1)+'pp</span>':'<span style="color:var(--red)">'+v.toFixed(1)+'pp</span>');
      let html = '<div class="liq-card" style="margin-top:8px"><div class="liq-section-title">📐 Benchmark — Alpha vs Indices</div>';
      // Portfolio KPIs
      html += '<div class="intel-dspx-row" style="margin-bottom:6px">';
      html += '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Perf totale</div><div class="intel-kpi-val">'+fmtPerf(portPerfs.total??null)+'</div></div>';
      html += '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Sharpe</div><div class="intel-kpi-val">'+(portSharpe!=null?Number(portSharpe).toFixed(2):'—')+'</div></div>';
      html += '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Max DD</div><div class="intel-kpi-val" style="color:var(--red)">'+(portDD!=null?portDD.toFixed(1)+'%':'—')+'</div></div>';
      html += '</div>';
      // Alpha par benchmark
      if (Object.keys(alpha).length) {
        html += '<div class="intel-dspx-row">';
        for (const [label, av] of Object.entries(alpha)) {
          html += '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">α '+label+'</div><div class="intel-kpi-val">'+fmtAlpha(av)+'</div></div>';
        }
        html += '</div>';
      }
      // Tableau benchmarks
      if (benchList.length) {
        html += '<div style="overflow-x:auto;margin-top:8px"><table style="width:100%;border-collapse:collapse;font-size:.58rem">';
        html += '<thead><tr style="color:var(--muted)"><th style="text-align:left;padding:3px 4px">Indice</th>';
        periodes.forEach(p => { html += '<th style="text-align:right;padding:3px 4px">'+p+'</th>'; });
        html += '<th style="text-align:right;padding:3px 4px">DD</th></tr></thead><tbody>';
        benchList.filter(b=>!b.erreur).forEach(b => {
          html += '<tr style="border-top:1px solid var(--surface2)"><td style="padding:3px 4px;font-weight:700">'+b.label+'</td>';
          periodes.forEach(p => { html += '<td style="text-align:right;padding:3px 4px">'+fmtPerf((b.performances||{})[p]??null)+'</td>'; });
          html += '<td style="text-align:right;padding:3px 4px;color:var(--red)">'+(b.max_drawdown!=null?b.max_drawdown.toFixed(1)+'%':'—')+'</td>';
          html += '</tr>';
        });
        html += '</tbody></table></div>';
      }
      html += '</div>';
      return html;
    })() +

    // Risk Parity Dalio
    (() => {
      if (!rp) return '';
      const classes   = rp.classes || [];
      const volPort   = rp.vol_portefeuille_pct ?? null;
      const nbDeseq   = rp.nb_desequilibres ?? 0;
      const rebals    = (rp.rebalancement || []).slice(0, 4);
      const contCible = rp.contribution_cible_pct ?? null;
      const statusCls = { OK:'var(--accent)', WARNING:'#ff9944', CRITIQUE:'var(--red)' };
      let html = '<div class="liq-card" style="margin-top:8px"><div class="liq-section-title">⚖️ Risk Parity Dalio — All Weather</div>';
      html += '<div class="intel-dspx-row" style="margin-bottom:6px">';
      html += '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Vol portefeuille</div><div class="intel-kpi-val">'+(volPort!=null?volPort.toFixed(1)+'%':'—')+'</div></div>';
      html += '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Déséquilibres</div><div class="intel-kpi-val" style="color:'+(nbDeseq>0?'var(--red)':'var(--accent)')+'">'+nbDeseq+'</div></div>';
      html += '<div class="intel-dspx-kpi"><div class="intel-kpi-lbl">Cible/classe</div><div class="intel-kpi-val">'+(contCible!=null?contCible.toFixed(1)+'%':'—')+'</div></div>';
      html += '</div>';
      // Classes d'actif
      if (classes.length) {
        html += '<div style="display:flex;flex-direction:column;gap:4px;margin-top:4px">';
        classes.forEach(c => {
          const contW = Math.min(c.contribution_risque_pct||0, 100).toFixed(1);
          const sc = statusCls[c.statut] || 'var(--muted)';
          html += '<div style="display:flex;align-items:center;gap:6px;font-size:.58rem">' +
            '<span style="width:100px;color:var(--muted)">'+(c.classe||'').replace(/_/g,' ')+'</span>' +
            '<div style="flex:1;background:var(--surface2);border-radius:2px;height:6px">' +
            '<div style="width:'+contW+'%;height:6px;background:'+sc+';border-radius:2px"></div></div>' +
            '<span style="width:38px;text-align:right;color:'+sc+'">'+Number(c.contribution_risque_pct||0).toFixed(1)+'%</span>' +
            '<span style="width:28px;text-align:right;color:var(--muted)">'+(c.statut!=='OK'?'⚠':'')+'</span>' +
            '</div>';
        });
        html += '</div>';
      }
      // Rééquilibrage
      if (rebals.length) {
        html += '<div style="margin-top:8px;font-size:.58rem;color:var(--muted)">Rééquilibrage suggéré :</div>';
        rebals.forEach(r => {
          const dc = r.action==='AUGMENTER'?'var(--accent)':'var(--red)';
          html += '<div style="font-size:.6rem;display:flex;gap:6px;margin-top:2px">' +
            '<span style="color:'+dc+';font-weight:700">'+(r.action==='AUGMENTER'?'▲':'▼')+' '+escHtml(r.ticker)+'</span>' +
            '<span style="color:var(--muted)">'+escHtml(r.classe||'').replace(/_/g,' ')+'</span>' +
            '<span style="color:'+dc+';margin-left:auto">'+(r.delta_pct>=0?'+':'')+r.delta_pct.toFixed(1)+'pp</span>' +
            '</div>';
        });
      }
      html += '</div>';
      return html;
    })() +

    // Post-market résumé
    (pm ? '<div class="liq-card" style="margin-top:8px"><div class="liq-section-title">📊 Post-Market — Jour '+pm.battle_day+'/30</div>' +
    '<div class="pm-kpis">' +
    '<div class="pm-kpi"><div class="pm-kpi-val">€'+fmt(pm.avg_value,0)+'</div><div class="pm-kpi-lbl">Moyenne</div></div>' +
    '<div class="pm-kpi"><div class="pm-kpi-val '+totalPnlCls+'">'+totalPnlSign+'€'+fmt(Math.abs(pm.total_pnl),0)+'</div><div class="pm-kpi-lbl">P&L Total</div></div>' +
    '<div class="pm-kpi"><div class="pm-kpi-val green">€'+fmt(pm.max_value,0)+'</div><div class="pm-kpi-lbl">Meilleur</div></div>' +
    '<div class="pm-kpi"><div class="pm-kpi-val red">€'+fmt(pm.min_value,0)+'</div><div class="pm-kpi-lbl">Pire</div></div>' +
    '</div>' +
    (top5pm ? '<div style="margin-top:8px"><div style="font-size:.6rem;color:var(--muted);margin-bottom:6px">Top 3</div>' + top5pm + '</div>' : '') +
    '</div>' : '') +

    '<button class="liq-refresh-btn" id="brief-refresh-btn" style="margin:12px 0">↻ Actualiser le Brief</button>' +
    '</div>';

  qs('#brief-refresh-btn')?.addEventListener('click', async () => {
    morningBriefLoaded = false;
    const btn = qs('#brief-refresh-btn');
    if (btn) { btn.textContent = '⌛…'; btn.disabled = true; }
    await loadMorningBrief(true);
    const b = qs('#brief-refresh-btn');
    if (b) { b.textContent = '↻ Actualiser le Brief'; b.disabled = false; }
  });
}

// ═══════════════════════════════════════════════════════════════════
// SPARKLINE / CARD HELPERS
// ═══════════════════════════════════════════════════════════════════

function makeSvgSparkline(values, color) {
  if (values.length < 3) return '';
  const W=72,H=26,PAD=2;
  const min=Math.min(...values),max=Math.max(...values),range=max-min||1;
  const pts=values.map((v,i)=>{
    const x=PAD+(i/(values.length-1))*(W-PAD*2);
    const y=H-PAD-((v-min)/range)*(H-PAD*2);
    return x.toFixed(1)+','+y.toFixed(1);
  }).join(' ');
  return '<svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" fill="none"><polyline points="'+pts+'" stroke="'+color+'" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>';
}

function sitgClass(b) { return b>1.05?'sitg-bull':b<0.95?'sitg-bear':'sitg-neut'; }
function sitgLabel(b) { const a=b>1.05?'▲':b<0.95?'▼':'—'; return a+' ×'+b.toFixed(2); }
const GRADE_META = {
  RECRUE:  {cls:'grade-recrue', icon:'⚔️'}, JUNIOR:  {cls:'grade-junior', icon:'🔰'},
  SENIOR:  {cls:'grade-senior', icon:'⭐'}, ELITE:   {cls:'grade-elite',  icon:'💎'},
  LÉGENDE: {cls:'grade-legende',icon:'👑'},
};
function gradeClass(g) { return GRADE_META[g]?.cls||'grade-recrue'; }
function gradeLabel(g) { const m=GRADE_META[g]; return m?m.icon+' '+g:g||'RECRUE'; }

function cardHTML(t) {
  const pp=pct(t.value),sign=t.pnl>=0?'+':'',pnlCls=t.pnl>=0?'green':'red',fillCls=t.won?' gold':t.pnl<0?' red':'';
  const dc=divColor(t.division),spkArr=sparklineData.get(t.id)||[];
  const spkColor=t.pnl>=0?'#00e5a0':'#ff4466',spkSvg=makeSvgSparkline(spkArr,spkColor);
  const sitg=t.sitg_budget??1.0,grade=t.grade||'RECRUE';
  return '<div class="card-top"><div class="card-rank">'+rankIcon(t.rank)+'</div>' +
    '<div class="card-info"><div class="card-name">'+escHtml(t.name)+(t.won?'<span class="won-badge">WINNER</span>':'')+
    '</div><div class="card-meta"><span class="card-strategy">'+escHtml(t.strategy)+'</span>' +
    '<span class="div-chip" style="--chip-color:'+dc+'">'+divIcon(t.division)+' '+escHtml(t.division)+'</span></div></div>' +
    '<div class="card-right">'+(spkSvg?'<div class="card-sparkline">'+spkSvg+'</div>':'')+
    '<div class="card-value">€'+fmt(t.value,0)+'</div>' +
    '<div class="card-pnl '+pnlCls+'">'+sign+'€'+fmt(Math.abs(t.pnl),0)+' ('+sign+t.pnl_pct+'%)</div>' +
    '<div class="grade-pill '+gradeClass(grade)+'">'+gradeLabel(grade)+'</div>' +
    '<div class="sitg-pill '+sitgClass(sitg)+'">'+sitgLabel(sitg)+'</div>' +
    '</div></div><div class="progress-bg"><div class="progress-fill'+fillCls+'" style="width:'+pp+'%"></div></div>';
}

function rankIcon(r) {
  if (r===1) return '🥇'; if (r===2) return '🥈'; if (r===3) return '🥉';
  return '<span class="num">#'+r+'</span>';
}

// ═══════════════════════════════════════════════════════════════════
// TRADER MODAL
// ═══════════════════════════════════════════════════════════════════

function openModal(id) { activeTraderId=id; qs('#overlay').classList.remove('hidden'); document.body.style.overflow='hidden'; refreshModal(); }
function closeModal() { qs('#overlay').classList.add('hidden'); document.body.style.overflow=''; if (modalChart){modalChart.destroy();modalChart=null;} activeTraderId=null; }

async function refreshModal() {
  try { const data = await (await fetch(API+'/trader/'+activeTraderId)).json(); renderModal(data); } catch {}
}

function renderModal(data) {
  const ts  = state?.leaderboard.find(t => t.id===data.id);
  const pnl = data.value-START;
  const sign= pnl>=0?'+':'', cls=pnl>=0?'green':'red';
  qs('#modal-name').textContent     = data.name;
  qs('#modal-strategy').textContent = data.strategy;
  qs('#modal-rank-badge').textContent= ts?(ts.rank<=3?rankIcon(ts.rank):'#'+ts.rank):'';
  const div=ts?.division||'',dc=divColor(div);
  qs('#modal-div-row').innerHTML=div?'<span class="div-chip" style="--chip-color:'+dc+'">'+divIcon(div)+' '+escHtml(div)+'</span>':'';
  qs('#modal-value').textContent='€'+fmt(data.value,2);
  qs('#modal-pnl').innerHTML='<span class="'+cls+'">'+sign+'€'+fmt(Math.abs(pnl),2)+' ('+sign+((pnl/START)*100).toFixed(2)+'%)</span>';
  const sitg=data.sitg_budget??ts?.sitg_budget??1.0,grade=data.grade??ts?.grade??'RECRUE';
  qs('#modal-sitg-value').innerHTML='<span class="'+sitgClass(sitg)+'">'+sitgLabel(sitg)+'</span>';
  qs('#modal-grade-value').innerHTML='<span class="'+gradeClass(grade)+'">'+gradeLabel(grade)+'</span>';
  const pp=pct(data.value),fill=qs('#modal-progress');
  fill.style.width=pp+'%';
  fill.className='progress-fill'+(data.value>=TARGET?' gold':pnl<0?' red':'');
  qs('#modal-progress-pct').textContent=pp.toFixed(1)+'%';
  renderChart(data.history||[]);
  renderPositions(data.positions||{},data.cash??0);
  renderTrades(data.trades||[]);
}

function renderChart(history) {
  if (modalChart){modalChart.destroy();modalChart=null;}
  if (history.length<2) return;
  const labels=history.map(h=>h.timestamp.slice(11,16)),values=history.map(h=>h.portfolio_value);
  const isUp=values.at(-1)>=values[0],color=isUp?'#00e5a0':'#ff4466';
  const monoFont={size:10,family:"'JetBrains Mono','Courier New',monospace"};
  modalChart=new Chart(qs('#modal-chart').getContext('2d'),{
    type:'line',data:{labels,datasets:[{data:values,borderColor:color,borderWidth:2,pointRadius:0,fill:true,backgroundColor:color+'18',tension:0.35}]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false,callbacks:{label:ctx=>'€'+ctx.parsed.y.toFixed(2)}}},
      scales:{x:{ticks:{color:'#52526a',maxTicksLimit:6,font:monoFont},grid:{color:'#222230'}},
              y:{ticks:{color:'#52526a',font:monoFont,callback:v=>'€'+v.toFixed(0)},grid:{color:'#222230'}}}},
  });
}

function renderPositions(positions,cash) {
  const el=qs('#modal-positions'),entries=Object.entries(positions).filter(([,qty])=>qty>0);
  const cashRow='<div class="position-row"><span class="pos-symbol">💶 CASH</span><span class="pos-qty">€'+fmt(cash,2)+'</span></div>';
  if (!entries.length){el.innerHTML=cashRow+'<div class="empty-state">Pas de positions ouvertes</div>';return;}
  el.innerHTML=cashRow+entries.map(([sym,qty])=>'<div class="position-row"><span class="pos-symbol">'+sym+'</span><span class="pos-qty">'+trimQty(qty)+' unités</span></div>').join('');
}

function renderTrades(trades) {
  const el=qs('#modal-trades');
  if (!trades.length){el.innerHTML='<div class="empty-state">Aucun trade</div>';return;}
  el.innerHTML=trades.slice(0,20).map(tr=>{
    const buy=tr.action==='buy';
    return '<div class="trade-row '+(buy?'buy':'sell')+'"><span class="trade-action">'+(buy?'↑ BUY':'↓ SELL')+'</span><span class="trade-symbol">'+tr.symbol+'</span><span class="trade-amount">×'+trimQty(tr.amount)+'</span><span class="trade-price">@ €'+Number(tr.price).toFixed(2)+'</span><span class="trade-time">'+tr.timestamp.slice(11,16)+'</span></div>';
  }).join('');
}

// ═══════════════════════════════════════════════════════════════════
// NOTIFICATIONS
// ═══════════════════════════════════════════════════════════════════

function notify(icon, title, body, accent) {
  const notif={icon,title,body,accent,ts:new Date()};
  NOTIFS.unshift(notif); if (NOTIFS.length>50) NOTIFS.pop();
  unread++; updateBellBadge(); showToast(notif);
  if (notifOpen) renderNotifList();
}
function updateBellBadge() {
  const badge=qs('#bell-badge'); if (!badge) return;
  if (unread>0){badge.textContent=unread>99?'99+':String(unread);badge.classList.remove('hidden');}
  else badge.classList.add('hidden');
}
function showToast(n) {
  const container=qs('#toast-container'),el=document.createElement('div');
  el.className='toast'; el.style.setProperty('--toast-accent',n.accent||'var(--accent)');
  el.innerHTML='<div class="toast-icon">'+n.icon+'</div><div class="toast-body"><div class="toast-title">'+escHtml(n.title)+'</div><div class="toast-msg">'+escHtml(n.body)+'</div></div><button class="toast-close" aria-label="Fermer">✕</button>';
  el.querySelector('.toast-close').addEventListener('click',()=>dismissToast(el));
  container.appendChild(el);
  requestAnimationFrame(()=>requestAnimationFrame(()=>el.classList.add('toast-visible')));
  setTimeout(()=>dismissToast(el),5500);
}
function dismissToast(el) {
  el.classList.remove('toast-visible');
  el.addEventListener('transitionend',()=>el.remove(),{once:true});
}
function renderNotifList() {
  const list=qs('#notif-list'); if (!list) return;
  if (!NOTIFS.length){list.innerHTML='<div class="notif-empty">Aucune alerte</div>';return;}
  list.innerHTML=NOTIFS.map(n=>'<div class="notif-item"><div class="notif-item-icon">'+n.icon+'</div><div class="notif-item-body"><div class="notif-item-title">'+escHtml(n.title)+'</div><div class="notif-item-msg">'+escHtml(n.body)+'</div><div class="notif-item-ts">'+n.ts.toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit',second:'2-digit'})+'</div></div></div>').join('');
}
function toggleNotifPanel() {
  const panel=qs('#notif-panel'); notifOpen=!notifOpen; panel.classList.toggle('open',notifOpen);
  if (notifOpen){unread=0;updateBellBadge();renderNotifList();}
}

// ═══════════════════════════════════════════════════════════════════
// APPORT MODAL
// ═══════════════════════════════════════════════════════════════════

function _initApportModal() {
  qs('#apport-close').addEventListener('click',()=>qs('#apport-overlay').classList.add('hidden'));
  qs('#apport-overlay').addEventListener('click',e=>{if(e.target===qs('#apport-overlay'))qs('#apport-overlay').classList.add('hidden');});
  qs('#apport-submit').addEventListener('click', async () => {
    const montant=parseFloat(qs('#apport-montant').value),note=qs('#apport-note').value.trim(),fb=qs('#apport-feedback');
    if (!montant||montant<=0){fb.style.color='var(--red)';fb.textContent='Montant invalide';return;}
    fb.style.color='var(--muted)';fb.textContent='Envoi en cours…';
    try {
      const r=await fetch(API+'/patrimoine/apport',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({montant,note})});
      const res=await r.json();
      if (res.status==='ok'){
        fb.style.color='var(--accent)';fb.textContent='✓ Apport de '+fmt(montant,0)+' € enregistré';
        qs('#apport-montant').value='';qs('#apport-note').value='';
        setTimeout(()=>{
          qs('#apport-overlay').classList.add('hidden');
          retraiteLoaded=false; if(activeTab==='retraite') loadRetraite(true);
        },1200);
      } else throw new Error(res.erreur||'Erreur');
    } catch(err){fb.style.color='var(--red)';fb.textContent='Erreur : '+err.message;}
  });
}

// ═══════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════

function pct(value)   { return Math.min(100,Math.max(0,(value-START)/(TARGET-START)*100)); }
function fmt(n,decimals) { return Number(n).toLocaleString('fr-FR',{minimumFractionDigits:decimals,maximumFractionDigits:decimals}); }
function trimQty(n)   { return Number(n).toFixed(6).replace(/\.?0+$/,''); }
function qs(sel)      { return document.querySelector(sel); }
function qsa(sel)     { return document.querySelectorAll(sel); }
function escHtml(s)   { return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function showBanner() { qs('#banner').classList.remove('hidden'); }
function hideBanner() { qs('#banner').classList.add('hidden'); }
function _fmtTs(ts) {
  if (!ts) return '—';
  try { const d=new Date(ts.includes('T')?ts:ts+'Z'); return d.toLocaleString('fr-FR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}); }
  catch { return ts.slice(0,16); }
}

// ═══════════════════════════════════════════════════════════════════
// EVENTS & BOOT
// ═══════════════════════════════════════════════════════════════════

qs('#btn-close').addEventListener('click', closeModal);
qs('#overlay').addEventListener('click', e => { if (e.target===qs('#overlay')) closeModal(); });

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

qs('#filter-clear').addEventListener('click', () => { activeFilter=null; applyFilter(); });

qs('#bell-btn').addEventListener('click', e => { e.stopPropagation(); toggleNotifPanel(); });

document.addEventListener('click', e => {
  if (notifOpen && !qs('#notif-panel').contains(e.target) && e.target!==qs('#bell-btn')) {
    notifOpen=false; qs('#notif-panel').classList.remove('open');
  }
});

qs('#notif-clear-btn').addEventListener('click', () => { NOTIFS.length=0; renderNotifList(); });

// ── Boot ──────────────────────────────────────────────────────────
startClock();
initWS();
startPolling();
_initApportModal();
loadDashboard();

/* King Fund — Frontend App
   API base : window.KING_API ou ?api=URL ou http://localhost:5000/api
   WebSocket : ws://…/ws
*/

(function () {
  'use strict';

  // ── Config ──────────────────────────────────────────────
  const params  = new URLSearchParams(location.search);
  const API     = (window.KING_API || params.get('api') || 'http://localhost:5000/api').replace(/\/$/, '');
  const WS_URL  = API.replace(/^http/, 'ws').replace('/api', '/ws');

  const REFRESH_INTERVAL = 30_000; // 30s

  // Libellés humains pour les classes d'actif
  const CLASS_LABELS = {
    equity:       'Equity',
    fixed_income: 'Fixed Income',
    fx:           'FX',
    commodities:  'Commodités',
    derivatives:  'Dérivés',
    quant:        'Quant',
    crypto:       'Crypto',
    alternatives: 'Alternatives',
    multi:        'Multi',
  };

  // ── État ────────────────────────────────────────────────
  let state = {
    activeTab:      'classement',
    activeFilter:   'all',
    traders:        [],
    stats:          {},
    morning:        {},
    postmarket:     {},
    scheduler:      {},
    macro:          {},
    alertes:        {},
    intelligence:   {},
    retraite:       {},
    dividendes:     {},
    blackswan:      null,
    ws:             null,
    wsConnected:    false,
    timers:         {},
  };

  // ── Utils ────────────────────────────────────────────────
  const $  = id => document.getElementById(id);
  const el = (tag, cls, html) => {
    const e = document.createElement(tag);
    if (cls)  e.className   = cls;
    if (html !== undefined) e.innerHTML = html;
    return e;
  };

  function fmt(n, decimals = 0, prefix = '') {
    if (n == null || isNaN(n)) return '—';
    const abs = Math.abs(n);
    let s;
    if (abs >= 1_000_000) s = (n / 1_000_000).toFixed(1) + 'M';
    else if (abs >= 1_000) s = (n / 1_000).toFixed(1) + 'k';
    else s = n.toFixed(decimals);
    return prefix + s;
  }

  function fmtPnl(n) {
    if (n == null || isNaN(n)) return '—';
    const sign = n >= 0 ? '+' : '';
    return sign + fmt(n, 0) + ' €';
  }

  function fmtPct(n) {
    if (n == null) return '—';
    return (n >= 0 ? '+' : '') + n.toFixed(1) + '%';
  }

  function pnlClass(n) {
    if (n == null) return 'neu';
    return n > 0 ? 'pos' : n < 0 ? 'neg' : 'neu';
  }

  function timeAgo(iso) {
    if (!iso) return '—';
    const diff = Date.now() - new Date(iso).getTime();
    const min = Math.floor(diff / 60_000);
    if (min < 1)   return "À l'instant";
    if (min < 60)  return `Il y a ${min} min`;
    const h = Math.floor(min / 60);
    if (h < 24)    return `Il y a ${h}h`;
    return new Date(iso).toLocaleDateString('fr-FR');
  }

  function shortTime(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  }

  function toast(msg, type = 'info') {
    const t = $('toast');
    const colors = { info: '#3b82f6', ok: '#22c55e', error: '#ef4444' };
    t.style.borderColor = colors[type] || colors.info;
    t.textContent = msg;
    t.style.transform = 'translateY(0)';
    t.style.opacity   = '1';
    clearTimeout(state._toastTimer);
    state._toastTimer = setTimeout(() => {
      t.style.transform = 'translateY(80px)';
      t.style.opacity   = '0';
    }, 3000);
  }

  // ── Fetch wrappers ───────────────────────────────────────
  async function apiFetch(path, timeout = 10_000) {
    const ctrl = new AbortController();
    const id   = setTimeout(() => ctrl.abort(), timeout);
    try {
      const r = await fetch(API + path, { signal: ctrl.signal });
      clearTimeout(id);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch (e) {
      clearTimeout(id);
      throw e;
    }
  }

  async function apiPost(path, timeout = 15_000) {
    const ctrl = new AbortController();
    const id   = setTimeout(() => ctrl.abort(), timeout);
    try {
      const r = await fetch(API + path, {
        method: 'POST',
        signal: ctrl.signal,
        headers: { 'Content-Type': 'application/json' },
      });
      clearTimeout(id);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch (e) {
      clearTimeout(id);
      throw e;
    }
  }

  // ── WebSocket ────────────────────────────────────────────
  function connectWS() {
    if (state.ws) { try { state.ws.close(); } catch (_) {} }
    try {
      const ws = new WebSocket(WS_URL);
      state.ws = ws;

      ws.onopen = () => {
        state.wsConnected = true;
        setWsBadge('connected', 'Temps réel');
      };
      ws.onmessage = e => {
        try {
          const msg = JSON.parse(e.data);
          handleWsMessage(msg);
        } catch (_) {}
      };
      ws.onclose  = () => {
        state.wsConnected = false;
        setWsBadge('', 'Déconnecté');
        setTimeout(connectWS, 5_000);
      };
      ws.onerror  = () => {
        state.wsConnected = false;
        setWsBadge('error', 'Erreur WS');
      };
    } catch (_) {
      setWsBadge('error', 'WS indisponible');
    }
  }

  function setWsBadge(state_, label) {
    $('ws-dot').className   = 'ws-dot' + (state_ ? ' ' + state_ : '');
    $('ws-label').textContent = label;
  }

  function handleWsMessage(msg) {
    if (msg.type === 'state' || msg.classement) {
      state.traders = msg.classement || msg.traders || state.traders;
      state.stats   = msg.stats || state.stats;
      if (state.activeTab === 'classement') renderClassement();
    }
    if (msg.type === 'alerte') {
      toast(`🚨 ${msg.niveau?.toUpperCase()} — ${msg.titre}`, msg.niveau === 'critique' ? 'error' : 'info');
    }
  }

  // ── Tab navigation ────────────────────────────────────────
  function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        $('tab-' + tab).classList.add('active');
        state.activeTab = tab;
        App.refresh(tab);
      });
    });
  }

  // ── Filters ──────────────────────────────────────────────
  function initFilters() {
    document.querySelectorAll('.filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.activeFilter = btn.dataset.class;
        renderTraderList(state.traders, state.activeFilter);
      });
    });
  }

  // ── Classement ───────────────────────────────────────────
  async function loadClassement() {
    const [resState, resBS] = await Promise.allSettled([
      apiFetch('/state'),
      apiFetch('/blackswan/etat', 12_000),
    ]);

    if (resState.status === 'fulfilled') {
      const data = resState.value;
      state.traders = data.classement || data.traders || [];
      state.stats   = data.stats || {};
      $('classement-time').textContent = 'Mis à jour ' + timeAgo(data.timestamp);
    } else {
      renderClassementDemo();
    }

    if (resBS.status === 'fulfilled') {
      state.blackswan = resBS.value;
    }

    renderClassement();
  }

  function renderClassement() {
    renderKpis(state.stats);
    renderClassementBlackswan(state.blackswan);
    renderTraderList(state.traders, state.activeFilter);
  }

  function renderClassementBlackswan(bs) {
    const banner   = $('cl-bs-banner');
    const strip    = $('cl-bs-strip');
    const vixEl    = $('cl-bs-vix');
    const spreadEl = $('cl-bs-spread');
    const modeEl   = $('cl-bs-mode');
    const stoppesEl= $('cl-bs-stoppes');

    if (!bs) {
      banner.style.display = 'none';
      strip.style.display  = 'none';
      return;
    }

    const niveau  = bs.niveau || 'INCONNU';
    const indic   = bs.indicateurs || {};
    const style   = BS_NIVEAU_STYLE[niveau] || BS_NIVEAU_STYLE.INCONNU;
    const mode    = bs.mode_portefeuille || 'NORMAL';
    const stoppes = bs.traders_momentum_stoppes || [];

    // Bannière (hors NORMAL)
    if (niveau !== 'NORMAL' && niveau !== 'INCONNU') {
      banner.style.display    = 'block';
      banner.style.background = style.bg;
      banner.style.border     = `1px solid ${style.border}`;
      banner.style.color      = style.color;
      banner.textContent      = '🌊 ' + style.label +
        (stoppes.length ? ` — ${stoppes.length} traders momentum suspendus` : '');
    } else {
      banner.style.display = 'none';
    }

    // Strip
    strip.style.display     = 'flex';
    strip.style.borderColor = style.border;

    vixEl.textContent  = indic.vix != null ? indic.vix.toFixed(1) : '—';
    vixEl.className    = !indic.vix ? 'neu' : indic.vix > 34 ? 'neg' : indic.vix > 25 ? 'warn' : 'pos';

    spreadEl.textContent = indic.credit_spread_hy != null ? indic.credit_spread_hy.toFixed(0) + ' bps' : '—';
    spreadEl.className   = !indic.credit_spread_hy ? 'neu' : indic.credit_spread_hy > 700 ? 'neg' : indic.credit_spread_hy > 500 ? 'warn' : 'pos';

    modeEl.textContent  = mode;
    modeEl.style.color  = style.color;

    stoppesEl.textContent = stoppes.length
      ? `${stoppes.length} traders momentum ${mode === 'BARBELL' ? 'stoppés' : 'en surveillance'}`
      : 'Aucun trader impacté';
    stoppesEl.style.color = stoppes.length ? style.color : 'var(--muted)';
  }

  function renderKpis(s) {
    const pnl = s.pnl_total_desk ?? 0;
    const kEl = $('kpi-pnl');
    kEl.textContent  = fmtPnl(pnl);
    kEl.className    = 'kpi-val ' + pnlClass(pnl);
    $('kpi-pos').textContent    = s.nb_traders_positifs ?? '—';
    $('kpi-neg').textContent    = s.nb_traders_negatifs ?? '—';
    $('kpi-wr').textContent     = s.taux_victoire_moyen != null ? s.taux_victoire_moyen.toFixed(0) + '%' : '—';
    $('kpi-trades').textContent = s.nb_trades_total ?? '—';
    $('kpi-vol').textContent    = fmt(s.volume_total, 0) + ' €';
  }

  function renderTraderList(traders, filter) {
    const list = $('trader-list');
    if (!traders || !traders.length) {
      list.innerHTML = '<div style="text-align:center;padding:40px;color:var(--muted)">Aucune donnée disponible</div>';
      return;
    }
    const filtered = filter === 'all' ? traders : traders.filter(t => t.classe_actif === filter);
    if (!filtered.length) {
      list.innerHTML = '<div style="text-align:center;padding:30px;color:var(--muted)">Aucun trader dans cette classe</div>';
      return;
    }
    const bs          = state.blackswan || {};
    const bsNiveau    = bs.niveau || 'NORMAL';
    const bsStoppes   = new Set(bs.traders_momentum_stoppes || []);

    list.innerHTML = '';
    filtered.forEach((t, i) => {
      const rank     = traders.indexOf(t) + 1;
      const rankCls  = rank === 1 ? 'gold' : rank === 2 ? 'silver' : rank === 3 ? 'bronze' : '';
      const pnl      = t.pnl_jour ?? 0;
      const label    = CLASS_LABELS[t.classe_actif] || t.classe_actif || '';
      const badgeCls = 'trader-badge badge-' + (t.classe_actif || 'equity');

      const isStoppé  = bsStoppes.has(t.trader_id);
      const isWarning = !isStoppé && bsNiveau === 'WARNING' && bsStoppes.has(t.trader_id);

      let bsBadge = '';
      if (isStoppé && bsNiveau === 'CRITIQUE') {
        bsBadge = `<span style="
          background:#3a1010;border:1px solid #e53935;color:#ff6b6b;
          border-radius:4px;font-size:10px;font-weight:700;
          padding:1px 6px;margin-left:6px;vertical-align:middle;
        ">⚠ STOPPÉ</span>`;
      } else if (bsNiveau === 'WARNING' && isStoppé) {
        bsBadge = `<span style="
          background:#2c2200;border:1px solid #f9a825;color:#ffd54f;
          border-radius:4px;font-size:10px;font-weight:700;
          padding:1px 6px;margin-left:6px;vertical-align:middle;
        ">⚡ WATCH</span>`;
      }

      const cardStyle = isStoppé && bsNiveau === 'CRITIQUE'
        ? 'border-left:3px solid #e53935;'
        : '';

      const card = el('div', 'trader-card');
      card.dataset.class = t.classe_actif || '';
      card.style.cssText += cardStyle;
      card.innerHTML = `
        <div class="trader-rank ${rankCls}">${rank}</div>
        <div class="trader-info">
          <div class="trader-name">${t.nom || '—'}${bsBadge}</div>
          <div class="trader-role">${t.role || ''}</div>
          <span class="${badgeCls}">${label}</span>
          <div style="font-size:11px;color:var(--muted);margin-top:2px">${t.specialite || ''}</div>
        </div>
        <div class="trader-stats">
          <div class="trader-pnl ${pnlClass(pnl)}">${fmtPnl(pnl)}</div>
          <div class="trader-meta">${t.nb_trades ?? 0} trades · ${(t.taux_victoire ?? 0).toFixed(0)}% WR</div>
          ${t.meilleur_ticker ? `<div class="trader-meta">↑ ${t.meilleur_ticker}</div>` : ''}
        </div>`;
      list.appendChild(card);
    });
  }

  function renderClassementDemo() {
    const traders = getDemoTraders();
    state.traders = traders;
    renderKpis({ pnl_total_desk: 47820, nb_traders_positifs: 22, nb_traders_negatifs: 7,
                 taux_victoire_moyen: 63.4, nb_trades_total: 284, volume_total: 3_420_000 });
    renderTraderList(traders, state.activeFilter);
    $('classement-time').textContent = 'Mode démo (API hors ligne)';
    toast('API hors ligne — données démo affichées', 'info');
  }

  // ── Morning Brief ─────────────────────────────────────────
  async function loadMorning() {
    const [resBrief, resBS] = await Promise.allSettled([
      apiFetch('/brief'),
      apiFetch('/blackswan/etat', 12_000),
    ]);

    if (resBrief.status === 'fulfilled') {
      renderMorning(resBrief.value);
      $('brief-time').textContent = 'Généré ' + timeAgo(resBrief.value.timestamp);
    } else {
      $('brief-rapport').textContent = 'Morning Brief indisponible (API hors ligne).\n\nDémarrez le serveur backend pour voir les rapports Anthropic.';
      $('brief-rapport').classList.add('loading');
    }

    renderMorningBlackswan(resBS.status === 'fulfilled' ? resBS.value : null);
  }

  function renderMorningBlackswan(bs) {
    const banner  = $('brief-bs-banner');
    const bodyEl  = $('brief-bs-body');
    const badge   = $('brief-bs-niveau-badge');

    if (!bs) {
      banner.style.display = 'none';
      badge.textContent    = 'N/A';
      bodyEl.innerHTML     = '<span style="color:var(--muted)">Agent Black Swan non disponible.</span>';
      return;
    }

    const niveau  = bs.niveau || 'INCONNU';
    const indic   = bs.indicateurs || {};
    const style   = BS_NIVEAU_STYLE[niveau] || BS_NIVEAU_STYLE.INCONNU;
    const stoppes = bs.traders_momentum_stoppes || [];
    const mode    = bs.mode_portefeuille || 'NORMAL';

    // Bannière (visible uniquement hors NORMAL)
    if (niveau !== 'NORMAL' && niveau !== 'INCONNU') {
      banner.style.display     = 'block';
      banner.style.background  = style.bg;
      banner.style.border      = `1px solid ${style.border}`;
      banner.style.color       = style.color;
      banner.textContent       = '🌊 ' + style.label + (
        stoppes.length ? ` — ${stoppes.length} traders momentum stoppés` : ''
      );
    } else {
      banner.style.display = 'none';
    }

    // Badge niveau
    badge.textContent         = niveau;
    badge.style.color         = style.color;
    badge.style.borderColor   = style.border;
    badge.style.border        = `1px solid ${style.border}`;

    // Indicateurs en ligne
    const cols = [
      { label: 'VIX',        val: indic.vix              != null ? indic.vix.toFixed(1)              : '—', cls: !indic.vix ? '' : indic.vix > 34 ? 'neg' : indic.vix > 25 ? 'warn' : 'pos' },
      { label: 'DSPX/Skew',  val: indic.dspx             != null ? indic.dspx.toFixed(1)             : '—', cls: indic.dspx > 140 ? 'warn' : '' },
      { label: 'Spread HY',  val: indic.credit_spread_hy != null ? indic.credit_spread_hy.toFixed(0) + ' bps' : '—', cls: !indic.credit_spread_hy ? '' : indic.credit_spread_hy > 700 ? 'neg' : indic.credit_spread_hy > 500 ? 'warn' : 'pos' },
      { label: 'Corr SPY/TLT', val: indic.correlation_spy_tlt != null ? indic.correlation_spy_tlt.toFixed(2) : '—', cls: indic.correlation_spy_tlt < -0.6 ? 'neg' : '' },
    ];

    let html = `<div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:10px">` +
      cols.map(c =>
        `<div style="text-align:center">
          <div style="font-size:10px;color:var(--muted);margin-bottom:2px">${c.label}</div>
          <div style="font-size:16px;font-weight:700" class="${c.cls}">${c.val}</div>
        </div>`
      ).join('') +
      `</div>`;

    html += `<div style="font-size:11px;color:var(--muted)">Mode portefeuille : <strong style="color:${style.color}">${mode}</strong>`;

    if (mode === 'BARBELL') {
      const actifs = bs.actifs_recommandes || {};
      const allTickers = Object.values(actifs).flat().filter(Boolean);
      if (allTickers.length) {
        html += ` — Allocation : ${allTickers.join(', ')}`;
      }
    }

    if (indic.vix_variation_24h != null) {
      const v = indic.vix_variation_24h;
      html += ` · VIX var.24h : <span class="${v > 0 ? 'neg' : 'pos'}">${v > 0 ? '+' : ''}${v.toFixed(1)}%</span>`;
    }
    html += `</div>`;

    if ((bs.messages_analyse || []).length) {
      const last = bs.messages_analyse[bs.messages_analyse.length - 1];
      html += `<div style="margin-top:6px;font-size:11px;font-style:italic;color:var(--muted)">${last}</div>`;
    }

    bodyEl.innerHTML = html;
  }

  function renderMorning(data) {
    // Indices asie
    const asie = data.indices_asie || {};
    const asieEl = $('brief-indices');
    asieEl.innerHTML = '';
    Object.entries(asie).forEach(([ticker, info]) => {
      if (!info) return;
      const chg = info.variation_pct ?? 0;
      asieEl.appendChild(buildKpi(ticker, fmt(info.prix, 2), fmtPct(chg), pnlClass(chg)));
    });

    // Banques centrales
    const bc = data.banques_centrales || [];
    const bcEl = $('brief-bc-list');
    if (bc.length) {
      bcEl.innerHTML = bc.slice(0, 8).map(b =>
        `<div style="padding:4px 0;border-bottom:1px solid var(--border)">
          <span style="font-weight:600">${b.banque || b.nom || '—'}</span>
          <span style="float:right;color:var(--muted)">${b.taux_directeur != null ? b.taux_directeur + '%' : '—'}</span>
          <div style="color:var(--muted);font-size:11px">${b.biais || b.politique || ''}</div>
        </div>`
      ).join('');
    } else {
      bcEl.textContent = 'Aucune donnée banques centrales disponible';
    }

    // Actualités
    const news = data.actualites || [];
    const newsEl = $('brief-news-list');
    if (news.length) {
      newsEl.innerHTML = news.slice(0, 8).map(n =>
        `<div style="padding:5px 0;border-bottom:1px solid var(--border)">
          <div style="font-size:12px">${n.titre || n.title || '—'}</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">${n.source || ''} · ${shortTime(n.date || n.publishedAt)}</div>
        </div>`
      ).join('');
    } else {
      newsEl.textContent = 'Aucune actualité disponible';
    }

    // Rapport
    const rapportEl = $('brief-rapport');
    rapportEl.textContent = data.rapport || data.synthese || 'Rapport non disponible';
    rapportEl.classList.remove('loading');
  }

  // ── Post-Market ───────────────────────────────────────────
  async function loadPostmarket() {
    const [resPmr, resBS] = await Promise.allSettled([
      apiFetch('/post-market'),
      apiFetch('/blackswan/etat', 12_000),
    ]);

    if (resPmr.status === 'fulfilled') {
      renderPostmarket(resPmr.value);
      $('pmr-date').textContent = resPmr.value.date ? `Session du ${resPmr.value.date} · 18:15` : '18:15';
    } else {
      $('pmr-rapport').textContent = 'Post-Market Review indisponible (API hors ligne).\n\nLe rapport est généré automatiquement à 18:15 par le scheduler.';
      $('pmr-rapport').classList.add('loading');
    }

    renderPostmarketBlackswan(resBS.status === 'fulfilled' ? resBS.value : null);
  }

  function renderPostmarketBlackswan(bs) {
    const banner = $('pmr-bs-banner');
    const bodyEl = $('pmr-bs-body');
    const badge  = $('pmr-bs-niveau-badge');

    if (!bs) {
      banner.style.display = 'none';
      badge.textContent    = 'N/A';
      bodyEl.innerHTML     = '<span style="color:var(--muted)">Agent Black Swan non disponible.</span>';
      return;
    }

    const niveau  = bs.niveau || 'INCONNU';
    const indic   = bs.indicateurs || {};
    const style   = BS_NIVEAU_STYLE[niveau] || BS_NIVEAU_STYLE.INCONNU;
    const stoppes = bs.traders_momentum_stoppes || [];
    const mode    = bs.mode_portefeuille || 'NORMAL';

    // Bannière (hors NORMAL)
    if (niveau !== 'NORMAL' && niveau !== 'INCONNU') {
      banner.style.display    = 'block';
      banner.style.background = style.bg;
      banner.style.border     = `1px solid ${style.border}`;
      banner.style.color      = style.color;
      banner.textContent      = '🌊 Clôture sous alerte Black Swan — ' + style.label +
        (stoppes.length ? ` · ${stoppes.length} traders momentum stoppés` : '');
    } else {
      banner.style.display = 'none';
    }

    // Badge
    badge.textContent       = niveau;
    badge.style.color       = style.color;
    badge.style.borderColor = style.border;

    // Indicateurs
    const metrics = [
      indic.vix              != null ? `<b>VIX</b> <span class="${!indic.vix ? '' : indic.vix > 34 ? 'neg' : indic.vix > 25 ? 'warn' : 'pos'}">${indic.vix.toFixed(1)}</span>` : null,
      indic.dspx             != null ? `<b>DSPX</b> <span class="${indic.dspx > 140 ? 'warn' : ''}">${indic.dspx.toFixed(1)}</span>` : null,
      indic.credit_spread_hy != null ? `<b>Spread HY</b> <span class="${indic.credit_spread_hy > 700 ? 'neg' : indic.credit_spread_hy > 500 ? 'warn' : 'pos'}">${indic.credit_spread_hy.toFixed(0)} bps</span>` : null,
      indic.correlation_spy_tlt != null ? `<b>Corr SPY/TLT</b> <span class="${indic.correlation_spy_tlt < -0.6 ? 'neg' : ''}">${indic.correlation_spy_tlt.toFixed(2)}</span>` : null,
    ].filter(Boolean);

    let html = `<div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:8px">` +
      metrics.map(m => `<span style="font-size:13px">${m}</span>`).join('') +
      `</div>`;

    html += `<div style="font-size:11px;color:var(--muted)">Mode de clôture : <strong style="color:${style.color}">${mode}</strong>`;

    if (stoppes.length > 0) {
      html += ` · Traders stoppés : ` +
        stoppes.map(id =>
          `<span style="background:#3a1010;border:1px solid #e53935;border-radius:3px;padding:1px 5px;margin:1px;display:inline-block;font-size:10px">${id}</span>`
        ).join('');
    } else {
      html += ` · Aucun trader momentum impacté`;
    }

    if (mode === 'BARBELL') {
      const actifs = bs.actifs_recommandes || {};
      const tickers = Object.entries(actifs)
        .filter(([, v]) => v && v.length)
        .map(([cat, v]) => `${cat.toUpperCase()} : ${v.join(', ')}`).join(' · ');
      if (tickers) html += `<div style="margin-top:4px">Allocation barbell : ${tickers}</div>`;
    }

    html += `</div>`;

    if ((bs.messages_analyse || []).length) {
      const last = bs.messages_analyse[bs.messages_analyse.length - 1];
      html += `<div style="margin-top:6px;font-size:11px;font-style:italic;color:var(--muted)">${last}</div>`;
    }

    bodyEl.innerHTML = html;
  }

  function renderPostmarket(data) {
    // Podium
    const best  = data.meilleur_trader || {};
    const worst = data.pire_trader || {};
    $('pmr-best-nom').textContent   = best.nom   || '—';
    $('pmr-best-role').textContent  = best.role  || best.specialite || '—';
    $('pmr-best-pnl').textContent   = fmtPnl(best.pnl_jour);
    $('pmr-best-stats').textContent = best.nb_trades ? `${best.nb_trades} trades · ${best.taux_victoire?.toFixed(0)}% WR` : '—';
    $('pmr-worst-nom').textContent   = worst.nom   || '—';
    $('pmr-worst-role').textContent  = worst.role  || worst.specialite || '—';
    $('pmr-worst-pnl').textContent   = fmtPnl(worst.pnl_jour);
    $('pmr-worst-stats').textContent = worst.nb_trades ? `${worst.nb_trades} trades · ${worst.taux_victoire?.toFixed(0)}% WR` : '—';

    // KPIs desk
    const s = data.stats_globales || {};
    const kEl = $('pmr-kpis');
    kEl.innerHTML = '';
    [
      ['P&L Desk', fmtPnl(s.pnl_total_desk), '', pnlClass(s.pnl_total_desk)],
      ['Traders +', s.nb_traders_positifs ?? '—', `/ ${s.nb_traders ?? 30}`, 'pos'],
      ['Volume', fmt(s.volume_total, 0) + ' €', 'Échangé'],
      ['Trades', s.nb_trades_total ?? '—', 'Exécutés'],
      ['Win Rate', s.taux_victoire_moyen ? s.taux_victoire_moyen.toFixed(0) + '%' : '—', 'Moyen'],
    ].forEach(([label, val, sub, cls]) => kEl.appendChild(buildKpi(label, val, sub, cls)));

    // Par classe d'actif
    const classEl = $('pmr-classes');
    const classes = data.classement_classes || {};
    if (Object.keys(classes).length) {
      classEl.innerHTML = Object.entries(classes).map(([cls, traders]) => {
        const totalPnl = traders.reduce((s, t) => s + (t.pnl_jour || 0), 0);
        const label    = CLASS_LABELS[cls] || cls;
        const pct      = s.pnl_total_desk ? (totalPnl / Math.abs(s.pnl_total_desk) * 100).toFixed(0) : 0;
        return `
          <div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid var(--border)">
            <span class="trader-badge badge-${cls}" style="min-width:90px;text-align:center">${label}</span>
            <div style="flex:1">
              <div class="progress-bar"><div class="progress-fill" style="width:${Math.min(Math.abs(pct), 100)}%"></div></div>
            </div>
            <span class="${pnlClass(totalPnl)}" style="font-weight:700;min-width:80px;text-align:right">${fmtPnl(totalPnl)}</span>
          </div>`;
      }).join('');
    } else {
      classEl.textContent = 'Aucune donnée';
    }

    // Par secteur
    const sectEl = $('pmr-secteurs');
    const secteurs = data.analyse_trades?.par_secteur || {};
    if (Object.keys(secteurs).length) {
      sectEl.innerHTML = Object.entries(secteurs).slice(0, 10).map(([sec, val]) => {
        const pnl = val.pnl || 0;
        return `
          <div style="display:flex;align-items:center;gap:10px;padding:5px 0;border-bottom:1px solid var(--border)">
            <span style="font-size:12px;flex:1">${sec}</span>
            <span style="font-size:11px;color:var(--muted)">${val.nb_trades} trades</span>
            <span class="${pnlClass(pnl)}" style="font-weight:600;min-width:75px;text-align:right">${fmtPnl(pnl)}</span>
          </div>`;
      }).join('');
    } else {
      sectEl.textContent = 'Aucune donnée sectorielle';
    }

    // Table classement
    const tbody = $('pmr-table');
    tbody.innerHTML = '';
    (data.classement || []).forEach((t, i) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="color:var(--muted);font-weight:600">${i + 1}</td>
        <td><strong>${t.nom}</strong><div style="font-size:10px;color:var(--muted)">${t.trader_id}</div></td>
        <td style="font-size:11px">${t.specialite || '—'}</td>
        <td class="${pnlClass(t.pnl_jour)}" style="font-weight:700">${fmtPnl(t.pnl_jour)}</td>
        <td>${t.nb_trades ?? '—'}</td>
        <td>${t.taux_victoire != null ? t.taux_victoire.toFixed(0) + '%' : '—'}</td>`;
      tbody.appendChild(tr);
    });

    // Rapport narratif
    const rapportEl = $('pmr-rapport');
    rapportEl.textContent = data.rapport_narratif || 'Rapport non disponible';
    rapportEl.classList.remove('loading');
  }

  // ── Scheduler ─────────────────────────────────────────────
  async function loadScheduler() {
    const [resEtat, resRes, resBS] = await Promise.allSettled([
      apiFetch('/scheduler/etat'),
      apiFetch('/scheduler/resultats'),
      apiFetch('/blackswan/etat', 12_000),
    ]);

    if (resEtat.status === 'fulfilled' && resRes.status === 'fulfilled') {
      renderScheduler(resEtat.value, resRes.value);
    } else {
      $('sched-status').textContent = 'Hors ligne';
      $('sched-status').style.color = 'var(--red)';
      $('sched-results').textContent = 'Scheduler API indisponible';
    }

    renderSchedulerBlackswan(
      resBS.status  === 'fulfilled' ? resBS.value  : null,
      resRes.status === 'fulfilled' ? resRes.value : null,
    );
  }

  function renderSchedulerBlackswan(bs, resultats) {
    const vixEl    = $('sched-bs-vix');
    const niveauEl = $('sched-bs-niveau');
    const badge    = $('sched-bs-badge');
    const bodyEl   = $('sched-bs-body');
    const planRow  = $('sched-plan-bs');

    if (!bs) {
      vixEl.textContent    = '—';
      vixEl.className      = 'kpi-val neu';
      niveauEl.textContent = 'Indisponible';
      badge.textContent    = 'N/A';
      bodyEl.innerHTML     = '<span style="color:var(--muted)">Agent Black Swan non disponible.</span>';
      return;
    }

    const niveau  = bs.niveau || 'INCONNU';
    const indic   = bs.indicateurs || {};
    const style   = BS_NIVEAU_STYLE[niveau] || BS_NIVEAU_STYLE.INCONNU;
    const mode    = bs.mode_portefeuille || 'NORMAL';

    // KPI
    vixEl.textContent = indic.vix != null ? indic.vix.toFixed(1) : '—';
    vixEl.className   = 'kpi-val ' + (!indic.vix ? 'neu' : indic.vix > 34 ? 'neg' : indic.vix > 25 ? 'warn' : 'pos');
    niveauEl.textContent = 'Mode : ' + mode;

    // Badge
    badge.textContent       = niveau;
    badge.style.color       = style.color;
    badge.style.borderColor = style.border;

    // Ligne planning — colorer selon niveau
    if (planRow) {
      planRow.style.color = niveau === 'CRITIQUE' ? 'var(--red)' : niveau === 'WARNING' ? 'var(--yellow)' : 'var(--muted)';
    }

    // Derniers résultats des jobs BS dans le scheduler
    const lastScan   = resultats?.blackswan_scan   || resultats?.blackswan_30min || null;
    const scanStatut = lastScan?.statut ?? '—';
    const scanTs     = lastScan?.timestamp ? timeAgo(lastScan.timestamp) : '—';

    let html = `<div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:10px">`;
    html += `<div><div style="font-size:10px;color:var(--muted)">Dernier scan</div><div style="font-size:13px;font-weight:600">${scanTs}</div></div>`;
    html += `<div><div style="font-size:10px;color:var(--muted)">Statut</div><div style="font-size:13px;font-weight:600;color:${scanStatut === 'ok' ? 'var(--green)' : scanStatut === 'erreur' ? 'var(--red)' : 'var(--muted)'}">${scanStatut}</div></div>`;
    html += `<div><div style="font-size:10px;color:var(--muted)">VIX</div><div style="font-size:13px;font-weight:600" class="${!indic.vix ? 'neu' : indic.vix > 34 ? 'neg' : indic.vix > 25 ? 'warn' : 'pos'}">${indic.vix != null ? indic.vix.toFixed(1) : '—'}</div></div>`;
    html += `<div><div style="font-size:10px;color:var(--muted)">Spread HY</div><div style="font-size:13px;font-weight:600" class="${!indic.credit_spread_hy ? 'neu' : indic.credit_spread_hy > 700 ? 'neg' : indic.credit_spread_hy > 500 ? 'warn' : 'pos'}">${indic.credit_spread_hy != null ? indic.credit_spread_hy.toFixed(0) + ' bps' : '—'}</div></div>`;
    html += `<div><div style="font-size:10px;color:var(--muted)">DSPX</div><div style="font-size:13px;font-weight:600" class="${indic.dspx > 140 ? 'warn' : 'neu'}">${indic.dspx != null ? indic.dspx.toFixed(1) : '—'}</div></div>`;
    html += `<div><div style="font-size:10px;color:var(--muted)">Corr SPY/TLT</div><div style="font-size:13px;font-weight:600" class="${indic.correlation_spy_tlt < -0.6 ? 'neg' : 'neu'}">${indic.correlation_spy_tlt != null ? indic.correlation_spy_tlt.toFixed(2) : '—'}</div></div>`;
    html += `</div>`;

    html += `<div style="font-size:11px;color:var(--muted)">Mode portefeuille : <strong style="color:${style.color}">${mode}</strong>`;
    if (bs.traders_momentum_stoppes?.length) {
      html += ` · ${bs.traders_momentum_stoppes.length} traders momentum stoppés`;
    }
    if (lastScan?.erreur) {
      html += `<div style="margin-top:4px;color:var(--red)">Erreur dernier scan : ${lastScan.erreur}</div>`;
    }
    html += `</div>`;

    bodyEl.innerHTML = html;
  }

  function renderScheduler(etat, resultats) {
    $('sched-status').textContent  = etat.running ? '🟢 Actif' : '🔴 Arrêté';
    $('sched-status').style.color  = etat.running ? 'var(--green)' : 'var(--red)';
    $('sched-nb').textContent      = etat.nb_jobs ?? '—';
    $('sched-tz').textContent      = etat.timezone || 'Europe/Paris';

    const jobs = etat.jobs || [];
    const next = jobs.filter(j => j.prochaine_exec).sort((a, b) =>
      new Date(a.prochaine_exec) - new Date(b.prochaine_exec)
    )[0];
    $('sched-next').textContent = next ? `${next.id} · ${shortTime(next.prochaine_exec)}` : '—';

    // Table jobs
    const tbody = $('sched-table');
    tbody.innerHTML = '';
    jobs.forEach(j => {
      const res  = resultats[j.id] || {};
      const stat = res.statut || j.dernier_resultat || 'pending';
      const tr   = document.createElement('tr');
      tr.innerHTML = `
        <td style="font-family:monospace;font-size:12px">${j.id}</td>
        <td><span class="job-status ${stat}">${stat}</span></td>
        <td style="font-size:11px">${shortTime(j.prochaine_exec)}</td>
        <td style="font-size:11px;color:var(--muted)">${res.timestamp ? timeAgo(res.timestamp) : '—'}</td>`;
      tbody.appendChild(tr);
    });

    // Derniers résultats (compacts)
    const resEl = $('sched-results');
    resEl.innerHTML = '';
    Object.entries(resultats).slice(0, 8).forEach(([id, res]) => {
      const d = el('div', '', '');
      d.style.cssText = 'padding:5px 0;border-bottom:1px solid var(--border);font-size:12px';
      const ok = res.statut === 'ok';
      d.innerHTML = `<span style="color:${ok ? 'var(--green)' : 'var(--red)'}">${ok ? '✓' : '✗'}</span>
        <strong style="margin:0 6px">${id}</strong>
        <span style="color:var(--muted)">${timeAgo(res.timestamp)}</span>
        ${res.erreur ? `<div style="color:var(--red);font-size:11px;margin-top:2px">${res.erreur}</div>` : ''}`;
      resEl.appendChild(d);
    });
    if (!Object.keys(resultats).length) resEl.textContent = 'Aucun job exécuté depuis le démarrage';
  }

  // ── CIO Macro ─────────────────────────────────────────────
  async function loadMacro() {
    const [resMacro, resBS] = await Promise.allSettled([
      apiFetch('/macro'),
      apiFetch('/blackswan/etat', 12_000),
    ]);

    if (resMacro.status === 'fulfilled') {
      renderMacro(resMacro.value);
      $('macro-time').textContent = 'Mis à jour ' + timeAgo(resMacro.value.timestamp);
    } else {
      $('macro-bc').textContent = 'CIO Macro API indisponible — démarrez le serveur backend';
    }

    renderMacroBlackswan(resBS.status === 'fulfilled' ? resBS.value : null);
  }

  function renderMacroBlackswan(bs) {
    const banner = $('macro-bs-banner');
    const bodyEl = $('macro-bs-body');
    const badge  = $('macro-bs-badge');

    if (!bs) {
      banner.style.display = 'none';
      badge.textContent    = 'N/A';
      bodyEl.innerHTML     = '<span style="color:var(--muted)">Agent Black Swan non disponible.</span>';
      return;
    }

    const niveau  = bs.niveau || 'INCONNU';
    const indic   = bs.indicateurs || {};
    const style   = BS_NIVEAU_STYLE[niveau] || BS_NIVEAU_STYLE.INCONNU;
    const mode    = bs.mode_portefeuille || 'NORMAL';
    const stoppes = bs.traders_momentum_stoppes || [];

    // Bannière (hors NORMAL)
    if (niveau !== 'NORMAL' && niveau !== 'INCONNU') {
      banner.style.display    = 'block';
      banner.style.background = style.bg;
      banner.style.border     = `1px solid ${style.border}`;
      banner.style.color      = style.color;
      banner.textContent      = '🌊 CIO Alert — ' + style.label;
    } else {
      banner.style.display = 'none';
    }

    // Badge
    badge.textContent       = niveau;
    badge.style.color       = style.color;
    badge.style.borderColor = style.border;

    // Ligne indicateurs avec interprétation CIO
    const fmt = (v, decimals = 1) => v != null ? v.toFixed(decimals) : '—';
    const vixCls    = !indic.vix ? '' : indic.vix > 34 ? 'neg' : indic.vix > 25 ? 'warn' : 'pos';
    const spreadCls = !indic.credit_spread_hy ? '' : indic.credit_spread_hy > 700 ? 'neg' : indic.credit_spread_hy > 500 ? 'warn' : 'pos';
    const dspxCls   = indic.dspx > 140 ? 'warn' : '';
    const corrCls   = indic.correlation_spy_tlt < -0.6 ? 'neg' : '';

    let html = `<div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:12px">`;
    html += `<div><div style="font-size:10px;color:var(--muted)">VIX</div><div style="font-size:20px;font-weight:700" class="${vixCls}">${fmt(indic.vix)}</div><div style="font-size:10px;color:var(--muted)">var.24h : ${indic.vix_variation_24h != null ? (indic.vix_variation_24h > 0 ? '+' : '') + fmt(indic.vix_variation_24h) + '%' : '—'}</div></div>`;
    html += `<div><div style="font-size:10px;color:var(--muted)">DSPX / Skew</div><div style="font-size:20px;font-weight:700" class="${dspxCls}">${fmt(indic.dspx)}</div><div style="font-size:10px;color:var(--muted)">Risque de queue</div></div>`;
    html += `<div><div style="font-size:10px;color:var(--muted)">Spread HY</div><div style="font-size:20px;font-weight:700" class="${spreadCls}">${fmt(indic.credit_spread_hy, 0)} bps</div><div style="font-size:10px;color:var(--muted)">FRED BAMLH0A0HYM2</div></div>`;
    html += `<div><div style="font-size:10px;color:var(--muted)">Corr SPY/TLT</div><div style="font-size:20px;font-weight:700" class="${corrCls}">${fmt(indic.correlation_spy_tlt, 2)}</div><div style="font-size:10px;color:var(--muted)">Rolling 20j</div></div>`;
    html += `</div>`;

    // Recommandation CIO
    html += `<div style="border-top:1px solid var(--border);padding-top:10px;font-size:12px">`;
    html += `<span style="color:var(--muted)">Positionnement CIO : </span><strong style="color:${style.color}">${mode}</strong> — `;
    if (mode === 'BARBELL') {
      const actifs = bs.actifs_recommandes || {};
      const parts  = Object.entries(actifs)
        .filter(([, v]) => v && v.length)
        .map(([cat, v]) => `${cat} (${v.join(', ')})`).join(' · ');
      html += `Réduction exposition momentum · Allocation barbell : ${parts || '—'}`;
      if (stoppes.length) {
        html += `<div style="margin-top:6px;font-size:11px;color:var(--muted)">Traders momentum suspendus (${stoppes.length}) : ${stoppes.join(', ')}</div>`;
      }
    } else if (mode === 'NORMAL') {
      html += `Allocation standard maintenue · Pas de restriction trading`;
    }
    html += `</div>`;

    bodyEl.innerHTML = html;
  }

  function renderMacro(data) {
    const MARKET_SECTIONS = [
      ['macro-asie',   data.indices_asie   || {}, { '^N225': 'Nikkei', '^HSI': 'Hang Seng', '000300.SS': 'CSI300' }],
      ['macro-europe', data.indices_europe  || {}, { '^FCHI': 'CAC40', '^GDAXI': 'DAX', '^FTSE': 'FTSE100', '^STOXX50E': 'EuroStoxx50' }],
      ['macro-us',     data.indices_us     || {}, { '^GSPC': 'S&P500', '^IXIC': 'Nasdaq', '^DJI': 'Dow Jones', '^VIX': 'VIX' }],
      ['macro-forex',  data.forex          || {}, { 'EURUSD=X': 'EUR/USD', 'GC=F': 'Gold', 'CL=F': 'Pétrole WTI' }],
    ];

    MARKET_SECTIONS.forEach(([id, src, labels]) => {
      const el_ = $(id);
      el_.innerHTML = '';
      const entries = Object.keys(labels).length
        ? Object.entries(labels).map(([k, lbl]) => [lbl, src[k]])
        : Object.entries(src);
      if (!entries.some(([, v]) => v)) {
        el_.innerHTML = '<span style="color:var(--muted);font-size:12px">Données non disponibles</span>';
        return;
      }
      entries.forEach(([ticker, info]) => {
        if (!info) return;
        const chg   = info.variation_pct ?? 0;
        const cell  = el('div', 'market-cell');
        cell.innerHTML = `
          <div class="market-ticker">${ticker}</div>
          <div class="market-price">${info.prix != null ? info.prix.toLocaleString('fr-FR', { maximumFractionDigits: 2 }) : '—'}</div>
          <div class="market-change ${pnlClass(chg)}">${fmtPct(chg)}</div>`;
        el_.appendChild(cell);
      });
    });

    // Crypto
    const cryptoEl = $('macro-crypto');
    cryptoEl.innerHTML = '';
    const crypto = data.crypto?.prix || data.crypto || {};
    Object.entries(crypto).slice(0, 6).forEach(([ticker, info]) => {
      if (!info) return;
      const chg  = info.variation_24h ?? info.variation_pct ?? 0;
      const cell = el('div', 'market-cell');
      cell.innerHTML = `
        <div class="market-ticker">${ticker}</div>
        <div class="market-price">$${info.prix != null ? info.prix.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—'}</div>
        <div class="market-change ${pnlClass(chg)}">${fmtPct(chg)}</div>`;
      cryptoEl.appendChild(cell);
    });

    // Banques centrales
    const bcEl = $('macro-bc');
    const bc   = data.banques_centrales || [];
    if (bc.length) {
      const tbl = document.createElement('table');
      tbl.className = 'data-table';
      tbl.innerHTML = `<thead><tr><th>Banque</th><th>Taux</th><th>Biais</th><th>Prochaine réunion</th></tr></thead>`;
      const tbody = document.createElement('tbody');
      bc.slice(0, 12).forEach(b => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>${b.banque || b.nom || '—'}</strong></td>
          <td>${b.taux_directeur != null ? b.taux_directeur + '%' : '—'}</td>
          <td style="color:${b.biais === 'hawkish' ? 'var(--red)' : b.biais === 'dovish' ? 'var(--green)' : 'var(--muted)'}">${b.biais || '—'}</td>
          <td style="font-size:11px;color:var(--muted)">${b.prochaine_reunion || '—'}</td>`;
        tbody.appendChild(tr);
      });
      tbl.appendChild(tbody);
      bcEl.innerHTML = '';
      bcEl.appendChild(tbl);
    } else {
      bcEl.textContent = 'Aucune donnée banques centrales';
    }
  }

  // ── Alertes ───────────────────────────────────────────────
  async function loadAlertes() {
    const [resAlertes, resMaint, resBS] = await Promise.allSettled([
      apiFetch('/alertes'),
      apiFetch('/maintenance/health'),
      apiFetch('/blackswan/etat', 12_000),
    ]);

    if (resAlertes.status === 'fulfilled') {
      const data = resAlertes.value;

      // Fusionner les alertes maintenance dans les listes sectorielles
      if (resMaint.status === 'fulfilled') {
        const recentes = resMaint.value.alertes_recentes || [];
        const toItem = a => ({
          titre:     a.titre,
          detail:    a.detail,
          expert:    '🔧 Maintenance',
          timestamp: a.ts,
        });
        data.critiques = [
          ...(data.critiques || []),
          ...recentes.filter(a => a.niveau === 'critique' || a.niveau === 'critique_urgent').map(toItem),
        ];
        data.warnings = [
          ...(data.warnings || []),
          ...recentes.filter(a => a.niveau === 'warning').map(toItem),
        ];
        data.infos = [
          ...(data.infos || []),
          ...recentes.filter(a => a.niveau === 'info').map(toItem),
        ];
      }

      // Injecter l'alerte Black Swan dans la liste critique ou warning
      if (resBS.status === 'fulfilled') {
        const bs = resBS.value;
        if (bs.niveau === 'CRITIQUE' || bs.niveau === 'WARNING') {
          const indic  = bs.indicateurs || {};
          const vixStr = indic.vix   != null ? indic.vix.toFixed(1)   : 'N/A';
          const spStr  = indic.credit_spread_hy != null ? indic.credit_spread_hy.toFixed(0) + 'bps' : 'N/A';
          const bsItem = {
            titre:     `🌊 Black Swan — VIX ${vixStr} | Spread HY ${spStr} | Mode ${bs.mode_portefeuille}`,
            detail:    (bs.messages_analyse || []).slice(-1)[0] || '',
            expert:    '🌊 AgentBlackSwan',
            timestamp: bs.timestamp,
          };
          if (bs.niveau === 'CRITIQUE') {
            data.critiques = [bsItem, ...(data.critiques || [])];
          } else {
            data.warnings  = [bsItem, ...(data.warnings  || [])];
          }
        }
      }

      renderAlertes(data);
      $('alertes-time').textContent = 'Mis à jour ' + timeAgo(data.timestamp);
    } else {
      $('alertes-crit-list').innerHTML =
        '<div style="color:var(--muted);font-size:12px;text-align:center;padding:20px">API alertes indisponible</div>';
    }

    if (resMaint.status === 'fulfilled') {
      renderMaintenanceHealth(resMaint.value);
    } else {
      renderMaintenanceHealth(null);
    }

    renderBlackswanInline(resBS.status === 'fulfilled' ? resBS.value : null);
  }

  function renderAlertes(data) {
    const critiques = data.critiques || [];
    const warnings  = data.warnings  || [];
    const infos     = data.infos     || [];

    $('alertes-crit').textContent = critiques.length;
    $('alertes-warn').textContent = warnings.length;
    $('alertes-info').textContent = infos.length;

    renderAlerteList('alertes-crit-list', critiques, 'critique');
    renderAlerteList('alertes-warn-list', warnings,  'warning');

    // Surveillance continue experts sectoriels
    const survEl = $('alertes-surveillance');
    const surv   = data.surveillance || {};
    if (Object.keys(surv).length) {
      survEl.innerHTML = Object.entries(surv).map(([expert, etat]) => `
        <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)">
          <span>${expert}</span>
          <span style="color:${etat.actif ? 'var(--green)' : 'var(--muted)'}">${etat.actif ? 'Actif' : 'Inactif'}</span>
        </div>`).join('');
    } else {
      survEl.textContent = 'Surveillance continue non démarrée';
    }
  }

  function renderBlackswanInline(bs) {
    const vixEl    = $('al-bs-vix');
    const niveauEl = $('al-bs-niveau');
    const bodyEl   = $('al-bs-body');
    const card     = $('al-bs-card');

    if (!bs) {
      vixEl.textContent    = '—';
      vixEl.className      = 'kpi-val neu';
      niveauEl.textContent = 'Indisponible';
      bodyEl.innerHTML     = '<span style="color:var(--muted)">Agent Black Swan non disponible.</span>';
      return;
    }

    const niveau = bs.niveau || 'INCONNU';
    const indic  = bs.indicateurs || {};
    const style  = BS_NIVEAU_STYLE[niveau] || BS_NIVEAU_STYLE.INCONNU;
    const stoppes = bs.traders_momentum_stoppes || [];

    // KPI VIX
    vixEl.textContent = indic.vix != null ? indic.vix.toFixed(1) : '—';
    vixEl.className   = 'kpi-val ' + (
      !indic.vix ? 'neu' : indic.vix > 34 ? 'neg' : indic.vix > 25 ? 'warn' : 'pos'
    );
    niveauEl.textContent = 'Mode : ' + (bs.mode_portefeuille || '—');

    // Bordure card selon niveau
    card.style.borderColor = style.border;

    // Corps de la card
    const rows = [
      indic.vix              != null ? `<b>VIX</b> ${indic.vix.toFixed(1)} <span style="color:var(--muted)">(critique >34)</span>` : null,
      indic.dspx             != null ? `<b>DSPX/Skew</b> ${indic.dspx.toFixed(1)} <span style="color:var(--muted)">(alerte >140)</span>` : null,
      indic.credit_spread_hy != null ? `<b>Spread HY</b> ${indic.credit_spread_hy.toFixed(0)} bps <span style="color:var(--muted)">(critique >700bps)</span>` : null,
      indic.correlation_spy_tlt != null ? `<b>Corr SPY/TLT</b> ${indic.correlation_spy_tlt.toFixed(2)}` : null,
    ].filter(Boolean);

    let html = `<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:8px">` +
      rows.map(r => `<span>${r}</span>`).join('') + `</div>`;

    html += `<div style="font-weight:600;color:${style.color};margin-bottom:6px">${style.label}</div>`;

    if (stoppes.length > 0) {
      html += `<div style="margin-top:4px;font-size:11px">Traders momentum stoppés : ` +
        stoppes.map(id =>
          `<span style="background:#3a1010;border:1px solid #e53935;border-radius:3px;padding:1px 5px;margin:1px;display:inline-block">${id}</span>`
        ).join('') + `</div>`;
    }

    bodyEl.innerHTML = html;
  }

  function renderAlerteList(elId, alertes, niveau) {
    const el_ = $(elId);
    if (!alertes.length) {
      el_.innerHTML = `<div style="color:var(--muted);font-size:12px;text-align:center;padding:20px">Aucune alerte ${niveau}</div>`;
      return;
    }
    el_.innerHTML = '';
    alertes.slice(0, 20).forEach(a => {
      const icon = niveau === 'critique' ? '🔴' : niveau === 'warning' ? '🟡' : 'ℹ️';
      const item = el('div', `alerte-item ${niveau}`);
      item.innerHTML = `
        <div class="alerte-icon">${icon}</div>
        <div class="alerte-body">
          <div class="alerte-titre">${a.titre || a.message || '—'}</div>
          ${a.detail ? `<div class="alerte-sous-titre">${a.detail.slice(0, 100)}</div>` : ''}
          <div class="alerte-detail">${a.expert || a.secteur || ''} ${a.ticker ? '· ' + a.ticker : ''}</div>
          <div class="alerte-time">${timeAgo(a.timestamp)}</div>
        </div>`;
      el_.appendChild(item);
    });
  }

  // ── Santé système (maintenance) ───────────────────────────

  const COMPOSANT_ICONS = {
    database:  '🗄️',
    scheduler: '⚙️',
    websocket: '🔌',
    memoire:   '💾',
    disque:    '💿',
  };

  function renderMaintenanceHealth(health) {
    if (!health) {
      $('maint-global').textContent    = '—';
      $('maint-global').className      = 'kpi-val neu';
      $('maint-global-sub').textContent = 'API indisponible';
      $('maint-composants').innerHTML =
        '<div style="color:var(--muted);font-size:12px">Service maintenance non disponible</div>';
      return;
    }

    // KPI global
    const ok = health.ok !== false;
    const globalEl = $('maint-global');
    globalEl.textContent = ok ? '✓ OK' : '⚠ Alerte';
    globalEl.className   = 'kpi-val ' + (ok ? 'pos' : 'neg');
    $('maint-global-sub').textContent = ok ? 'Tous systèmes' : 'Voir détail';

    // KPI corrections
    const corrections = health.corrections || {};
    const nbCorr = Object.values(corrections).reduce((s, v) => s + (v || 0), 0);
    $('maint-corrections').textContent = nbCorr;

    // Grille des composants
    const composants = health.composants || {};
    const grid = $('maint-composants');
    if (!Object.keys(composants).length) {
      grid.innerHTML = '<div style="color:var(--muted);font-size:12px">Aucun composant surveillé</div>';
    } else {
      grid.innerHTML = '';
      Object.entries(composants).forEach(([nom, s]) => {
        const card = el('div', 'composant-card ' + (s.ok ? 'composant-ok' : 'composant-err'));
        card.innerHTML = `
          <div class="composant-icon">${COMPOSANT_ICONS[nom] || '⚙️'}</div>
          <div class="composant-nom">${nom}</div>
          <div class="composant-status ${s.ok ? 'pos' : 'neg'}">${s.message || '—'}</div>
          ${s.detail ? `<div class="composant-detail">${s.detail}</div>` : ''}`;
        grid.appendChild(card);
      });
    }

    // Timestamp dernier check
    const lastEl = $('maint-last-check');
    lastEl.textContent = health.timestamp
      ? 'Dernier check : ' + timeAgo(health.timestamp)
      : '';
  }

  async function forceCheck() {
    toast('⚡ Vérification système en cours…', 'info');
    try {
      const health = await apiPost('/maintenance/check');
      renderMaintenanceHealth(health);
      toast('✓ Vérification terminée', 'ok');
    } catch (e) {
      toast('API maintenance indisponible', 'error');
    }
  }

  async function fixDb() {
    toast('🗄️ Réparation SQLite en cours…', 'info');
    try {
      const result = await apiPost('/maintenance/fix-db');
      toast(
        result.ok ? '✓ ' + result.message : '⚠ ' + result.message,
        result.ok ? 'ok' : 'error',
      );
      apiFetch('/maintenance/health').then(renderMaintenanceHealth).catch(() => {});
    } catch (e) {
      toast('API maintenance indisponible', 'error');
    }
  }

  // ── KPI builder helper ────────────────────────────────────
  function buildKpi(label, val, sub, cls) {
    const k = el('div', 'kpi');
    k.innerHTML = `
      <div class="kpi-label">${label}</div>
      <div class="kpi-val ${cls || ''}">${val ?? '—'}</div>
      ${sub ? `<div class="kpi-sub">${sub}</div>` : ''}`;
    return k;
  }

  // ── Demo data ─────────────────────────────────────────────
  function getDemoTraders() {
    const base = [
      { trader_id: 'TRD001', nom: 'Alexandre Martin',   role: 'Senior Equity Trader',      specialite: 'Large Cap Europe',        classe_actif: 'equity',       pnl_jour:  4820, nb_trades: 12, taux_victoire: 75, meilleur_ticker: 'LVMH' },
      { trader_id: 'TRD005', nom: 'Thomas Girard',      role: 'Senior Equity Trader',      specialite: 'Tech & Semiconducteurs',  classe_actif: 'equity',       pnl_jour:  3650, nb_trades: 9,  taux_victoire: 67, meilleur_ticker: 'ASML' },
      { trader_id: 'TRD025', nom: 'Sébastien Robert',   role: 'Quant Trader',              specialite: 'Statistical Arb',         classe_actif: 'quant',        pnl_jour:  3210, nb_trades: 31, taux_victoire: 71, meilleur_ticker: 'SPY' },
      { trader_id: 'TRD028', nom: 'Mathieu Martinez',   role: 'Crypto Trader',             specialite: 'BTC, ETH, DeFi',          classe_actif: 'crypto',       pnl_jour:  2980, nb_trades: 18, taux_victoire: 61, meilleur_ticker: 'BTC' },
      { trader_id: 'TRD016', nom: 'Emma Garnier',       role: 'Senior FX Trader',          specialite: 'G10 FX',                  classe_actif: 'fx',           pnl_jour:  2540, nb_trades: 14, taux_victoire: 64, meilleur_ticker: 'EUR/USD' },
      { trader_id: 'TRD026', nom: 'Pauline Michel',     role: 'Algo Trader',               specialite: 'High-Frequency Equity',   classe_actif: 'quant',        pnl_jour:  2180, nb_trades: 45, taux_victoire: 69, meilleur_ticker: 'CAC40' },
      { trader_id: 'TRD011', nom: 'François Lambert',   role: 'Senior Bond Trader',        specialite: 'Souverains Zone Euro',    classe_actif: 'fixed_income', pnl_jour:  1920, nb_trades: 7,  taux_victoire: 71, meilleur_ticker: 'OAT10Y' },
      { trader_id: 'TRD020', nom: 'Chloé Marchand',     role: 'Metals Trader',             specialite: 'Or, Argent, Cuivre',      classe_actif: 'commodities',  pnl_jour:  1640, nb_trades: 6,  taux_victoire: 67, meilleur_ticker: 'GC=F' },
      { trader_id: 'TRD006', nom: 'Anaïs Morel',        role: 'US Equity Trader',          specialite: 'S&P500 Large Cap',        classe_actif: 'equity',       pnl_jour:  1450, nb_trades: 11, taux_victoire: 55, meilleur_ticker: 'AAPL' },
      { trader_id: 'TRD030', nom: 'Charles Dupuis',     role: 'Prop Trader',               specialite: 'Cross-Asset Opportuniste',classe_actif: 'multi',        pnl_jour:  1320, nb_trades: 22, taux_victoire: 59, meilleur_ticker: 'SPY' },
      { trader_id: 'TRD022', nom: 'Laura Henry',        role: 'Equity Derivatives Trader', specialite: 'Index Options & Vol',     classe_actif: 'derivatives',  pnl_jour:  1100, nb_trades: 8,  taux_victoire: 63, meilleur_ticker: 'VIX' },
      { trader_id: 'TRD027', nom: 'Vincent Garcia',     role: 'Quant Macro Trader',        specialite: 'Macro systématique',      classe_actif: 'quant',        pnl_jour:   980, nb_trades: 16, taux_victoire: 56, meilleur_ticker: 'TLT' },
      { trader_id: 'TRD029', nom: 'Océane Lefebvre',    role: 'Alternative Trader',        specialite: 'REITs & Infrastructure',  classe_actif: 'alternatives', pnl_jour:   760, nb_trades: 5,  taux_victoire: 60, meilleur_ticker: 'VNQ' },
      { trader_id: 'TRD019', nom: 'Baptiste Rousseau',  role: 'Energy Trader',             specialite: 'Pétrole & Gaz naturel',   classe_actif: 'commodities',  pnl_jour:   620, nb_trades: 9,  taux_victoire: 56, meilleur_ticker: 'CL=F' },
      { trader_id: 'TRD012', nom: 'Margot Chevalier',   role: 'Credit Trader',             specialite: 'IG Corporate Bonds',      classe_actif: 'fixed_income', pnl_jour:   540, nb_trades: 4,  taux_victoire: 75, meilleur_ticker: 'LQD' },
      { trader_id: 'TRD007', nom: 'Nicolas Bernard',    role: 'Global Equity Trader',      specialite: 'Marchés émergents',       classe_actif: 'equity',       pnl_jour:   410, nb_trades: 8,  taux_victoire: 50, meilleur_ticker: 'EEM' },
      { trader_id: 'TRD015', nom: 'Julien Moreau',      role: 'Rate Trader',               specialite: 'Taux courts EZ',          classe_actif: 'fixed_income', pnl_jour:   320, nb_trades: 6,  taux_victoire: 50, meilleur_ticker: 'BTP2Y' },
      { trader_id: 'TRD024', nom: 'Alice Thomas',       role: 'Vol Arb Trader',            specialite: 'Volatilité implicite',    classe_actif: 'derivatives',  pnl_jour:   180, nb_trades: 12, taux_victoire: 58, meilleur_ticker: 'VVIX' },
      { trader_id: 'TRD021', nom: 'Quentin Fournier',   role: 'Agri Trader',               specialite: 'Blé, Maïs, Soja',         classe_actif: 'commodities',  pnl_jour:    90, nb_trades: 4,  taux_victoire: 50, meilleur_ticker: 'CORN' },
      { trader_id: 'TRD023', nom: 'Romain André',       role: 'Structured Products',       specialite: 'Autocalls & Barriers',    classe_actif: 'derivatives',  pnl_jour:   -40, nb_trades: 3,  taux_victoire: 33, meilleur_ticker: null },
      { trader_id: 'TRD018', nom: 'Inès Faure',         role: 'FX Options Trader',         specialite: 'EUR Options',             classe_actif: 'fx',           pnl_jour:  -120, nb_trades: 7,  taux_victoire: 43, meilleur_ticker: null },
      { trader_id: 'TRD010', nom: 'Clara Simon',        role: 'Equity Trader',             specialite: 'Consommation & Retail',   classe_actif: 'equity',       pnl_jour:  -240, nb_trades: 10, taux_victoire: 40, meilleur_ticker: null },
      { trader_id: 'TRD008', nom: 'Léa Dupont',         role: 'Equity Trader',             specialite: 'Healthcare & Pharma',     classe_actif: 'equity',       pnl_jour:  -380, nb_trades: 7,  taux_victoire: 43, meilleur_ticker: null },
      { trader_id: 'TRD002', nom: 'Camille Fontaine',   role: 'Equity Trader',             specialite: 'Small/Mid Cap France',    classe_actif: 'equity',       pnl_jour:  -490, nb_trades: 13, taux_victoire: 38, meilleur_ticker: null },
      { trader_id: 'TRD013', nom: 'Antoine Roux',       role: 'HY Credit Trader',          specialite: 'High Yield Europe',       classe_actif: 'fixed_income', pnl_jour:  -580, nb_trades: 6,  taux_victoire: 33, meilleur_ticker: null },
      { trader_id: 'TRD009', nom: 'Maxime Petit',       role: 'Equity Trader',             specialite: 'Banques & Finance',       classe_actif: 'equity',       pnl_jour:  -650, nb_trades: 9,  taux_victoire: 44, meilleur_ticker: null },
      { trader_id: 'TRD003', nom: 'Pierre Leclerc',     role: 'Equity Trader',             specialite: 'DACH (DE/AT/CH)',         classe_actif: 'equity',       pnl_jour:  -820, nb_trades: 11, taux_victoire: 36, meilleur_ticker: null },
      { trader_id: 'TRD017', nom: 'Hugo Blanc',         role: 'FX Trader',                 specialite: 'EM FX',                   classe_actif: 'fx',           pnl_jour:  -910, nb_trades: 8,  taux_victoire: 38, meilleur_ticker: null },
      { trader_id: 'TRD014', nom: 'Sophie Laurent',     role: 'EM Debt Trader',            specialite: 'Dettes émergentes',       classe_actif: 'fixed_income', pnl_jour: -1050, nb_trades: 5,  taux_victoire: 40, meilleur_ticker: null },
      { trader_id: 'TRD004', nom: 'Julie Renard',       role: 'Junior Equity Trader',      specialite: 'Utilities & Energie',     classe_actif: 'equity',       pnl_jour: -1340, nb_trades: 14, taux_victoire: 29, meilleur_ticker: null },
    ];
    return base.sort((a, b) => b.pnl_jour - a.pnl_jour);
  }

  // ── Investissement ────────────────────────────────────────

  function _recoToSignal(reco) {
    if (!reco) return 'HOLD';
    const r = reco.toUpperCase();
    if (r.includes('ACHAT')) return 'BUY';
    if (r === 'SURVEILLER') return 'HOLD';
    return 'SELL';
  }

  async function loadInvestissement() {
    let theses = {};
    try {
      const [data, thData] = await Promise.allSettled([
        apiFetch('/investissement/watchlist', 90_000),
        apiFetch('/investissement/theses',    120_000),
      ]);
      if (thData.status === 'fulfilled') theses = thData.value.theses || {};
      if (data.status === 'fulfilled') {
        renderWatchlist(data.value, theses);
        $('inv-time').textContent = 'Mis à jour ' + timeAgo(data.value.timestamp);
      } else {
        $('inv-watchlist-table').innerHTML =
          '<div style="color:var(--muted);padding:16px">API investissement indisponible — backend hors ligne</div>';
      }
    } catch (e) {
      $('inv-watchlist-table').innerHTML =
        '<div style="color:var(--muted);padding:16px">API investissement indisponible — backend hors ligne</div>';
    }
    try {
      const sc = await apiFetch('/investissement/screener', 10_000);
      renderScreener(sc);
    } catch (_) {}
  }

  function renderWatchlist(data, theses) {
    theses = theses || {};
    const list  = data.watchlist || [];
    // Accepte signal direct (BUY/HOLD/SELL) ou recommandation texte (ACHAT/SURVEILLER/VENTE)
    const signalOf = a => a.signal || _recoToSignal(a.recommandation);
    const nbBuy  = list.filter(a => signalOf(a) === 'BUY').length;
    const nbHold = list.filter(a => signalOf(a) === 'HOLD').length;
    const nbSell = list.filter(a => signalOf(a) === 'SELL').length;

    $('inv-nb').textContent       = list.length;
    $('inv-buy-cnt').textContent  = nbBuy;
    $('inv-hold-cnt').textContent = nbHold;
    $('inv-sell-cnt').textContent = nbSell;

    const tbl = document.createElement('table');
    tbl.className = 'data-table';
    tbl.innerHTML = `<thead><tr>
      <th>Ticker</th><th>Nom</th><th>Bourse</th>
      <th>Score /10</th><th>Marge Sécu.</th><th>Signal</th>
      <th>Prix</th><th>Prix Cible</th><th>WACC</th><th>PER</th><th>PBR</th>
      <th style="min-width:220px">Thèse d'investissement</th>
    </tr></thead>`;
    const tbody = document.createElement('tbody');

    list.forEach(a => {
      if (a.erreur) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td><strong>${a.ticker}</strong></td><td style="font-size:11px">${a.nom}</td><td style="font-size:10px;color:var(--muted)">${a.bourse}</td>
          <td colspan="9" style="color:var(--red);font-size:11px">${a.erreur}</td>`;
        tbody.appendChild(tr);
        return;
      }
      // score : accepte format 0-10 (a.score) ou 0-100 (a.score_global/10)
      const score10Raw = a.score != null ? a.score : (a.score_global != null ? a.score_global / 10 : null);
      const score10    = score10Raw != null ? score10Raw.toFixed(1) : '—';
      const scoreCls   = score10Raw == null ? 'neu' : score10Raw >= 7 ? 'pos' : score10Raw >= 4.5 ? 'neu' : 'neg';

      const marge    = a.marge_securite;
      const margeFmt = marge != null ? (marge * 100).toFixed(1) + '%' : '—';
      const margeCls = marge == null ? 'neu' : marge >= 0.30 ? 'pos' : marge >= 0 ? 'neu' : 'neg';
      const signal   = signalOf(a);
      const sigStyle = signal === 'BUY'
        ? 'background:#1a3a1a;color:#4ade80;font-weight:700;padding:2px 8px;border-radius:4px'
        : signal === 'HOLD'
          ? 'background:#2a2a1a;color:#facc15;font-weight:700;padding:2px 8px;border-radius:4px'
          : 'background:#3a1a1a;color:#f87171;font-weight:700;padding:2px 8px;border-radius:4px';

      // Prix cible : target_price (backend riche) ou valeur_intrinseque (nouveau watchlist)
      const prixCible = a.target_price ?? a.valeur_intrinseque;
      const prixCibleCls = prixCible != null && a.prix_actuel != null
        ? (prixCible > a.prix_actuel ? 'pos' : 'neg') : 'neu';

      const these      = theses[a.ticker] || '';
      const theseShort = these.length > 90 ? these.slice(0, 88) + '…' : these;
      const theseCell  = these
        ? `<span title="${these.replace(/"/g, '&quot;')}" style="font-size:11px;color:var(--muted);cursor:help">${theseShort}</span>`
        : '<span style="color:var(--muted);font-size:10px">—</span>';

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><strong>${a.ticker}</strong></td>
        <td style="font-size:11px">${a.nom}</td>
        <td style="font-size:10px;color:var(--muted)">${a.bourse}</td>
        <td class="${scoreCls}"><strong>${score10}</strong></td>
        <td class="${margeCls}"><strong>${margeFmt}</strong></td>
        <td><span style="${sigStyle}">${signal}</span></td>
        <td>${a.prix_actuel != null ? a.prix_actuel.toLocaleString('fr-FR', {maximumFractionDigits:2}) : '—'}</td>
        <td class="${prixCibleCls}">${prixCible != null ? prixCible.toLocaleString('fr-FR', {maximumFractionDigits:2}) : '—'}</td>
        <td style="font-size:11px">${a.wacc_damodaran != null ? (a.wacc_damodaran*100).toFixed(1)+'%' : '—'}</td>
        <td>${a.per != null ? a.per.toFixed(1) : '—'}</td>
        <td>${a.pbr != null ? a.pbr.toFixed(2) : '—'}</td>
        <td>${theseCell}</td>`;
      tbody.appendChild(tr);
    });

    tbl.appendChild(tbody);
    $('inv-watchlist-table').innerHTML = '';
    $('inv-watchlist-table').appendChild(tbl);
  }

  function renderScreener(sc) {
    if (!sc || sc.message) return;

    $('screener-time').textContent = sc.fin ? 'Scan ' + timeAgo(sc.fin) : '—';
    $('sc-univers').textContent    = sc.nb_univers_total ?? '—';
    $('sc-candidats').textContent  = sc.nb_candidats_graham ?? '—';
    $('sc-analyses').textContent   = sc.nb_analyses ?? '—';
    $('sc-buy').textContent        = sc.nb_buy_auto ?? '—';

    // BUY signals
    const buys = sc.buy_signals || [];
    const buyCard = $('screener-buy-card');
    if (buys.length) {
      buyCard.style.display = 'block';
      const buyList = $('screener-buy-list');
      buyList.innerHTML = '';
      buys.forEach(b => {
        const d = el('div', '', `
          <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border)">
            <div>
              <strong>${b.ticker}</strong>
              <span style="color:var(--muted);font-size:11px;margin-left:8px">${b.nom}</span>
              <span style="margin-left:8px;font-size:10px;color:var(--muted)">${b.bourse}</span>
            </div>
            <div style="text-align:right">
              <span class="pos" style="font-weight:700;margin-right:12px">Score ${b.score_pipeline}</span>
              <span class="pos">Marge ${b.marge_securite != null ? (b.marge_securite*100).toFixed(0)+'%' : '—'}</span>
            </div>
          </div>`);
        buyList.appendChild(d);
      });
    } else {
      buyCard.style.display = 'none';
    }

    // Top opportunities table
    const opps = sc.top_opportunites || [];
    if (!opps.length) {
      $('screener-top-table').innerHTML =
        '<div style="color:var(--muted);padding:16px">Aucune opportunité détectée après le filtre Graham.</div>';
      return;
    }
    const tbl = document.createElement('table');
    tbl.className = 'data-table';
    tbl.innerHTML = `<thead><tr>
      <th>#</th><th>Ticker</th><th>Nom</th><th>Bourse</th>
      <th>Score</th><th>Reco</th><th>PER</th><th>PBR</th>
      <th>Prix</th><th>Val. Intrin.</th><th>Marge Sécu.</th><th>WACC</th><th>BUY</th>
    </tr></thead>`;
    const tbody = document.createElement('tbody');
    opps.forEach((o, i) => {
      const marge   = o.marge_securite;
      const margeFmt = marge != null ? (marge * 100).toFixed(1) + '%' : '—';
      const margeCls = marge == null ? 'neu' : marge >= 0.30 ? 'pos' : marge >= 0 ? 'neu' : 'neg';
      const scoreCls = (o.score_pipeline || 0) >= 7 ? 'pos' : 'neu';
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="color:var(--muted)">${i+1}</td>
        <td><strong>${o.ticker}</strong></td>
        <td style="font-size:11px">${o.nom}</td>
        <td style="font-size:10px;color:var(--muted)">${o.bourse}</td>
        <td class="${scoreCls}"><strong>${o.score_pipeline ?? '—'}</strong></td>
        <td style="font-size:10px">${o.recommandation || '—'}</td>
        <td>${o.per != null ? o.per.toFixed(1) : '—'}</td>
        <td>${o.pbr != null ? o.pbr.toFixed(2) : '—'}</td>
        <td>${o.prix_actuel != null ? o.prix_actuel.toLocaleString('fr-FR',{maximumFractionDigits:2}) : '—'}</td>
        <td>${o.valeur_intrinseque != null ? o.valeur_intrinseque.toLocaleString('fr-FR',{maximumFractionDigits:2}) : '—'}</td>
        <td class="${margeCls}"><strong>${margeFmt}</strong></td>
        <td style="font-size:11px">${o.wacc_damodaran != null ? (o.wacc_damodaran*100).toFixed(1)+'%' : '—'}</td>
        <td style="text-align:center;font-size:14px">${o.buy_auto ? '🟢' : '—'}</td>`;
      tbody.appendChild(tr);
    });
    tbl.appendChild(tbody);
    $('screener-top-table').innerHTML = '';
    $('screener-top-table').appendChild(tbl);
  }

  async function runScreener() {
    toast('🔍 Scan mondial démarré (peut prendre 10-15 min)…', 'info');
    try {
      await apiPost('/investissement/screener/run', 15_000);
      toast('✓ Scan en arrière-plan — rechargez dans 15 min', 'ok');
    } catch (e) {
      toast('API screener indisponible', 'error');
    }
  }

  // ── Analyse ticker universelle ────────────────────────────

  const _INV_WATCHLIST = new Set([
    'VPK.AS','GTT.PA','O','JNJ','VZ','TEL.OL','DNB.OL',
    'BIPC','ADC','DSY.PA','SU.PA','TTE.PA','AIR.PA',
  ]);

  async function analyzeTickerSearch() {
    const input = $('inv-search-input');
    if (!input) return;
    const ticker = input.value.trim().toUpperCase();
    if (!ticker) { toast('Entrez un ticker (ex: WPM, MC.PA)', 'info'); return; }

    const resultEl = $('inv-search-result');
    resultEl.style.display = 'block';
    resultEl.innerHTML = '<div style="text-align:center;padding:24px"><div class="spinner"></div>'
      + '<p style="margin-top:10px;color:var(--muted)">Pipeline 17 étapes en cours… (15-30 s)</p></div>';

    try {
      const data = await apiFetch(`/investissement/analyze?ticker=${encodeURIComponent(ticker)}`, 90_000);
      _renderAnalyzeResult(data, ticker);
    } catch (e) {
      resultEl.innerHTML = `<div style="padding:14px;color:var(--red);background:var(--bg2);`
        + `border:1px solid #f87171;border-radius:8px">❌ Ticker invalide ou données indisponibles : <strong>${ticker}</strong></div>`;
    }
  }

  function _renderAnalyzeResult(data, ticker) {
    const resultEl = $('inv-search-result');
    if (!resultEl) return;

    if (data.erreur) {
      resultEl.innerHTML = `<div style="padding:14px;color:var(--red);background:var(--bg2);`
        + `border:1px solid #f87171;border-radius:8px">❌ ${data.erreur}</div>`;
      return;
    }

    const score  = data.score ?? 0;
    const signal = (data.signal || 'hold').toLowerCase();
    const reco   = data.recommandation_finale || signal.toUpperCase();
    const garde  = data._garde_fou || {};
    const statut = garde.statut_donnees || '—';
    const disc   = garde.disclaimer || '';
    const stages = data.stages || [];
    const inWl   = _INV_WATCHLIST.has(ticker);

    const scoreColor = score >= 7 ? 'var(--green)' : score >= 4 ? '#facc15' : 'var(--red)';
    const sigBg    = signal === 'buy'  ? '#1a3a1a' : signal === 'hold' ? '#2a2a1a' : '#3a1a1a';
    const sigColor = signal === 'buy'  ? '#4ade80' : signal === 'hold' ? '#facc15' : '#f87171';
    const statutColor = statut === 'OK' ? 'var(--green)' : '#facc15';

    const stageRows = stages.filter(s => s.name !== 'Score final').map((s, i) => {
      const sc  = s.score ?? 0;
      const cls = sc >= 0.3 ? 'pos' : sc <= -0.3 ? 'neg' : 'neu';
      const pct = Math.round(((sc + 1) / 2) * 100);
      const bar = cls === 'pos' ? '#4ade80' : cls === 'neg' ? '#f87171' : '#6b7280';
      return `<tr>
        <td style="color:var(--muted);text-align:center;font-size:11px">${i + 1}</td>
        <td style="font-size:12px">${s.name}</td>
        <td class="${cls}" style="text-align:right;font-weight:700;white-space:nowrap;font-size:12px">${sc.toFixed(3)}</td>
        <td style="width:80px;padding-left:8px">
          <div style="background:var(--bg3);border-radius:3px;height:5px;overflow:hidden">
            <div style="width:${pct}%;height:100%;background:${bar}"></div>
          </div>
        </td>
      </tr>`;
    }).join('');

    const addBtnHtml = inWl ? '' : `
      <div style="padding:12px 16px;border-top:1px solid var(--border)">
        <button class="btn btn-sm" id="btn-add-wl-${ticker}"
                onclick="App.addToWatchlist('${ticker}')"
                style="background:var(--bg2);color:#60a5fa;border:1px solid #3b82f6;font-size:12px">
          ➕ Ajouter à la watchlist
        </button>
      </div>`;

    resultEl.innerHTML = `
      <div style="border:1px solid var(--border);border-radius:10px;overflow:hidden">
        <div style="display:flex;align-items:center;gap:16px;padding:16px;background:var(--bg2);flex-wrap:wrap">
          <div>
            <div style="font-size:20px;font-weight:700;color:var(--fg)">${data.symbol || ticker}</div>
            <div style="font-size:11px;color:var(--muted);margin-top:2px">Pipeline 17 critères · Graham · Buffett · Damodaran</div>
          </div>
          <div style="margin-left:auto;display:flex;gap:20px;align-items:center">
            <div style="text-align:center">
              <div style="font-size:26px;font-weight:800;color:${scoreColor}">${score.toFixed(1)}</div>
              <div style="font-size:10px;color:var(--muted)">/10</div>
            </div>
            <span style="background:${sigBg};color:${sigColor};font-weight:700;padding:6px 16px;border-radius:6px;font-size:14px">${reco}</span>
          </div>
        </div>
        <div style="padding:6px 16px;background:var(--bg3);font-size:10px;color:var(--muted);border-top:1px solid var(--border)">
          <span style="color:${statutColor}">●</span> ${disc}
        </div>
        <div style="padding:16px">
          <div style="font-size:11px;font-weight:600;color:var(--muted);margin-bottom:8px;text-transform:uppercase;letter-spacing:.07em">17 Critères détaillés</div>
          <div style="overflow-x:auto">
            <table class="data-table" style="font-size:12px">
              <thead><tr>
                <th style="width:30px">#</th><th>Critère</th>
                <th style="text-align:right">Score [-1, +1]</th><th style="width:80px">Jauge</th>
              </tr></thead>
              <tbody>${stageRows}</tbody>
            </table>
          </div>
        </div>
        ${addBtnHtml}
      </div>`;
  }

  async function addToWatchlist(ticker) {
    const btn = $('btn-add-wl-' + ticker);
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Ajout…'; }
    try {
      await apiPost(`/investissement/watchlist/add?ticker=${encodeURIComponent(ticker)}`, 15_000);
      _INV_WATCHLIST.add(ticker);
      if (btn) {
        btn.textContent = '✓ Ajouté';
        btn.style.color = '#4ade80';
        btn.style.borderColor = '#4ade80';
      }
      toast(`✓ ${ticker} ajouté à la watchlist`, 'ok');
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = '➕ Ajouter à la watchlist'; }
      toast(`Impossible d'ajouter ${ticker}`, 'error');
    }
  }

  // ── Liquidité / Black Swan ────────────────────────────────

  const BS_NIVEAU_STYLE = {
    CRITIQUE: { bg: '#3a1010', border: '#e53935', color: '#ff6b6b', label: 'CRITIQUE — MODE BARBELL ACTIVÉ' },
    WARNING:  { bg: '#2c2200', border: '#f9a825', color: '#ffd54f', label: 'WARNING — Surveillance renforcée' },
    NORMAL:   { bg: '#0d1f0d', border: '#43a047', color: '#81c784', label: 'NORMAL — Marchés stables' },
    INCONNU:  { bg: 'var(--bg2)', border: 'var(--border)', color: 'var(--muted)', label: 'Données indisponibles' },
  };

  let _liquiditeRetryTimer = null;

  async function loadLiquidite() {
    if (_liquiditeRetryTimer) { clearTimeout(_liquiditeRetryTimer); _liquiditeRetryTimer = null; }

    // Fetch Black Swan + DSPX + Bertez en parallèle
    const [bsResult, dspxResult, bertezResult] = await Promise.allSettled([
      apiFetch('/blackswan/etat',   15_000),
      apiFetch('/dspx/etat',        10_000),
      apiFetch('/bertez/analyse',   10_000),
    ]);

    const bsData     = bsResult.status     === 'fulfilled' ? bsResult.value     : null;
    const dspxData   = dspxResult.status   === 'fulfilled' ? dspxResult.value   : null;
    const bertezData = bertezResult.status === 'fulfilled' ? bertezResult.value : null;

    if (!bsData) {
      $('bs-banner').textContent = 'API Black Swan indisponible — backend hors ligne';
      return;
    }

    // Si les données ne sont pas encore disponibles (warm-up en cours), retry automatique
    const niveau = bsData.niveau || 'INCONNU';
    if (niveau === 'INCONNU' && bsData.message === 'Pas encore de scan effectué') {
      $('bs-banner').textContent = '⏳ Scan initial en cours — actualisation dans 15s…';
      _liquiditeRetryTimer = setTimeout(loadLiquidite, 15_000);
      return;
    }

    renderLiquidite(bsData);
    $('bs-time').textContent = 'Mis à jour ' + timeAgo(bsData.timestamp);

    if (dspxData)   renderDSPX(dspxData);
    if (bertezData) renderBertez(bertezData);
  }

  function renderDSPX(d) {
    if (!d || d.regime === 'INCONNU') return;

    const REGIME_BADGE = {
      FORTE:   { bg: '#1a3a1a', color: '#81c784', label: 'FORTE — Stock-Picking' },
      NORMALE: { bg: '#1a2a3a', color: '#64b5f6', label: 'NORMALE — Mixte' },
      FAIBLE:  { bg: '#3a2a10', color: '#ffd54f', label: 'FAIBLE — Beta Only' },
      INCONNU: { bg: 'var(--bg3)', color: 'var(--muted)', label: '—' },
    };
    const s = REGIME_BADGE[d.regime] || REGIME_BADGE.INCONNU;
    const badge = $('bs-dspx-regime-badge');
    badge.textContent     = s.label;
    badge.style.background = s.bg;
    badge.style.color      = s.color;

    const dspx2 = $('bs-dspx2');
    dspx2.textContent  = d.dspx != null ? d.dspx.toFixed(1) : '—';
    dspx2.className    = 'kpi-val ' + (
      d.dspx == null ? 'neu' : d.dspx >= 25 ? 'pos' : d.dspx <= 12 ? 'warn' : 'neu'
    );
    $('bs-dspx-pct').textContent = d.dspx_pct50j != null ? d.dspx_pct50j.toFixed(0) + 'e pct.' : '—';

    const ALPHA_STYLE = {
      STOCK_PICKING: { cls: 'pos', sub: 'Titres indépendants — alpha accessible' },
      BETA_ONLY:     { cls: 'warn', sub: 'Corrélation élevée — préférer ETF' },
      NEUTRE:        { cls: 'neu',  sub: 'Régime mixte' },
    };
    const as = ALPHA_STYLE[d.signal_alpha] || ALPHA_STYLE.NEUTRE;
    const alphaEl = $('bs-dspx-alpha');
    alphaEl.textContent = d.signal_alpha || '—';
    alphaEl.className   = 'kpi-val ' + as.cls;
    $('bs-dspx-alpha-sub').textContent = as.sub;

    const corrMoy = $('bs-dspx-corr-moy');
    corrMoy.textContent = d.corr_moyenne != null ? d.corr_moyenne.toFixed(2) : '—';
    corrMoy.className   = 'kpi-val ' + (d.corr_moyenne == null ? 'neu' : d.corr_moyenne >= 0.6 ? 'neg' : d.corr_moyenne <= 0.2 ? 'pos' : 'neu');
    $('bs-dspx-corr-regime').textContent = d.regime_corr || '—';

    const msgs = d.interpretation || [];
    $('bs-dspx-messages').innerHTML = msgs.length
      ? msgs.map(m => `<div>${m}</div>`).join('')
      : '<span style="color:var(--muted)">Aucun message.</span>';
  }

  function renderBertez(d) {
    if (!d) return;

    const SIGNAL_STYLE = {
      ACHAT_REELS: { bg: '#1a3a1a', color: '#81c784', label: 'ACHAT ACTIFS RÉELS' },
      VENTE_REELS: { bg: '#3a1010', color: '#ff6b6b', label: 'VENTE ACTIFS RÉELS' },
      NEUTRE:      { bg: 'var(--bg3)', color: 'var(--muted)', label: 'NEUTRE' },
    };
    const REGIME_CLS = {
      STAGFLATION:  'neg',
      REFLATION:    'warn',
      DESINFLATION: 'pos',
      NEUTRE:       'neu',
    };
    const ss = SIGNAL_STYLE[d.signal] || SIGNAL_STYLE.NEUTRE;
    const badge = $('bs-bertez-signal-badge');
    badge.textContent      = ss.label;
    badge.style.background = ss.bg;
    badge.style.color      = ss.color;

    const wtiEl = $('bs-bertez-wti');
    wtiEl.textContent = d.wti_prix != null ? d.wti_prix.toFixed(1) : '—';
    wtiEl.className   = 'kpi-val ' + (d.wti_prix == null ? 'neu' : d.wti_prix > 85 ? 'neg' : d.wti_prix < 65 ? 'pos' : 'neu');

    const v5 = $('bs-bertez-var5');
    v5.textContent = d.wti_variation_5j != null ? (d.wti_variation_5j > 0 ? '+' : '') + d.wti_variation_5j.toFixed(1) + '%' : '—';
    v5.className   = 'kpi-val ' + (d.wti_variation_5j == null ? 'neu' : d.wti_variation_5j > 0 ? 'neg' : 'pos');

    $('bs-bertez-var30').textContent = d.wti_variation_30j != null ? (d.wti_variation_30j > 0 ? '+' : '') + d.wti_variation_30j.toFixed(1) + '%' : '—';

    const tendEl = $('bs-bertez-tendance');
    tendEl.textContent = d.tendance_wti || '—';
    tendEl.className   = 'kpi-val ' + ({ HAUSSE: 'neg', BAISSE: 'pos', NEUTRE: 'neu' }[d.tendance_wti] || 'neu');

    const regEl = $('bs-bertez-regime');
    regEl.textContent = d.regime_macro || '—';
    regEl.className   = 'kpi-val ' + (REGIME_CLS[d.regime_macro] || 'neu');

    $('bs-bertez-these').textContent = d.these_bertez || '—';

    const ok  = d.actifs_recommandes || [];
    const nok = d.actifs_eviter || [];
    let actifsHtml = '';
    if (ok.length)  actifsHtml += `<div style="margin-bottom:4px"><span style="color:#81c784;font-weight:600">✓ Privilégier :</span> ${ok.join(', ')}</div>`;
    if (nok.length) actifsHtml += `<div><span style="color:#ff6b6b;font-weight:600">✗ Éviter :</span> ${nok.join(', ')}</div>`;
    $('bs-bertez-actifs').innerHTML = actifsHtml || '—';
  }

  function renderLiquidite(data) {
    const niveau  = data.niveau  || 'INCONNU';
    const mode    = data.mode_portefeuille || '—';
    const indic   = data.indicateurs || {};
    const style   = BS_NIVEAU_STYLE[niveau] || BS_NIVEAU_STYLE.INCONNU;

    // Bannière niveau
    const banner = $('bs-banner');
    banner.style.background   = style.bg;
    banner.style.borderColor  = style.border;
    banner.style.color        = style.color;
    banner.textContent        = style.label;

    // KPIs
    const vix = indic.vix;
    const vixEl = $('bs-vix');
    vixEl.textContent = vix != null ? vix.toFixed(1) : '—';
    vixEl.className = 'kpi-val ' + (
      vix == null ? 'neu' : vix > 34 ? 'neg' : vix > 25 ? 'warn' : 'pos'
    );
    if (indic.vix_variation_24h != null) {
      $('bs-vix-var').textContent = `Var. 24h : ${indic.vix_variation_24h > 0 ? '+' : ''}${indic.vix_variation_24h.toFixed(1)}% · seuil critique : 34`;
    }

    const dspx = indic.dspx;
    const dspxEl = $('bs-dspx');
    dspxEl.textContent = dspx != null ? dspx.toFixed(1) : '—';
    dspxEl.className = 'kpi-val ' + (dspx == null ? 'neu' : dspx > 140 ? 'neg' : 'neu');

    const spread = indic.credit_spread_hy;
    const spreadEl = $('bs-spread');
    spreadEl.textContent = spread != null ? spread.toFixed(0) : '—';
    spreadEl.className = 'kpi-val ' + (
      spread == null ? 'neu' : spread > 700 ? 'neg' : spread > 500 ? 'warn' : 'pos'
    );

    const corr = indic.correlation_spy_tlt;
    const corrEl = $('bs-corr');
    corrEl.textContent = corr != null ? corr.toFixed(2) : '—';
    corrEl.className = 'kpi-val ' + (corr == null ? 'neu' : corr < -0.6 ? 'neg' : 'neu');

    // Mode portefeuille
    const modeEl = $('bs-mode-detail');
    if (mode === 'BARBELL') {
      modeEl.innerHTML = '<strong style="color:#ff6b6b">MODE BARBELL ACTIF</strong> — ' +
        '80% cash / Or (GC=F, IAU) / GTT (GTT.PA) / Vopak (VPK.AS) · ' +
        '20% défensifs (Utilities, T-Bills, Bund)';
    } else {
      modeEl.innerHTML = '<strong style="color:#81c784">MODE NORMAL</strong> — Allocation standard maintenue.';
    }

    // Traders stoppés
    const stoppes = data.traders_momentum_stoppes || [];
    const tradersEl = $('bs-traders-list');
    if (stoppes.length > 0) {
      tradersEl.innerHTML = '<div style="color:#ff6b6b;margin-bottom:8px;font-weight:600">STOP TRADING — ' +
        stoppes.length + ' traders momentum suspendus :</div>' +
        stoppes.map(id => `<span style="background:#3a1010;border:1px solid #e53935;border-radius:4px;padding:2px 8px;margin:2px;display:inline-block">${id}</span>`).join('');
    } else {
      tradersEl.innerHTML = '<span style="color:#81c784">Tous les traders momentum actifs (VIX normal).</span>';
    }

    // Actifs barbell
    const actifs   = data.actifs_recommandes || {};
    const actifsEl = $('bs-actifs-detail');
    if (mode === 'BARBELL' && Object.keys(actifs).some(k => (actifs[k] || []).length > 0)) {
      const rows = Object.entries(actifs)
        .filter(([, v]) => v && v.length > 0)
        .map(([cat, tickers]) =>
          `<div style="margin:4px 0"><strong>${cat.toUpperCase()}</strong> : ${tickers.join(', ')}</div>`
        ).join('');
      actifsEl.innerHTML = rows || '—';
    } else {
      actifsEl.innerHTML = 'Mode normal — pas d\'allocation barbell active.';
    }

    // Messages analyse
    const msgs = data.messages_analyse || [];
    $('bs-messages').innerHTML = msgs.length
      ? msgs.map(m => `<div>${m}</div>`).join('')
      : '<span style="color:var(--muted)">Aucun message d\'analyse.</span>';
  }

  async function blackswanScan() {
    const btn = $('bs-scan-btn');
    btn.disabled = true;
    btn.textContent = '⏳ Scan…';
    toast('Scan Black Swan démarré…', 'info');
    try {
      const data = await apiPost('/blackswan/scan', 30_000);
      renderLiquidite(data);
      $('bs-time').textContent = 'Mis à jour ' + timeAgo(data.timestamp);
      toast('✓ Scan Black Swan terminé', 'ok');
    } catch (e) {
      toast('Erreur scan Black Swan', 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = '▶ Scanner';
    }
  }

  async function loadIntelligence() {
    $('intel-articles').innerHTML = '<div style="text-align:center;padding:30px;color:var(--muted)"><div class="spinner"></div><p style="margin-top:10px">Chargement des flux RSS…</p></div>';
    $('intel-sources').innerHTML  = '<div style="color:var(--muted);font-size:12px;padding:16px">Chargement…</div>';
    let data;
    try {
      data = await apiFetch('/veille-strategique', 30_000);
    } catch (e) {
      $('intel-articles').innerHTML = '<span style="color:var(--muted);padding:16px;display:block">Erreur chargement veille stratégique.</span>';
      $('intel-sources').innerHTML  = '';
    }
    if (data) {
      state.intelligence = data;
      renderIntelligence(data);
    }
    // Charger Flux Macro et Alpha Lab en parallèle (non bloquant)
    loadFluxMacro().catch(() => {});
    loadAlphaLab().catch(() => {});
  }

  function renderIntelligence(data) {
    const articles = data.articles || [];
    const etat     = data.etat    || {};

    $('intel-total').textContent     = etat.nb_total    ?? articles.length;
    $('intel-critique').textContent  = etat.nb_critique ?? 0;
    $('intel-important').textContent = etat.nb_important ?? 0;
    $('intel-info').textContent      = etat.nb_info     ?? 0;
    $('intel-time').textContent      = etat.derniere_maj ? 'Mis à jour ' + timeAgo(etat.derniere_maj) : '—';

    if (!articles.length) {
      $('intel-articles').innerHTML = '<span style="color:var(--muted);padding:16px;display:block">Aucun article disponible — flux RSS vides ou inaccessibles.</span>';
      $('intel-sources').innerHTML  = '';
      return;
    }

    const BADGE = {
      CRITIQUE:  '<span style="background:#c0392b;color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;margin-right:6px">CRITIQUE</span>',
      IMPORTANT: '<span style="background:#e67e22;color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;margin-right:6px">IMPORTANT</span>',
      INFO:      '<span style="background:var(--bg3);color:var(--muted);font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;margin-right:6px">INFO</span>',
    };
    const BORDER = { CRITIQUE: '#c0392b', IMPORTANT: '#e67e22', INFO: 'var(--border)' };

    function articleCard(a) {
      const themes = (a.themes || []).map(t =>
        `<span style="font-size:10px;color:var(--accent);margin-right:4px">#${t}</span>`
      ).join('');
      const desc = a.description
        ? `<div style="font-size:12px;color:var(--muted);margin-top:4px;line-height:1.5">${a.description.slice(0, 250)}${a.description.length > 250 ? '…' : ''}</div>`
        : '';
      const date = a.publie_a ? `<span style="font-size:10px;color:var(--muted)">${a.publie_a.slice(0, 22)}</span>` : '';
      const link = a.url ? `<a href="${a.url}" target="_blank" rel="noopener" style="font-size:11px;color:var(--accent);margin-left:8px">→ Lire</a>` : '';
      return `<div style="border-left:3px solid ${BORDER[a.niveau] || BORDER.INFO};padding:10px 12px;margin-bottom:10px;background:var(--bg2);border-radius:0 6px 6px 0">
        <div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-bottom:4px">
          ${BADGE[a.niveau] || BADGE.INFO}
          <span style="font-size:11px;color:var(--accent);font-weight:600">${a.source || ''}</span>
          <span style="flex:1"></span>${date}${link}
        </div>
        <div style="font-size:13px;font-weight:600;color:var(--fg)">${a.titre || '—'}</div>
        ${desc}
        <div style="margin-top:4px">${themes}</div>
      </div>`;
    }

    // Tous les articles — CRITIQUE → IMPORTANT → INFO
    const ordre = { CRITIQUE: 0, IMPORTANT: 1, INFO: 2 };
    const sorted = [...articles].sort((a, b) => (ordre[a.niveau] ?? 3) - (ordre[b.niveau] ?? 3));
    $('intel-articles').innerHTML = sorted.map(articleCard).join('') || '<span style="color:var(--muted)">Aucun article.</span>';

    // Actualités filtrées par source
    const SOURCES_CLES = ['Bruno Bertez', 'Ray Dalio', 'CrossBorderCapital', 'InflationGuy'];
    let html2 = '';
    for (const src of SOURCES_CLES) {
      const arts = articles.filter(a => a.source === src);
      const label = src === 'CrossBorderCapital' ? 'Howell (CrossBorderCapital)' : src;
      if (!arts.length) {
        html2 += `<div style="margin-bottom:16px">
          <div style="font-size:12px;font-weight:700;color:var(--fg);margin-bottom:6px;padding-bottom:4px;border-bottom:1px solid var(--border)">${label}</div>
          <span style="color:var(--muted);font-size:12px">Aucun article récent.</span>
        </div>`;
        continue;
      }
      html2 += `<div style="margin-bottom:16px">
        <div style="font-size:12px;font-weight:700;color:var(--fg);margin-bottom:6px;padding-bottom:4px;border-bottom:1px solid var(--border)">${label} — ${arts.length} article${arts.length > 1 ? 's' : ''}</div>
        ${arts.slice(0, 3).map(articleCard).join('')}
      </div>`;
    }
    $('intel-sources').innerHTML = html2;
  }

  // ── Flux Macro — Le Détective de Capitaux ─────────────────────────────────

  async function loadFluxMacro() {
    $('fm-ratios').innerHTML    = '<div style="text-align:center;padding:20px;color:var(--muted)"><div class="spinner"></div></div>';
    $('fm-anomalies').innerHTML = '<div style="color:var(--muted);font-size:12px;padding:16px">Chargement…</div>';
    $('fm-ipos').innerHTML      = '<div style="color:var(--muted);font-size:12px;padding:16px">Chargement…</div>';
    let data;
    try {
      data = await apiFetch('/flux-macro', 60_000);
    } catch (e) {
      $('fm-ratios').innerHTML = '<span style="color:var(--muted);padding:16px;display:block">Erreur chargement Flux Macro.</span>';
      return;
    }
    state.fluxMacro = data;
    renderFluxMacro(data);
  }

  function renderFluxMacro(data) {
    const anomalies = data.anomalies || [];
    const ratios    = data.ratios    || [];
    const ipos      = data.ipos      || [];
    const ts        = data.timestamp ? 'Mis à jour ' + timeAgo(data.timestamp) : '—';

    $('fm-time').textContent = ts;
    $('fm-nb-anomalies').textContent = anomalies.length;
    $('fm-nb-sources').textContent   = data.nb_sources ?? '—';
    $('fm-nb-ipos').textContent      = ipos.length;

    // Confiance coloring
    const conf = data.confiance || '—';
    const confEl = $('fm-confiance');
    confEl.textContent = conf;
    confEl.style.color = conf === 'FORTE' ? 'var(--green)' :
                         conf === 'MOYEN'  ? 'var(--yellow)' :
                         conf === 'FAIBLE' ? '#ff6b35' : 'var(--muted)';

    // ── Ratios ──────────────────────────────────────────────────────────────
    if (!ratios.length) {
      $('fm-ratios').innerHTML = '<span style="color:var(--muted);font-size:12px;padding:16px;display:block">DONNÉES INDISPONIBLES</span>';
    } else {
      $('fm-ratios').innerHTML = `<div style="display:grid;gap:8px;padding:4px 0">${
        ratios.map(r => {
          const alertCls = r.alerte ? 'color:#ff4455' : 'color:var(--green)';
          const icon     = r.alerte ? '🔴' : '🟢';
          const fresh    = r.freshness === 'STALE' ? ' <span style="color:#ff6b35;font-size:9px">STALE</span>' :
                           r.freshness === 'UNAVAILABLE' ? ' <span style="color:var(--muted);font-size:9px">N/A</span>' : '';
          return `<div style="display:flex;align-items:center;gap:10px;padding:8px 10px;background:var(--bg3);border-radius:6px;border-left:3px solid ${r.alerte ? '#ff4455' : 'var(--green)'}">
            <span style="font-size:14px">${icon}</span>
            <div style="flex:1;min-width:0">
              <div style="font-size:12px;font-weight:600;color:var(--fg)">${r.label}${fresh}</div>
              <div style="font-size:11px;color:var(--muted)">${r.detail || ''}</div>
            </div>
            <div style="font-size:13px;font-weight:700;${alertCls};white-space:nowrap">${r.valeur ?? '—'}</div>
          </div>`;
        }).join('')
      }</div>`;
    }

    // ── Anomalies ────────────────────────────────────────────────────────────
    if (!anomalies.length) {
      $('fm-anomalies').innerHTML = '<div style="padding:12px;color:var(--green);font-size:13px">✅ Aucune anomalie significative — marchés dans les normes 30j</div>';
    } else {
      $('fm-anomalies').innerHTML = anomalies.map(a => {
        const lvlColor = a.niveau === 'CRITIQUE' ? '#c0392b' : '#e67e22';
        return `<div style="border-left:3px solid ${lvlColor};padding:10px 12px;margin-bottom:8px;background:var(--bg2);border-radius:0 6px 6px 0">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <span style="background:${lvlColor};color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px">${a.niveau}</span>
            <span style="font-size:12px;font-weight:700;color:var(--fg)">${a.label}</span>
            <span style="margin-left:auto;font-size:11px;color:var(--muted)">${a.timestamp || ''}</span>
          </div>
          <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:12px">
            <span>Valeur : <b style="color:var(--fg)">${a.valeur ?? '—'}</b></span>
            <span>Variation : <b style="color:${a.variation_pct >= 0 ? 'var(--green)' : '#ff4455'}">${a.variation_pct !== undefined ? (a.variation_pct >= 0 ? '+' : '') + a.variation_pct.toFixed(1) + '%' : '—'}</b></span>
            <span>Z-score : <b style="color:#e67e22">${a.z_score !== undefined ? (a.z_score >= 0 ? '+' : '') + a.z_score.toFixed(1) + 'σ' : '—'}</b></span>
          </div>
          ${a.seuil_label ? `<div style="font-size:11px;color:var(--muted);margin-top:4px">⚠️ ${a.seuil_label}</div>` : ''}
        </div>`;
      }).join('');
    }

    // ── IPOs calendrier ──────────────────────────────────────────────────────
    if (!ipos.length) {
      $('fm-ipos').innerHTML = '<span style="color:var(--muted);font-size:12px;padding:16px;display:block">Aucun filing S-1 récent détecté (SEC EDGAR)</span>';
    } else {
      $('fm-ipos').innerHTML = ipos.map(i =>
        `<div style="padding:8px 0;border-bottom:1px solid var(--border)">
          <div style="font-size:12px;font-weight:600;color:var(--fg)">${i.titre}</div>
          <div style="display:flex;gap:10px;font-size:11px;color:var(--muted);margin-top:2px">
            <span>📅 ${i.date}</span>
            ${i.url ? `<a href="${i.url}" target="_blank" rel="noopener" style="color:var(--accent)">→ SEC EDGAR</a>` : ''}
          </div>
        </div>`
      ).join('');
    }

    // ── Conclusion ───────────────────────────────────────────────────────────
    const concl = data.conclusion || '—';
    const action = data.action_suggeree || '';
    const tort   = data.pourquoi_tort   || '';
    $('fm-conclusion').innerHTML =
      `<div style="margin-bottom:10px">${concl}</div>` +
      (action ? `<div style="font-size:12px;color:var(--accent);margin-bottom:8px">📈 ${action}</div>` : '') +
      (tort ? `<details style="margin-top:8px"><summary style="font-size:11px;color:var(--muted);cursor:pointer">⚖️ Pourquoi j'ai tort (biais narratif)</summary><pre style="font-size:11px;color:var(--muted);margin-top:6px;white-space:pre-wrap">${tort}</pre></details>` : '');

    if (data.disclaimer) {
      $('fm-disclaimer').textContent = data.disclaimer;
    }

    // ── Régime de marché ─────────────────────────────────────────────────────
    const regime = data.regime || {};
    const regimeNom = regime.regime || 'NORMAL';
    const regimeBadge = $('fm-regime-badge');
    if (regimeBadge) {
      const REGIME_COLORS = {
        NORMAL:          { bg: 'rgba(0,229,160,0.15)',  color: '#00e5a0', border: '#00e5a0' },
        ROTATION:        { bg: 'rgba(255,213,0,0.15)',  color: '#ffd700', border: '#ffd700' },
        CRISE_LIQUIDITE: { bg: 'rgba(255,68,85,0.15)',  color: '#ff4455', border: '#ff4455' },
        EFFONDREMENT:    { bg: 'rgba(180,76,255,0.15)', color: '#b44cff', border: '#b44cff' },
      };
      const rc = REGIME_COLORS[regimeNom] || REGIME_COLORS.NORMAL;
      regimeBadge.textContent = regimeNom;
      regimeBadge.style.background   = rc.bg;
      regimeBadge.style.color        = rc.color;
      regimeBadge.style.border       = `1px solid ${rc.border}`;
    }
    const regimeDesc = $('fm-regime-desc');
    if (regimeDesc) regimeDesc.textContent = regime.description || '—';
    const regimeProt = $('fm-regime-protection');
    if (regimeProt) {
      regimeProt.textContent = '🛡️ ' + (regime.protection || '—');
    }
    const corrEl  = $('fm-corr-tlt-spy');
    const ratioEl = $('fm-ratio-tlt-spy');
    if (corrEl) {
      const corr = regime.corr_tlt_spy_5j;
      corrEl.textContent = corr !== null && corr !== undefined ? (corr >= 0 ? '+' : '') + corr.toFixed(3) : '—';
      corrEl.style.color = (corr !== null && corr > 0) ? '#ff4455' : 'var(--green)';
    }
    if (ratioEl) {
      ratioEl.textContent = regime.ratio_tlt_spy !== null && regime.ratio_tlt_spy !== undefined
        ? regime.ratio_tlt_spy.toFixed(4) : '—';
    }
    const signauxEl = $('fm-regime-signaux');
    if (signauxEl && regime.signaux && regime.signaux.length) {
      signauxEl.innerHTML = regime.signaux.map(s =>
        `<div style="padding:4px 0">⚡ ${s}</div>`
      ).join('');
    } else if (signauxEl) {
      signauxEl.innerHTML = '';
    }

    // ── Indicateurs liquidité macro ───────────────────────────────────────────
    const liq = data.fred_liquidite || {};
    const liqEl = $('fm-liquidite');
    if (liqEl) {
      // Formatters — FRED units: WALCL en M$ (pas Mds), spreads en % (×100 = bps)
      const LIQ_ITEMS = [
        {
          id: 'M2SL', label: 'M2 (masse monét. US)',
          fmt: (v) => v.toLocaleString('fr-FR', {maximumFractionDigits: 0}) + ' Mds$',
          warn: () => false,
        },
        {
          id: 'WALCL', label: 'Fed balance sheet',
          fmt: (v) => (v / 1000).toLocaleString('fr-FR', {maximumFractionDigits: 0}) + ' Mds$',
          warn: () => false,
        },
        {
          id: 'IORB', label: 'Taux repo Fed (IORB)',
          fmt: (v) => v.toFixed(2) + ' %',
          warn: () => false,
        },
        {
          id: 'BAMLC0A0CM', label: 'Spreads IG (150 bps seuil)',
          fmt: (v) => (v * 100).toFixed(0) + ' bps (' + v.toFixed(2) + '%)',
          warn: (v) => typeof v === 'number' && v > 1.50,
        },
        {
          id: 'BAMLH0A0HYM2', label: 'Spreads HY (500 bps seuil)',
          fmt: (v) => (v * 100).toFixed(0) + ' bps (' + v.toFixed(2) + '%)',
          warn: (v) => typeof v === 'number' && v > 5.00,
        },
      ];
      if (!liq.ok) {
        liqEl.innerHTML = '<span style="color:var(--muted);font-size:12px">DONNÉES INDISPONIBLES — FRED_API_KEY requis</span>';
      } else {
        liqEl.innerHTML = LIQ_ITEMS.map(item => {
          const val = liq[item.id];
          const display = (val === 'DONNÉES INDISPONIBLES' || val === null || val === undefined)
            ? '<span style="color:var(--muted)">DONNÉES INDISPONIBLES</span>'
            : (typeof val === 'number' ? item.fmt(val) : String(val));
          const alerte = typeof val === 'number' ? item.warn(val) : false;
          return `<div style="display:flex;align-items:center;gap:10px;padding:7px 10px;background:var(--bg3);border-radius:6px;border-left:3px solid ${alerte ? '#ff4455' : 'var(--border)'}">
            <span style="font-size:13px">${alerte ? '🔴' : '🔵'}</span>
            <div style="flex:1;font-size:12px;color:var(--muted)">${item.label}</div>
            <div style="font-size:13px;font-weight:700;color:${alerte ? '#ff4455' : 'var(--fg)'}">${display}</div>
          </div>`;
        }).join('');
      }
    }

    // Alertes liquidité (seuils M2/WALCL/spreads dépassés)
    const alertesLiqEl = $('fm-alertes-liquidite');
    if (alertesLiqEl) {
      const alertesLiq = data.alertes_liquidite || [];
      if (alertesLiq.length) {
        alertesLiqEl.innerHTML = alertesLiq.map(a => {
          const col = a.niveau === 'CRITIQUE' ? '#c0392b' : '#e67e22';
          return `<div style="border-left:3px solid ${col};padding:8px 12px;margin-bottom:6px;background:var(--bg2);border-radius:0 6px 6px 0;font-size:12px">
            <span style="background:${col};color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;margin-right:8px">${a.niveau}</span>
            <b>${a.label}</b> — ${a.valeur} (seuil: ${a.seuil})
          </div>`;
        }).join('');
      } else {
        alertesLiqEl.innerHTML = '';
      }
    }
  }

  async function loadRetraite() {
    const [retResult, pruResult] = await Promise.allSettled([
      apiFetch('/patrimoine/retraite', 15_000),
      apiFetch('/patrimoine/positions-pru', 15_000),
    ]);

    if (retResult.status === 'fulfilled') {
      const d = retResult.value;
      state.retraite = d;
      const base = d.base_investissable || 0;
      const obj  = d.objectif || 0;
      const pct  = obj > 0 ? (base / obj * 100) : 0;
      $('ret-base').textContent      = fmt(base, 0) + ' €';
      $('ret-objectif').textContent  = fmt(obj, 0) + ' €';
      $('ret-apport').textContent    = fmt(d.apport_mensuel || 0, 0) + ' €/mois';
      $('ret-jours').textContent     = (d.jours_restants || 0).toLocaleString('fr-FR');
      $('ret-taux').textContent      = ((d.taux_annuel || 0) * 100).toFixed(0) + '%';
      $('ret-pct-label').textContent = pct.toFixed(2) + '%';
      $('ret-progress-label').textContent = fmt(base, 0) + ' € / ' + fmt(obj, 0) + ' €';
      $('ret-progress-fill').style.width = Math.min(pct, 100) + '%';
      $('ret-time').textContent = 'Mis à jour ' + timeAgo(new Date().toISOString());
    } else {
      $('ret-base').textContent = 'Erreur API';
    }

    if (pruResult.status === 'fulfilled') {
      renderPositionsPRU(pruResult.value);
    }
  }

  function renderPositionsPRU(data) {
    const container = $('ret-positions');
    const raw = Array.isArray(data) ? data : (data.positions || {});
    const positions = Array.isArray(raw) ? raw : Object.values(raw);
    if (!positions.length) {
      container.innerHTML = '<span style="color:var(--muted)">Aucune position enregistrée.</span>';
      return;
    }
    const rows = positions.map(p => {
      const pru        = p.pru || 0;
      const prixActuel = p.prix_actuel || 0;
      const qte        = p.quantite || 0;
      const pvUnit     = prixActuel - pru;
      const pvTotal    = pvUnit * qte;
      const pvPct      = pru > 0 ? (pvUnit / pru * 100) : 0;
      return `<tr>
        <td><strong>${p.ticker || '—'}</strong></td>
        <td>${pru.toFixed(2)} €</td>
        <td>${prixActuel > 0 ? prixActuel.toFixed(2) + ' €' : '<span style="color:var(--muted)">—</span>'}</td>
        <td class="${pnlClass(pvTotal)}">${(pvTotal >= 0 ? '+' : '') + pvTotal.toFixed(2) + ' €'}</td>
        <td class="${pnlClass(pvPct)}">${pvPct.toFixed(2)}%</td>
        <td style="color:var(--muted)">${qte}</td>
      </tr>`;
    }).join('');
    container.innerHTML = `<div class="table-wrap"><table class="data-table">
      <thead><tr>
        <th>Ticker</th><th>PRU</th><th>Prix live</th><th>PV/MV €</th><th>PV/MV %</th><th>Qté</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
  }

  async function loadDividendes() {
    let data;
    try {
      data = await apiFetch('/dividendes', 20_000);
    } catch (e) {
      $('div-table').innerHTML = '<span style="color:var(--muted)">Erreur API dividendes.</span>';
      return;
    }
    state.dividendes = data;

    const revM  = data.revenu_mensuel_total || 0;
    const obj   = data.objectif_mensuel    || 0;
    const ecart = data.ecart_objectif      || 0;
    const pct   = obj > 0 ? Math.min(revM / obj * 100, 100) : 0;

    $('div-rev-mensuel').textContent = revM.toFixed(2) + ' €';
    $('div-objectif').textContent    = obj.toFixed(0) + ' €';
    $('div-ecart').textContent       = (ecart >= 0 ? '+' : '') + ecart.toFixed(2) + ' €';
    $('div-ecart').className         = 'kpi-val ' + (ecart >= 0 ? 'pos' : 'neg');
    $('div-fiables').textContent     = data.nb_dividendes_fiables || 0;
    $('div-coupes').textContent      = data.nb_coupes_detectees   || 0;
    $('div-coupes').className        = 'kpi-val ' + ((data.nb_coupes_detectees || 0) > 0 ? 'neg' : 'neu');
    $('div-pct-label').textContent   = pct.toFixed(1) + '%';
    $('div-progress-label').textContent = revM.toFixed(2) + ' € / ' + obj.toFixed(0) + ' €';
    $('div-progress-fill').style.width  = pct + '%';
    $('div-time').textContent = data.timestamp ? 'Mis à jour ' + timeAgo(data.timestamp) : '—';

    renderDividendes(data.positions || []);
  }

  function renderDividendes(positions) {
    if (!positions.length) {
      $('div-table').innerHTML = '<span style="color:var(--muted)">Aucune position.</span>';
      return;
    }
    const rows = positions.map(p => {
      const sc      = p.scoring || {};
      const score   = sc.score != null ? sc.score.toFixed(1) : '—';
      const fiable   = sc.fiable;
      const coupe    = p.coupe_detectee;
      const isReit   = p.is_reit || sc.is_reit;
      const yld      = p.div_yield != null ? p.div_yield.toFixed(1) + '%' : '—';
      const payoutVal= p.payout_ratio != null ? p.payout_ratio.toFixed(0) + '%' : '—';
      const payoutCell = isReit
        ? `<span style="color:var(--muted)">${payoutVal} <span style="font-size:10px">(FFO)</span></span>`
        : `<span class="${parseFloat(payoutVal) > 100 ? 'neg' : parseFloat(payoutVal) > 75 ? 'warn' : 'pos'}">${payoutVal}</span>`;
      const scoreClass = sc.score >= 6 ? 'pos' : sc.score >= 3 ? 'warn' : 'neg';
      return `<tr${coupe ? ' style="background:rgba(239,68,68,.06)"' : ''}>
        <td><strong>${p.ticker || '—'}</strong>${coupe ? ' <span style="color:#ef4444;font-size:10px">✂ COUPE</span>' : ''}${isReit ? ' <span style="color:var(--muted);font-size:10px">REIT</span>' : ''}</td>
        <td style="color:var(--muted)">${p.nom || '—'}</td>
        <td>${(p.montant_investi || 0).toFixed(0)} €</td>
        <td>${p.prix != null ? p.prix.toFixed(2) + ' €' : '—'}</td>
        <td>${p.div_annuel_action != null ? p.div_annuel_action.toFixed(2) + ' €' : '—'}</td>
        <td class="${parseFloat(yld) > 10 ? 'warn' : 'pos'}">${yld}</td>
        <td class="pos">${(p.rev_mensuel || 0).toFixed(2)} €</td>
        <td>${payoutCell}</td>
        <td class="${scoreClass}">${score}/10</td>
        <td>${fiable ? '<span style="color:#22c55e;font-weight:700">✓</span>' : '<span style="color:var(--muted)">—</span>'}</td>
      </tr>`;
    }).join('');
    $('div-table').innerHTML = `<table class="data-table">
      <thead><tr>
        <th>Ticker</th><th>Nom</th><th>Investi</th><th>Prix</th>
        <th>Div/action</th><th>Rendement</th><th>Rev/mois</th>
        <th>Payout</th><th>Score</th><th>Fiable</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  }

  // ── Alpha Lab — Backtests Signaux & Facteurs Académiques ──────────────────

  async function loadAlphaLab() {
    $('al-signaux-table').innerHTML  = '<div style="text-align:center;padding:20px;color:var(--muted)"><div class="spinner"></div></div>';
    $('al-facteurs-table').innerHTML = '<div style="text-align:center;padding:20px;color:var(--muted)"><div class="spinner"></div></div>';
    $('al-crises-table').innerHTML   = '<div style="color:var(--muted);font-size:12px;padding:16px">Chargement…</div>';
    let data;
    try {
      data = await apiFetch('/alpha-lab/rapport', 90_000);
    } catch (e) {
      $('al-signaux-table').innerHTML = '<span style="color:var(--muted);padding:16px;display:block">Erreur chargement Alpha Lab.</span>';
      return;
    }
    state.alphaLab = data;
    renderAlphaLab(data);
  }

  function renderAlphaLab(data) {
    const signaux  = data.signaux  || {};
    const facteurs = data.facteurs || {};
    const ts       = data.signaux && data.signaux.ts ? 'Mis à jour ' + timeAgo(data.signaux.ts) : '—';

    $('al-time').textContent = ts;

    // ── KPIs ────────────────────────────────────────────────────────────────
    const nSignaux  = (data.signaux || {}).n_signaux || Object.keys(signaux.signaux || {}).length;
    const valides   = (data.signaux || {}).valides || [];
    $('al-n-signaux').textContent = (data.signaux || {}).n_signaux ?? '—';
    $('al-n-valides').textContent = valides.length;

    const sigData   = (data.signaux || {}).signaux || {};
    const VERDICT_COLOR = { VALIDE: 'var(--green)', BRUIT: 'var(--muted)', OVERFITTE: 'var(--yellow)', INCONNU: 'var(--muted)' };
    const VERDICT_ICON  = { VALIDE: '✅', BRUIT: '🔇', OVERFITTE: '⚠️', INCONNU: '—' };

    const trendf = sigData.TrendFollow;
    if (trendf) {
      const el = $('al-trendf-verdict');
      el.textContent  = VERDICT_ICON[trendf.verdict] + ' ' + trendf.verdict;
      el.style.color  = VERDICT_COLOR[trendf.verdict];
      $('al-trendf-sub').textContent = 'OOS ' + (trendf.sharpe_oos !== undefined ? trendf.sharpe_oos.toFixed(2) : '—');
    }

    const bertez = sigData.Bertez_Energy;
    if (bertez) {
      const el = $('al-bertez-verdict');
      el.textContent  = VERDICT_ICON[bertez.verdict] + ' ' + bertez.verdict;
      el.style.color  = VERDICT_COLOR[bertez.verdict];
      $('al-bertez-sub').textContent = 'OOS ' + (bertez.sharpe_oos !== undefined ? bertez.sharpe_oos.toFixed(2) : '—');
    }

    // ── Badge régime cohérent (Bloc 4) ─────────────────────────────────────
    const badge = $('al-regime-badge');
    if ((data.signaux || {}).signal_regime_coherent) {
      badge.style.display = 'block';
    } else {
      badge.style.display = 'none';
    }

    // ── Table backtests ──────────────────────────────────────────────────────
    const sigEntries = Object.entries(sigData);
    if (!sigEntries.length) {
      $('al-signaux-table').innerHTML = '<span style="color:var(--muted);font-size:12px;padding:16px;display:block">Aucun signal disponible.</span>';
    } else {
      const rows = sigEntries.map(([name, s]) => {
        const vc = VERDICT_COLOR[s.verdict] || 'var(--muted)';
        const vi = VERDICT_ICON[s.verdict]  || '—';
        const mdd = s.max_drawdown !== undefined ? (s.max_drawdown * 100).toFixed(1) + '%' : '—';
        return `<tr>
          <td style="font-weight:600;color:var(--fg)">${name}</td>
          <td style="color:${s.sharpe_is >= 0.5 ? 'var(--green)' : 'var(--muted)'}">${s.sharpe_is !== undefined ? s.sharpe_is.toFixed(3) : '—'}</td>
          <td style="color:${s.sharpe_oos >= 0.5 ? 'var(--green)' : s.sharpe_oos < 0.25 ? '#ff4455' : 'var(--yellow)'}">${s.sharpe_oos !== undefined ? s.sharpe_oos.toFixed(3) : '—'}</td>
          <td style="color:${Math.abs(s.t_stat || 0) >= 2 ? 'var(--green)' : 'var(--muted)'}">${s.t_stat !== undefined ? s.t_stat.toFixed(2) : '—'}</td>
          <td style="color:#ff6b35">${mdd}</td>
          <td style="font-weight:700;color:${vc}">${vi} ${s.verdict}</td>
        </tr>`;
      }).join('');
      $('al-signaux-table').innerHTML = `<div style="overflow-x:auto"><table class="data-table">
        <thead><tr>
          <th>Signal</th><th>Sharpe IS</th><th>Sharpe OOS</th><th>t-stat</th><th>Max DD</th><th>Verdict</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <div style="font-size:10px;color:var(--muted);margin-top:8px;padding:0 4px">
        Seuils : VALIDE si |t|≥2 &amp; Sharpe OOS≥0.50 · OVERFITTE si |t|≥2 &amp; Sharpe OOS&lt;0.25 · sinon BRUIT
      </div>`;
    }

    // ── Table facteurs watchlist ─────────────────────────────────────────────
    const actifs = (facteurs.actifs || []);
    if (!actifs.length) {
      $('al-facteurs-table').innerHTML = '<span style="color:var(--muted);font-size:12px;padding:16px;display:block">Données facteurs indisponibles.</span>';
    } else {
      const frows = actifs.map(a => {
        const sc    = a.scores || {};
        const rank  = a.composite_rank;
        const rankColor = rank >= 75 ? 'var(--green)' : rank >= 40 ? 'var(--yellow)' : '#ff4455';
        const err   = a.erreur ? `<span style="color:var(--muted);font-size:10px">${a.erreur.slice(0,40)}</span>` : '';
        return `<tr>
          <td style="font-weight:600;color:var(--accent)">${a.ticker}${err}</td>
          <td>${sc.value   !== undefined ? sc.value.toFixed(0)    : '—'}</td>
          <td>${sc.momentum !== undefined ? sc.momentum.toFixed(0) : '—'}</td>
          <td>${sc.quality  !== undefined ? sc.quality.toFixed(0)  : '—'}</td>
          <td>${sc.lowvol   !== undefined ? sc.lowvol.toFixed(0)   : '—'}</td>
          <td style="font-weight:700;color:var(--fg)">${a.composite !== undefined ? a.composite.toFixed(1) : '—'}</td>
          <td style="font-weight:700;color:${rankColor}">${rank !== undefined ? rank.toFixed(0) + '%' : '—'}</td>
        </tr>`;
      }).join('');
      $('al-facteurs-table').innerHTML = `<div style="overflow-x:auto"><table class="data-table">
        <thead><tr>
          <th>Ticker</th><th>Value</th><th>Momentum</th><th>Quality</th><th>LowVol</th><th>Composite</th><th>Rang %</th>
        </tr></thead>
        <tbody>${frows}</tbody>
      </table></div>
      <div style="font-size:10px;color:var(--muted);margin-top:8px;padding:0 4px">
        Poids égaux 25% chacun · Rang% : 100 = meilleur cross-sectionnel
      </div>`;
    }

    // ── Crises — signal TrendFollow ─────────────────────────────────────────
    const crisesData = trendf && trendf.crises_perf ? trendf.crises_perf : null;
    if (!crisesData || !Object.keys(crisesData).length) {
      $('al-crises-table').innerHTML = '<span style="color:var(--muted);font-size:12px;padding:16px;display:block">Données crises non disponibles.</span>';
    } else {
      const crows = Object.entries(crisesData).map(([name, c]) => {
        const ret   = c.rendement_total !== undefined ? (c.rendement_total * 100).toFixed(1) + '%' : '—';
        const retColor = c.rendement_total >= 0 ? 'var(--green)' : '#ff4455';
        const sh    = c.sharpe !== undefined ? c.sharpe.toFixed(2) : '—';
        return `<tr>
          <td style="font-weight:600;color:var(--fg)">${name.replace(/_/g, ' ')}</td>
          <td style="color:var(--muted);font-size:11px">${c.periode || '—'}</td>
          <td>${c.n_mois || '—'} mois</td>
          <td style="font-weight:700;color:${retColor}">${ret}</td>
          <td style="color:${parseFloat(sh) >= 0.5 ? 'var(--green)' : 'var(--muted)'}">${sh}</td>
        </tr>`;
      }).join('');
      $('al-crises-table').innerHTML = `<div style="overflow-x:auto"><table class="data-table">
        <thead><tr>
          <th>Crise</th><th>Période</th><th>Durée</th><th>Rendement total</th><th>Sharpe</th>
        </tr></thead>
        <tbody>${crows}</tbody>
      </table></div>`;
    }
  }

  // ── Public API ────────────────────────────────────────────
  window.App = {
    refresh(tab) {
      const loaders = {
        classement:     loadClassement,
        morning:        loadMorning,
        postmarket:     loadPostmarket,
        scheduler:      loadScheduler,
        macro:          loadMacro,
        alertes:        loadAlertes,
        intelligence:   loadIntelligence,
        investissement: loadInvestissement,
        liquidite:      loadLiquidite,
        retraite:       loadRetraite,
        dividendes:     loadDividendes,
      };
      const fn = loaders[tab];
      if (fn) fn().catch(() => {});
    },
    forceCheck:           () => forceCheck().catch(() => {}),
    fixDb:                () => fixDb().catch(() => {}),
    runScreener:          () => runScreener().catch(() => {}),
    blackswanScan:        () => blackswanScan().catch(() => {}),
    analyzeTickerSearch:  () => analyzeTickerSearch().catch(() => {}),
    addToWatchlist:       ticker => addToWatchlist(ticker).catch(() => {}),
    refreshFluxMacro:     () => loadFluxMacro().catch(() => {}),
    refreshAlphaLab:      () => loadAlphaLab().catch(() => {}),
  };

  // ── Init ──────────────────────────────────────────────────
  function init() {
    initTabs();
    initFilters();
    connectWS();
    loadClassement();

    // Polling auto toutes les 30s sur l'onglet actif
    setInterval(() => {
      App.refresh(state.activeTab);
    }, REFRESH_INTERVAL);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();

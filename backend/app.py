import json
import os
import queue
import threading
import logging
import sys
from datetime import datetime
from pathlib import Path

import requests as _requests
from flask import Flask, jsonify
from flask_sock import Sock
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

sys.path.insert(0, str(Path(__file__).parent))

from engine import TradingEngine
from data.morning_brief import get_morning_brief
from config import TICK_INTERVAL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def _send_telegram(message: str) -> None:
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning(
            "Telegram: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID absent — alerte non envoyée"
        )
        return
    try:
        resp = _requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=5,
        )
        resp.raise_for_status()
        logger.info("Telegram: alerte envoyée (HTTP %d)", resp.status_code)
    except Exception as exc:
        logger.warning("Telegram alert failed: %s", exc)

app = Flask(__name__, static_folder="../frontend", static_url_path="")
sock = Sock(app)

engine = TradingEngine()
_ws_queues: list[queue.Queue] = []
_ws_lock = threading.Lock()


def _broadcast(state: dict):
    payload = json.dumps(state)
    with _ws_lock:
        dead = []
        for q in _ws_queues:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _ws_queues.remove(q)


# ------------------------------------------------------------------
# REST endpoints
# ------------------------------------------------------------------

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/state")
def get_state():
    return jsonify(engine.get_state())


@app.route("/api/battle")
def get_battle():
    return jsonify(engine.get_battle_info())


@app.route("/api/divisions")
def get_divisions():
    return jsonify(engine.get_divisions())


@app.route("/api/brief")
def get_brief():
    brief_obj = get_morning_brief()
    prices    = engine._last_prices or {}
    brief     = brief_obj.get_brief(prices)
    return jsonify(brief)


@app.route("/api/liquidite")
def get_liquidite():
    from divisions.middle_office import get_liquidity_desk
    desk = get_liquidity_desk()
    data = desk.get_data()
    return jsonify({
        "global_liquidity_score": data.get("global_liquidity_score"),
        "regime":                 data.get("regime"),
        "agent_scores":           data.get("agent_scores", {}),
        "agent_summaries":        data.get("agent_summaries", {}),
        "alerts":                 data.get("alerts", []),
        "errors":                 data.get("errors", []),
        "timestamp":              data.get("timestamp"),
        "bertez_signal":          data.get("bertez_signal"),
        "bertez_mode":            data.get("bertez_mode"),
    })


@app.route("/api/liquidite/refresh", methods=["POST"])
def trigger_liquidite_refresh():
    from divisions.middle_office import get_liquidity_desk
    get_liquidity_desk().trigger_background_refresh()
    return jsonify({"status": "refresh triggered"})


@app.route("/api/weekly-agent")
def get_weekly_agent():
    return jsonify(engine.get_weekly_agent())


@app.route("/api/post-market")
def get_post_market():
    return jsonify(engine.get_post_market())


@app.route("/api/investissement/watchlist")
def get_investissement_watchlist():
    from divisions.investissement.watchlist import get_watchlist_manager
    force = False
    try:
        mgr     = get_watchlist_manager()
        results = mgr.analyser_watchlist(force=force)
        return jsonify({"timestamp": datetime.utcnow().isoformat(), "watchlist": results})
    except Exception as e:
        logger.error("investissement watchlist: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/investissement/theses")
def get_investissement_theses():
    from divisions.investissement.watchlist import get_watchlist_manager
    from divisions.investissement.these import get_these_manager
    try:
        watchlist = get_watchlist_manager().analyser_watchlist(force=False)
        theses    = get_these_manager().generer_theses(watchlist)
        return jsonify({"timestamp": datetime.utcnow().isoformat(), "theses": theses})
    except Exception as e:
        logger.error("investissement theses: %s", e)
        return jsonify({"erreur": str(e)}), 500


# ── Patrimoine ────────────────────────────────────────────────────────────────

@app.route("/api/patrimoine")
def get_patrimoine():
    from data.patrimoine import get_patrimoine as _get
    try:
        return jsonify(_get())
    except Exception as e:
        logger.error("patrimoine: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/patrimoine/apport", methods=["POST"])
def add_patrimoine_apport():
    from data.patrimoine import add_apport
    from flask import request
    body = request.get_json(silent=True) or {}
    try:
        montant = float(body.get("montant", 0))
        note    = str(body.get("note", ""))
        apport  = add_apport(montant, note)
        return jsonify({"status": "ok", "apport": apport})
    except ValueError as e:
        return jsonify({"erreur": str(e)}), 400
    except Exception as e:
        logger.error("apport: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/patrimoine/config", methods=["POST"])
def update_patrimoine_config():
    from data.patrimoine import update_config
    from flask import request
    body = request.get_json(silent=True) or {}
    try:
        cfg = update_config(
            taux=body.get("taux_annuel"),
            age=body.get("age_actuel"),
            retraite=body.get("age_retraite"),
            apport_mensuel=body.get("apport_mensuel"),
        )
        return jsonify({"status": "ok", "config": cfg})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/bus/state")
def get_bus_state():
    hub = getattr(engine, "_hub", None)
    if hub is None:
        return jsonify({"erreur": "InterAgentHub non initialisé"}), 503
    return jsonify(hub.get_etat())


@app.route("/api/maintenance/health")
def get_maintenance_health():
    from maintenance import get_health as _health
    from config import DB_PATH
    return jsonify(_health(engine, DB_PATH, len(_ws_queues)))


# ── Gérant Délégué — AGD-01 ───────────────────────────────────────────────────

@app.route("/api/gerant-delegue/etat")
def get_agd_etat():
    try:
        from divisions.gerant_delegue import etat_division
        return jsonify(etat_division())
    except Exception as e:
        logger.error("agd etat: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/gerant-delegue/howell")
def get_agd_howell():
    try:
        from divisions.gerant_delegue import get_gerant_delegue
        return jsonify(get_gerant_delegue().howell_signal())
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/gerant-delegue/evaluer-decision", methods=["POST"])
def post_agd_evaluer():
    from flask import request
    body = request.get_json(silent=True) or {}
    try:
        from divisions.gerant_delegue import get_gerant_delegue
        result = get_gerant_delegue().evaluer_decision(
            ticker          = body.get("ticker", ""),
            action          = body.get("action", "buy"),
            montant         = float(body.get("montant", 0)),
            contexte        = body.get("contexte", ""),
            perf_annualisee = float(body.get("perf_annualisee", 0)),
            patrimoine      = float(body.get("patrimoine", 18082)),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/gerant-delegue/rapport-lundi", methods=["POST"])
def post_agd_rapport():
    from flask import request
    body = request.get_json(silent=True) or {}
    try:
        from divisions.gerant_delegue import get_gerant_delegue
        rapport = get_gerant_delegue().generer_rapport_lundi(body or None)
        return jsonify({"status": "ok", "rapport": rapport})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


# ── Agent Actualités ──────────────────────────────────────────────────────────

@app.route("/api/actualites")
def get_actualites():
    try:
        from divisions.gerant_delegue import get_agent_actualites
        agent = get_agent_actualites()
        return jsonify({
            "articles": agent.analyser(),
            "etat":     agent.etat(),
        })
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/actualites/critiques")
def get_actualites_critiques():
    try:
        from divisions.gerant_delegue import get_agent_actualites
        return jsonify(get_agent_actualites().critiques())
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


# ── Agent Dividendes ──────────────────────────────────────────────────────────

@app.route("/api/dividendes")
def get_dividendes():
    try:
        from divisions.gerant_delegue import get_agent_dividendes
        return jsonify(get_agent_dividendes().analyser())
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


# ── Agent Risk Parity ─────────────────────────────────────────────────────────

@app.route("/api/risk-parity")
def get_risk_parity():
    try:
        from divisions.gerant_delegue import get_agent_risk_parity
        return jsonify(get_agent_risk_parity().analyser())
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


# ── Agent Benchmark ───────────────────────────────────────────────────────────

@app.route("/api/benchmark")
def get_benchmark():
    try:
        from divisions.gerant_delegue import get_agent_benchmark
        return jsonify(get_agent_benchmark().analyser())
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


# ── Comité Sélection ──────────────────────────────────────────────────────────

@app.route("/api/comite-selection/voter", methods=["POST"])
def post_comite_voter():
    from flask import request
    body = request.get_json(silent=True) or {}
    ticker = body.get("ticker", "")
    if not ticker:
        return jsonify({"erreur": "ticker requis"}), 400
    try:
        from divisions.gerant_delegue import get_comite_selection
        verdict = get_comite_selection().voter(ticker, body)
        return jsonify(verdict)
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/comite-selection/historique")
def get_comite_historique():
    try:
        from divisions.gerant_delegue import get_comite_selection
        return jsonify(get_comite_selection().historique())
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/trader/<int:trader_id>")
def get_trader(trader_id: int):
    data = engine.get_trader(trader_id)
    if data is None:
        return jsonify({"error": "Trader not found"}), 404
    return jsonify(data)


# ------------------------------------------------------------------
# WebSocket endpoint
# ------------------------------------------------------------------

@sock.route("/ws")
def websocket(ws):
    q: queue.Queue = queue.Queue(maxsize=20)
    with _ws_lock:
        _ws_queues.append(q)
    # Push current state immediately on connect
    ws.send(json.dumps(engine.get_state()))
    try:
        while True:
            # Block until a tick update arrives; timeout keeps the loop alive
            try:
                msg = q.get(timeout=30)
                ws.send(msg)
            except queue.Empty:
                # Send a heartbeat so the client knows we're still alive
                ws.send(json.dumps({"type": "heartbeat"}))
    except Exception:
        pass
    finally:
        with _ws_lock:
            if q in _ws_queues:
                _ws_queues.remove(q)


# ---------------------------------------------------------------------------
# Scheduler APScheduler — jobs périodiques
# ---------------------------------------------------------------------------

_scheduler = BackgroundScheduler(timezone=pytz.timezone("Europe/Paris"))


def _job_rapport_pdf():
    logger.info("[SCHEDULER] Démarrage job rapport_investisseur (lundi 09:00 Paris)")
    try:
        from divisions.rapports.rapport_investisseur import generer_rapport
        chemin = generer_rapport(engine)
        logger.info("[SCHEDULER] ✓ Rapport PDF confirmé → %s", chemin)
        _send_telegram(f"📄 <b>Rapport investisseur généré</b>\n{chemin}")
    except Exception as exc:
        logger.error("[SCHEDULER] ✗ Rapport PDF ÉCHEC: %s", exc)
        _send_telegram(f"⚠️ Rapport investisseur ÉCHEC: {exc}")


_scheduler.add_job(
    _job_rapport_pdf,
    CronTrigger(day_of_week="mon", hour=9, minute=0),
    id="rapport_investisseur",
    replace_existing=True,
)


def _job_rapport_agd():
    """Rapport hebdomadaire Gérant Délégué — lundi 08:00 Paris (avant PDF 09:00)."""
    logger.info("[SCHEDULER] AGD-01 rapport lundi 08:00")
    try:
        from divisions.gerant_delegue import get_gerant_delegue
        state = engine.get_state() if engine else {}
        traders_sorted = sorted(state.get("traders", []), key=lambda t: t.get("pnl", 0), reverse=True)
        top5 = ", ".join(t.get("name", "?") for t in traders_sorted[:5])
        nav  = sum(t.get("portfolio_value", 0) for t in state.get("traders", []))
        donnees = {
            "perf_semaine":    "N/A",
            "nav":             f"{nav:.0f}€" if nav else "N/A",
            "top5":            top5,
            "patrimoine":      18082,
            "taux_annualise":  10.0,
        }
        get_gerant_delegue().generer_rapport_lundi(donnees)
        logger.info("[SCHEDULER] ✓ Rapport AGD-01 envoyé Telegram")
    except Exception as exc:
        logger.error("[SCHEDULER] ✗ AGD-01 rapport ÉCHEC: %s", exc)


_scheduler.add_job(
    _job_rapport_agd,
    CronTrigger(day_of_week="mon", hour=8, minute=0),
    id="rapport_agd_lundi",
    replace_existing=True,
)


def _job_comite_selection():
    """Comité Sélection — chaque jour 23:00 Paris pour les BUY candidats actifs."""
    logger.info("[SCHEDULER] Comité Sélection 23:00")
    try:
        from divisions.gerant_delegue import get_comite_selection
        from divisions.investissement.watchlist import get_watchlist_manager
        mgr        = get_watchlist_manager()
        watchlist  = mgr.analyser_watchlist(force=False)
        candidats  = [a for a in watchlist if a.get("signal") == "BUY"][:3]
        comite     = get_comite_selection()
        for candidat in candidats:
            comite.voter(candidat.get("ticker", "?"), candidat)
        logger.info("[SCHEDULER] ✓ Comité Sélection — %d candidats traités", len(candidats))
    except Exception as exc:
        logger.error("[SCHEDULER] ✗ Comité Sélection ÉCHEC: %s", exc)


_scheduler.add_job(
    _job_comite_selection,
    CronTrigger(hour=23, minute=0),
    id="comite_selection_nightly",
    replace_existing=True,
)


def _job_actualites():
    """Surveillance actualités — toutes les 30 min pendant les heures de trading."""
    try:
        from divisions.gerant_delegue import get_agent_actualites
        get_agent_actualites().analyser(forcer=True)
    except Exception as exc:
        logger.debug("[SCHEDULER] Actualités: %s", exc)


_scheduler.add_job(
    _job_actualites,
    CronTrigger(minute="*/30"),
    id="actualites_surveillance",
    replace_existing=True,
)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    _scheduler.start()
    logger.info("[SCHEDULER] APScheduler démarré — job rapport_investisseur lundi 09:00")

    engine.set_tick_callback(_broadcast)
    engine_thread = threading.Thread(target=engine.run, daemon=True)
    engine_thread.start()

    _send_telegram(
        f"🟢 <b>King Fund opérationnel</b>\n"
        f"Serveur démarré le {datetime.now().strftime('%d/%m/%Y à %H:%M:%S')}\n"
        f"30 traders actifs — Tick {TICK_INTERVAL}s\n"
        f"• Gérant Délégué AGD-01 actif\n"
        f"• Rapport lundi 08:00 (AGD-01) + 09:00 (PDF)\n"
        f"• Comité Sélection : chaque soir 23:00\n"
        f"• Actualités : surveillance toutes les 30 min\n"
        f"Objectif retraite Zoubida 2041 — 500 000€"
    )
    logger.info("Server starting on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)

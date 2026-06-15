import atexit
import json
import os
import queue
import signal
import threading
import logging
import sys
import time as _time
from datetime import datetime
from functools import wraps
from pathlib import Path

import requests as _requests
from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for
from flask_sock import Sock
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

sys.path.insert(0, str(Path(__file__).parent))

from engine import TradingEngine
from data.morning_brief import get_morning_brief
from config import TICK_INTERVAL, WEB_PASSWORD, SECRET_KEY

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

_FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
app = Flask(__name__, static_folder=_FRONTEND_DIR, static_url_path="")
app.secret_key = SECRET_KEY
sock = Sock(app)

# ---------------------------------------------------------------------------
# Authentification web par session Flask
# ---------------------------------------------------------------------------

_LOGIN_HTML = """
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>King Fund — Connexion</title>
<style>
  body{font-family:sans-serif;background:#0a0a0f;color:#e8e8f0;display:flex;
       align-items:center;justify-content:center;min-height:100vh;margin:0}
  .box{background:#12121a;border:1px solid #2a2a3a;border-radius:12px;
       padding:40px;width:320px;text-align:center}
  h2{margin:0 0 24px;font-size:1.4rem;color:#ffd700}
  input{width:100%;box-sizing:border-box;padding:12px;margin:8px 0 20px;
        background:#1a1a26;border:1px solid #2a2a3a;border-radius:8px;
        color:#e8e8f0;font-size:1rem}
  button{width:100%;padding:12px;background:#ffd700;color:#0a0a0f;
         border:none;border-radius:8px;font-size:1rem;font-weight:700;cursor:pointer}
  .err{color:#ff4455;margin-bottom:16px;font-size:.9rem}
</style></head><body>
<div class="box">
  <h2>👑 King Fund</h2>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <form method="post">
    <input type="password" name="password" placeholder="Mot de passe" autofocus>
    <button type="submit">Connexion</button>
  </form>
</div></body></html>
"""


def _requires_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.before_request
def _guard_web():
    """Protège l'interface web (non-API) par session Flask."""
    if request.path.startswith("/api/") or request.path.startswith("/ws"):
        return None
    if request.path in ("/login", "/logout"):
        return None
    # Fichiers statiques (CSS, JS, images) — autorisés pour que l'app charge
    if request.path.startswith("/assets/") or request.path.endswith(
        (".js", ".css", ".ico", ".png", ".svg", ".webmanifest", ".json")
    ):
        return None
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == WEB_PASSWORD:
            session["logged_in"] = True
            return redirect("/")
        error = "Mot de passe incorrect."
    return render_template_string(_LOGIN_HTML, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

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


@app.route("/api/investissement/screener")
def get_investissement_screener():
    try:
        from divisions.research.agent_screener_mondial import get_screener_mondial
        screener = get_screener_mondial()
        ts = screener.get_ts_run()
        return jsonify({
            "candidats": screener.get_candidats(),
            "ts_run":    ts.isoformat() if ts else None,
            "nb_univers": len(__import__("divisions.research.agent_screener_mondial",
                                         fromlist=["UNIVERSE"]).UNIVERSE),
        })
    except Exception as e:
        logger.error("screener get: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/investissement/screener/run", methods=["POST"])
def run_investissement_screener():
    try:
        from divisions.research.agent_screener_mondial import get_screener_mondial
        threading.Thread(
            target=get_screener_mondial().scanner,
            daemon=True,
            name="screener-run",
        ).start()
        return jsonify({"status": "started", "message": "Scan lancé (~2 min pour ~150 titres)"})
    except Exception as e:
        logger.error("screener run: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/investissement/analyze")
def api_investissement_analyze():
    """
    Analyse 17 étapes via pipeline réel obligatoire.
    RÈGLE : toute donnée (prix, P/E, market cap…) vient de yfinance — jamais de mémoire Claude.
    Retourne un disclaimer horodaté + statut fraîcheur dans _garde_fou.
    """
    import traceback as _tb
    ticker = request.args.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"erreur": "Paramètre 'ticker' requis (ex: ?ticker=AAPL)"}), 400

    try:
        from divisions.investissement.pipeline import InvestmentPipeline, get_pipeline
        from divisions.investissement.data_guard import verifier_fraicheur_prix, ajouter_disclaimer

        fraicheur = verifier_fraicheur_prix(ticker)
        rapport = get_pipeline().analyze(ticker)
        # Normalise le champ pour ajouter_disclaimer
        signal = rapport.get("signal", "hold")
        rapport["recommandation_finale"] = {"buy": "ACHAT", "sell": "ÉVITER", "hold": "SURVEILLER"}.get(signal, signal.upper())
        rapport = ajouter_disclaimer(rapport, fraicheur)
        return jsonify(rapport)
    except Exception as e:
        tb = _tb.format_exc()
        logger.error("investissement analyze [%s]: %s\n%s", ticker, e, tb)
        return jsonify({
            "erreur": str(e),
            "traceback": tb,
            "ticker": ticker,
            "timestamp": datetime.utcnow().isoformat(),
            "_garde_fou": {
                "disclaimer": f"ANALYSE ÉCHOUÉE le {datetime.utcnow().isoformat()} — données non disponibles via yfinance",
                "statut_donnees": "INDISPONIBLE",
                "fraicheur_ok": False,
                "generee_par": "pipeline_reel",
            },
        }), 500


@app.route("/api/investissement/watchlist/add", methods=["POST"])
def add_investissement_watchlist_ticker():
    ticker = request.args.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"erreur": "Paramètre 'ticker' requis (ex: ?ticker=AAPL)"}), 400
    try:
        from divisions.investissement.watchlist import get_watchlist_manager, WATCHLIST
        if any(w["ticker"] == ticker for w in WATCHLIST):
            return jsonify({"message": f"{ticker} déjà dans la watchlist", "ticker": ticker})
        get_watchlist_manager().add_ticker(ticker)
        return jsonify({"message": f"{ticker} ajouté à la watchlist", "ticker": ticker})
    except Exception as e:
        logger.error("watchlist add [%s]: %s", ticker, e)
        return jsonify({"erreur": str(e)}), 500


# ── Alertes (agrégation bus + agents) ────────────────────────────────────────

@app.route("/api/alertes")
def get_alertes():
    """Agrège alertes critiques/warnings/infos depuis le bus et les agents."""
    critiques: list = []
    warnings:  list = []
    infos:     list = []
    ts = datetime.utcnow().isoformat()

    # Source 1 — bus : 50 derniers messages
    try:
        hub = getattr(engine, "_hub", None)
        if hub:
            for msg in hub._bus.messages_recents(n=50):
                item = {
                    "titre":     msg.titre,
                    "detail":    msg.entite or "",
                    "expert":    msg.source,
                    "timestamp": msg.timestamp,
                }
                if msg.niveau == "critique":
                    critiques.append(item)
                elif msg.niveau == "warning":
                    warnings.append(item)
                else:
                    infos.append(item)
    except Exception as e:
        logger.debug("alertes bus: %s", e)

    # Source 2 — seuils prix d'entrée
    try:
        from divisions.gerant_delegue.agent_alertes_prix import get_agent_alertes_prix
        for s in (get_agent_alertes_prix().verifier_seuils() or []):
            if s.get("alerte"):
                warnings.append({
                    "titre":     f"Seuil atteint — {s.get('ticker', '')}",
                    "detail":    s.get("message", ""),
                    "expert":    "📊 Alertes Prix",
                    "timestamp": ts,
                })
    except Exception as e:
        logger.debug("alertes seuils: %s", e)

    # Source 3 — calendrier corporate (J≤2 → warning, sinon info)
    try:
        from divisions.gerant_delegue.agent_calendrier import get_agent_calendrier
        for evt in (get_agent_calendrier().prochains_evenements() or []):
            item = {
                "titre":     evt.get("titre", ""),
                "detail":    evt.get("detail", ""),
                "expert":    "📅 Calendrier",
                "timestamp": ts,
            }
            (warnings if evt.get("jours_restants", 99) <= 2 else infos).append(item)
    except Exception as ex:
        logger.debug("alertes calendrier: %s", ex)

    return jsonify({
        "critiques": critiques[:20],
        "warnings":  warnings[:20],
        "infos":     infos[:30],
        "timestamp": ts,
    })


# ── Alertes prix & Calendrier ────────────────────────────────────────────────

@app.route("/api/alertes/seuils")
def get_alertes_seuils():
    try:
        from divisions.gerant_delegue.agent_alertes_prix import get_agent_alertes_prix
        agent = get_agent_alertes_prix()
        resultats = agent.verifier_seuils()
        return jsonify({"timestamp": datetime.utcnow().isoformat(), "seuils": resultats})
    except Exception as e:
        logger.error("alertes seuils: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/alertes/calendrier")
def get_alertes_calendrier():
    try:
        from divisions.gerant_delegue.agent_calendrier import get_agent_calendrier
        agent = get_agent_calendrier()
        evenements = agent.prochains_evenements()
        return jsonify({"timestamp": datetime.utcnow().isoformat(), "evenements": evenements})
    except Exception as e:
        logger.error("alertes calendrier: %s", e)
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


@app.route("/api/patrimoine/actifs/<actif_id>", methods=["PUT"])
def update_patrimoine_actif(actif_id):
    from data.patrimoine import update_actif
    body = request.get_json(silent=True) or {}
    try:
        valeur = float(body.get("valeur_eur", 0))
        actif = update_actif(actif_id, valeur)
        if actif is None:
            return jsonify({"erreur": "actif non trouvé"}), 404
        return jsonify({"status": "ok", "actif": actif})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/patrimoine/actifs/<actif_id>", methods=["DELETE"])
def delete_patrimoine_actif(actif_id):
    from data.patrimoine import delete_actif
    ok = delete_actif(actif_id)
    return jsonify({"status": "ok" if ok else "not_found"})


@app.route("/api/patrimoine/retraite")
def get_patrimoine_retraite():
    from data.patrimoine import get_patrimoine as _get
    from datetime import date as _date
    try:
        d = _get()
        cfg = d.get("config", {})
        annee_retraite = cfg.get("annee_base", 2026) + (cfg.get("age_retraite", 56) - cfg.get("age_actuel", 35))
        jours_restants = max(0, (_date(annee_retraite, 1, 1) - _date.today()).days)
        return jsonify({
            "base_investissable": d.get("total_investissable", 0),
            "objectif":           d.get("valeur_retraite", 0),
            "apport_mensuel":     d.get("apport_mensuel_effectif", 500),
            "taux_annuel":        cfg.get("taux_annuel", 0.10),
            "annee_retraite":     annee_retraite,
            "jours_restants":     jours_restants,
        })
    except Exception as e:
        logger.error("patrimoine/retraite: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/patrimoine/positions-pru")
def get_positions_pru():
    from data.suivi_pru import get_suivi_pru
    try:
        return jsonify(get_suivi_pru())
    except Exception as e:
        logger.error("positions-pru: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/patrimoine/positions-pru/transaction", methods=["POST"])
def add_pru_transaction():
    from data.suivi_pru import ajouter_transaction
    body = request.get_json(silent=True) or {}
    try:
        tx = ajouter_transaction(
            ticker        = body["ticker"],
            type_tx       = body["type"],
            quantite      = float(body["quantite"]),
            prix_unitaire = float(body["prix_unitaire"]),
            compte        = body.get("compte", "cto"),
            note          = body.get("note", ""),
            date_tx       = body.get("date"),
        )
        return jsonify({"status": "ok", "transaction": tx})
    except (KeyError, ValueError) as e:
        return jsonify({"erreur": str(e)}), 400
    except Exception as e:
        logger.error("pru/transaction: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/patrimoine/positions-pru/config", methods=["POST"])
def config_pru_position():
    from data.suivi_pru import configurer_position
    body = request.get_json(silent=True) or {}
    try:
        pos = configurer_position(
            ticker     = body["ticker"],
            nom        = body.get("nom"),
            objectif   = body.get("objectif"),
            stop_loss  = body.get("stop_loss"),
            note       = body.get("note"),
        )
        return jsonify({"status": "ok", "position": pos})
    except KeyError as e:
        return jsonify({"erreur": str(e)}), 400
    except Exception as e:
        logger.error("pru/config: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/patrimoine/positions-pru/nouvelle", methods=["POST"])
def nouvelle_pru_position():
    from data.suivi_pru import ajouter_transaction, configurer_position
    body = request.get_json(silent=True) or {}
    try:
        ticker    = body["ticker"].strip().upper()
        quantite  = float(body["quantite"])
        pru       = float(body["pru"])
        date_achat = body.get("date") or None
        frais     = float(body.get("frais") or 0)
        objectif  = body.get("objectif")
        stop_loss = body.get("stop_loss")
        if quantite <= 0 or pru <= 0:
            return jsonify({"erreur": "quantite et pru doivent être positifs"}), 400
        note = f"frais: {frais:.2f}" if frais > 0 else ""
        tx  = ajouter_transaction(ticker, "achat", quantite, pru,
                                  compte="cto", note=note, date_tx=date_achat)
        pos = configurer_position(
            ticker,
            objectif  = float(objectif)  if objectif  else None,
            stop_loss = float(stop_loss) if stop_loss else None,
        )
        return jsonify({"status": "ok", "transaction": tx, "position": pos})
    except (KeyError, ValueError) as e:
        return jsonify({"erreur": str(e)}), 400
    except Exception as e:
        logger.error("positions-pru/nouvelle: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/patrimoine/positions-pru/<ticker>", methods=["DELETE"])
def delete_pru_position(ticker):
    from data.suivi_pru import supprimer_position
    ok = supprimer_position(ticker)
    return jsonify({"status": "ok" if ok else "not_found"})


@app.route("/api/rapports/investisseur/dernier")
def get_rapport_investisseur_dernier():
    from pathlib import Path
    rep_dir = Path.home() / "rapports" / "investisseur"
    try:
        fichiers = sorted(rep_dir.glob("rapport_*.pdf"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not fichiers:
            fichiers = sorted(rep_dir.glob("rapport_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not fichiers:
            return jsonify({"erreur": "Aucun rapport investisseur généré"}), 404
        f = fichiers[0]
        return jsonify({"chemin_pdf": str(f), "nom": f.name, "taille_ko": round(f.stat().st_size / 1024, 1), "ts": datetime.fromtimestamp(f.stat().st_mtime).isoformat()})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/rapports/mensuel/dernier")
def get_rapport_mensuel_dernier():
    from pathlib import Path
    rep_dir = Path.home() / "rapports" / "mensuel"
    try:
        fichiers = sorted(rep_dir.glob("rapport_mensuel_*.pdf"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not fichiers:
            fichiers = sorted(rep_dir.glob("rapport_mensuel_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not fichiers:
            return jsonify({"erreur": "Aucun rapport mensuel généré"}), 404
        f = fichiers[0]
        return jsonify({"chemin_pdf": str(f), "nom": f.name, "taille_ko": round(f.stat().st_size / 1024, 1), "ts": datetime.fromtimestamp(f.stat().st_mtime).isoformat()})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/rapports/investisseur/generer", methods=["POST"])
def post_rapport_investisseur_generer():
    try:
        from divisions.rapports.rapport_investisseur import generer_rapport as _gen_inv
        chemin = _gen_inv(engine)
        return jsonify({"status": "ok", "chemin_pdf": chemin})
    except Exception as e:
        logger.error("rapport investisseur: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/rapports/mensuel/generer", methods=["POST"])
def post_rapport_mensuel_generer():
    try:
        from divisions.rapports.rapport_mensuel import generer_rapport as _gen_mensuel
        chemin = _gen_mensuel(engine)
        return jsonify({"status": "ok", "chemin_pdf": chemin})
    except Exception as e:
        logger.error("rapport mensuel: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/rapports/annuel/dernier")
def get_rapport_annuel_dernier():
    from pathlib import Path
    rep_dir = Path.home() / "rapports" / "annuel"
    try:
        fichiers = sorted(rep_dir.glob("rapport_annuel_*.pdf"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not fichiers:
            fichiers = sorted(rep_dir.glob("rapport_annuel_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not fichiers:
            return jsonify({"erreur": "Aucun rapport annuel généré"}), 404
        f = fichiers[0]
        return jsonify({"chemin_pdf": str(f), "nom": f.name, "taille_ko": round(f.stat().st_size / 1024, 1), "ts": datetime.fromtimestamp(f.stat().st_mtime).isoformat()})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/rapports/annuel/generer", methods=["POST"])
def post_rapport_annuel_generer():
    try:
        from divisions.rapports.rapport_annuel import generer_rapport as _gen_annuel
        chemin = _gen_annuel(engine)
        return jsonify({"status": "ok", "chemin_pdf": chemin})
    except Exception as e:
        logger.error("rapport annuel: %s", e)
        return jsonify({"erreur": str(e)}), 500


# ---------------------------------------------------------------------------
# Gouvernance — hiérarchie, autonomie, mode trading, config user
# ---------------------------------------------------------------------------

@app.route("/api/gouvernance/etat")
def get_gouvernance_etat():
    try:
        from divisions.gouvernance.gouvernance import get_gouvernance_engine
        from divisions.gouvernance.autonomie   import get_autonomie_manager
        from divisions.gouvernance.mode_trading import get_mode_trading
        return jsonify({
            "gouvernance": get_gouvernance_engine().get_etat(),
            "autonomie":   get_autonomie_manager().get_etat(),
            "mode":        get_mode_trading().get_etat(),
        })
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/gouvernance/log")
def get_gouvernance_log():
    limit = int(request.args.get("limit", 50))
    try:
        from divisions.gouvernance.gouvernance import get_gouvernance_engine
        return jsonify(get_gouvernance_engine().get_log(limit))
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/gouvernance/validation/<vid>/valider", methods=["POST"])
def valider_action(vid):
    try:
        from divisions.gouvernance.autonomie import get_autonomie_manager
        ok = get_autonomie_manager().confirmer(vid)
        return jsonify({"status": "ok" if ok else "not_found"})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/gouvernance/validation/<vid>/rejeter", methods=["POST"])
def rejeter_action(vid):
    body = request.get_json(silent=True) or {}
    try:
        from divisions.gouvernance.autonomie import get_autonomie_manager
        ok = get_autonomie_manager().rejeter(vid, body.get("raison", ""))
        return jsonify({"status": "ok" if ok else "not_found"})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/gouvernance/autonomie/etat")
def get_autonomie_etat():
    try:
        from divisions.gouvernance.autonomie import get_autonomie_manager
        return jsonify(get_autonomie_manager().get_etat())
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/gouvernance/autonomie/log")
def get_autonomie_log():
    limit = int(request.args.get("limit", 50))
    try:
        from divisions.gouvernance.autonomie import get_autonomie_manager
        return jsonify(get_autonomie_manager().get_log_autonomie(limit))
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/gouvernance/mode")
def get_mode_trading_etat():
    try:
        from divisions.gouvernance.mode_trading import get_mode_trading
        return jsonify(get_mode_trading().get_etat())
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/gouvernance/mode/basculer-reel", methods=["POST"])
def demander_mode_reel():
    body = request.get_json(silent=True) or {}
    try:
        capital = float(body.get("capital", 0))
        if capital <= 0:
            return jsonify({"erreur": "capital doit être > 0"}), 400
        from divisions.gouvernance.mode_trading import get_mode_trading
        vid = get_mode_trading().demander_bascule_reel(capital)
        return jsonify({"status": "ok", "validation_id": vid, "message": "Alerte Telegram envoyée — confirmez dans les 24h"})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/gouvernance/mode/confirmer/<vid>", methods=["POST"])
def confirmer_mode_reel(vid):
    try:
        from divisions.gouvernance.mode_trading import get_mode_trading
        etat = get_mode_trading().confirmer_bascule(vid)
        return jsonify({"status": "ok", "mode": etat})
    except ValueError as e:
        return jsonify({"erreur": str(e)}), 400
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/gouvernance/mode/annuler/<vid>", methods=["POST"])
def annuler_mode_reel(vid):
    try:
        from divisions.gouvernance.mode_trading import get_mode_trading
        ok = get_mode_trading().annuler_bascule(vid)
        return jsonify({"status": "ok" if ok else "not_found"})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/gouvernance/mode/retour-simulation", methods=["POST"])
def retour_simulation():
    try:
        from divisions.gouvernance.mode_trading import get_mode_trading
        etat = get_mode_trading().revenir_simulation()
        return jsonify({"status": "ok", "mode": etat})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/config-user")
def get_config_user():
    try:
        from data.config_user import get_config, get_config_file_path
        return jsonify({"config": get_config(), "fichier": get_config_file_path()})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/config-user", methods=["POST"])
def post_config_user():
    body = request.get_json(silent=True) or {}
    try:
        from data.config_user import update_config, update_config_bulk
        # Mode bulk : {"updates": {"cle.sous_cle": valeur, ...}}
        if "updates" in body:
            cfg = update_config_bulk(body["updates"])
        elif "key" in body and "value" in body:
            cfg = update_config(body["key"], body["value"])
        else:
            return jsonify({"erreur": "Fournir 'key'+'value' ou 'updates'"}), 400
        return jsonify({"status": "ok", "config": cfg})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/config-user/reload", methods=["POST"])
def reload_config_user():
    try:
        from data.config_user import reload_config
        cfg = reload_config()
        return jsonify({"status": "ok", "config": cfg})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/bus/state")
def get_bus_state():
    hub = getattr(engine, "_hub", None)
    if hub is None:
        return jsonify({"erreur": "InterAgentHub non initialisé"}), 503
    raw = hub.get_etat()

    bs  = raw.get("black_swan", {})
    dl  = raw.get("desk_liquidite", {})
    vix_val = bs.get("vix")

    # Flatten CB signals: {code: {sentiment, name, rate}}
    cb_full: dict = {}
    try:
        with hub._lock:
            cb_full = {
                code: {
                    "sentiment": float(d.get("sentiment", 0)),
                    "name":      code,
                    "rate":      d.get("taux"),
                    "headline":  d.get("headline", ""),
                }
                for code, d in hub._cb_last_signals.items()
            }
    except Exception:
        cb_full = {
            code: {"sentiment": float(v), "name": code, "rate": None}
            for code, v in raw.get("banques_centrales", {}).get("signaux", {}).items()
        }

    # Derive Howell regime from VIX + liq_budget_factor
    liq_f = dl.get("budget_factor", 1.0)
    vix_f = float(vix_val) if vix_val is not None else None
    if (vix_f is not None and vix_f >= 30) or liq_f <= 0.65:
        howell = "HOWELL_DANGER"
    elif (vix_f is not None and vix_f >= 25) or liq_f <= 0.80:
        howell = "HOWELL_VIGILANCE"
    elif (vix_f is not None and vix_f >= 20) or liq_f <= 0.95:
        howell = "HOWELL_ATTENTION"
    else:
        howell = "HOWELL_SEREIN"

    return jsonify({
        **raw,
        # Flat keys expected by frontend
        "black_swan_halt":   bs.get("halt", False),
        "vix":               vix_val,
        "liq_budget_factor": liq_f,
        "central_banks":     cb_full,
        "expert_signals":    raw.get("experts_sectoriels", {}).get("signaux", {}),
        "howell_regime":     howell,
        "howell_resume":     f"VIX={vix_val:.1f} | Budget×{liq_f:.2f}" if vix_val else f"Budget×{liq_f:.2f}",
        "bus_stats":         raw.get("bus", {}),
    })


# ── Black Swan — surveillance VIX + indicateurs de risque systémique ─────────

_bs_cache:    dict  = {}
_bs_cache_ts: float = 0.0
_BS_TTL = 60   # 1 min


def _build_blackswan_etat() -> dict:
    hub  = getattr(engine, "_hub", None)
    halt = hub.black_swan_halt if hub else False
    vix  = hub.last_vix if hub else None

    # VIX variation 24h
    vix_var = None
    try:
        import yfinance as yf
        hist = yf.Ticker("^VIX").history(period="5d", interval="1d", auto_adjust=True)
        if len(hist) >= 2:
            v0 = float(hist["Close"].iloc[-2])
            v1 = float(hist["Close"].iloc[-1])
            vix_var = round((v1 / v0 - 1) * 100, 2) if v0 else None
            if vix is None:
                vix = round(v1, 2)
    except Exception:
        pass

    # DSPX — réutilise le cache du endpoint /api/dspx/etat
    dspx_val = _dspx_cache.get("dspx") if _dspx_cache else None

    # Corrélation SPY/TLT — réutilise le cache du endpoint /api/correlations/actoblig
    corr = _corr_cache.get("correlation_20j") if _corr_cache else None

    # Spread HY — parse résumé FRED Credit du desk liquidité
    hy_spread = None
    try:
        import re
        from divisions.middle_office import get_liquidity_desk
        summary = get_liquidity_desk().get_data().get("agent_summaries", {}).get("FRED_Credit", "")
        m = re.search(r"HY=([\d.]+)bp", summary or "")
        if m:
            hy_spread = float(m.group(1))
    except Exception:
        pass

    # Niveau
    if halt or (vix is not None and vix >= 35):
        niveau = "CRITIQUE"
    elif vix is not None and vix >= 25:
        niveau = "WARNING"
    elif vix is not None:
        niveau = "NORMAL"
    else:
        niveau = "INCONNU"

    mode    = "BARBELL" if (halt or (vix is not None and vix >= 34)) else "NORMAL"
    stoppes = [f"TRD{i:02d}" for i in range(1, 31)] if halt else []
    actifs  = (
        {"refuges": ["GC=F", "IAU", "GTT.PA", "VPK.AS"], "defensifs": ["TLT", "cash"]}
        if mode == "BARBELL" else {}
    )

    msgs = []
    if vix is not None:
        if halt:
            msgs.append(f"🚨 HALT — VIX={vix:.1f} ≥ 35 — Trading suspendu")
        elif vix >= 34:
            msgs.append(f"⚠️ VIX critique : {vix:.1f} — Mode BARBELL recommandé")
        elif vix >= 25:
            msgs.append(f"⚡ VIX élevé : {vix:.1f} — Vigilance")
        else:
            msgs.append(f"✅ VIX normal : {vix:.1f} — Allocation standard")
    else:
        msgs.append("Données VIX non disponibles")
    if hy_spread is not None:
        tag = "🚨" if hy_spread > 700 else "⚠️" if hy_spread > 500 else "✅"
        msgs.append(f"{tag} Spread HY : {hy_spread:.0f}bps")
    if corr is not None and corr > 0:
        msgs.append(f"⚠️ Corr SPY/TLT positive ({corr:+.2f}) — perte antifragilité")

    return {
        "niveau":                   niveau,
        "indicateurs": {
            "vix":                  vix,
            "vix_variation_24h":    vix_var,
            "credit_spread_hy":     hy_spread,
            "dspx":                 dspx_val,
            "correlation_spy_tlt":  corr,
        },
        "mode_portefeuille":        mode,
        "traders_momentum_stoppes": stoppes,
        "actifs_recommandes":       actifs,
        "messages_analyse":         msgs,
        "halt_actif":               halt,
        "timestamp":                datetime.utcnow().isoformat(),
    }


@app.route("/api/blackswan/etat")
def get_blackswan_etat():
    global _bs_cache, _bs_cache_ts
    now = _time.monotonic()
    if _bs_cache and (now - _bs_cache_ts) < _BS_TTL:
        return jsonify(_bs_cache)
    try:
        result       = _build_blackswan_etat()
        _bs_cache    = result
        _bs_cache_ts = now
        return jsonify(result)
    except Exception as e:
        logger.error("blackswan etat: %s", e)
        if _bs_cache:
            return jsonify(_bs_cache)
        return jsonify({
            "niveau": "INCONNU",
            "message": "Pas encore de scan effectué",
            "indicateurs": {
                "vix": None, "vix_variation_24h": None,
                "credit_spread_hy": None, "dspx": None, "correlation_spy_tlt": None,
            },
            "mode_portefeuille": "NORMAL",
            "traders_momentum_stoppes": [],
            "actifs_recommandes": {},
            "messages_analyse": [],
            "timestamp": datetime.utcnow().isoformat(),
        })


@app.route("/api/blackswan/scan", methods=["POST"])
def post_blackswan_scan():
    global _bs_cache, _bs_cache_ts
    try:
        hub = getattr(engine, "_hub", None)
        if hub is not None:
            hub.run_cycle_vix()
            _time.sleep(2)
        result       = _build_blackswan_etat()
        _bs_cache    = result
        _bs_cache_ts = _time.monotonic()
        return jsonify(result)
    except Exception as e:
        logger.error("blackswan scan: %s", e)
        return jsonify({"erreur": str(e)}), 500


# ── Macro — indices mondiaux (Asie / Europe / US / Forex / Crypto) ────────────

_macro_cache:    dict  = {}
_macro_cache_ts: float = 0.0
_MACRO_TTL = 900   # 15 min

_MACRO_TICKERS: dict = {
    "indices_asie":   ["^N225", "^HSI", "000300.SS"],
    "indices_europe": ["^FCHI", "^GDAXI", "^FTSE", "^STOXX50E"],
    "indices_us":     ["^GSPC", "^IXIC", "^DJI", "^VIX"],
    "forex":          ["EURUSD=X", "GC=F", "CL=F"],
    "crypto":         ["BTC-USD", "ETH-USD"],
}


@app.route("/api/macro")
def get_macro():
    global _macro_cache, _macro_cache_ts
    now = _time.monotonic()
    if _macro_cache and (now - _macro_cache_ts) < _MACRO_TTL:
        return jsonify(_macro_cache)
    try:
        import yfinance as yf
        all_tickers = [t for grp in _MACRO_TICKERS.values() for t in grp]
        raw: dict = {}
        for ticker in all_tickers:
            try:
                hist = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=True)
                if not hist.empty and len(hist) >= 2:
                    p1 = float(hist["Close"].iloc[-1])
                    p0 = float(hist["Close"].iloc[-2])
                    raw[ticker] = {"prix": round(p1, 2), "variation_pct": round((p1 / p0 - 1) * 100, 2) if p0 else 0}
                elif not hist.empty:
                    raw[ticker] = {"prix": round(float(hist["Close"].iloc[-1]), 2), "variation_pct": 0}
            except Exception:
                raw[ticker] = None

        result = {grp: {t: raw.get(t) for t in tickers} for grp, tickers in _MACRO_TICKERS.items()}
        result["timestamp"] = datetime.utcnow().isoformat()
        _macro_cache    = result
        _macro_cache_ts = now
        return jsonify(result)
    except Exception as e:
        logger.error("macro: %s", e)
        if _macro_cache:
            return jsonify(_macro_cache)
        return jsonify({
            **{grp: {t: None for t in tickers} for grp, tickers in _MACRO_TICKERS.items()},
            "erreur": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        })


# ── CIO Allocation macro ──────────────────────────────────────────────────────

@app.route("/api/cio/allocation")
def get_cio_allocation():
    """
    Allocation macro dynamique CIO.
    Régime dérivé du VIX (bus) + mode Bertez (desk liquidité).
    Régimes : RISK_ON / NEUTRAL / RISK_OFF
    """
    try:
        hub      = getattr(engine, "_hub", None)
        vix      = hub.last_vix if hub else None
        halt     = hub.black_swan_halt if hub else False

        bertez_mode = "NEUTRE"
        try:
            from divisions.middle_office import get_liquidity_desk
            data = get_liquidity_desk().get_data()
            bertez_mode = data.get("bertez_mode") or "NEUTRE"
        except Exception:
            pass

        vix_val = float(vix) if vix is not None else 20.0

        # Signal inflation depuis corrélations actions/obligations
        inflation_regime = False
        try:
            from divisions.middle_office.agent_correlations_actoblig import get_agent_correlations
            corr_data = get_agent_correlations().get_data()
            inflation_regime = corr_data.get("regime") == "REGIME_INFLATION"
        except Exception:
            pass

        # Régimes : RISK_OFF > MMT_INFLATION (Bertez DEFENSIF ou inflation) > RISK_ON > NEUTRAL
        if halt or vix_val >= 35:
            regime = "RISK_OFF"
        elif bertez_mode == "DEFENSIF" and vix_val >= 30:
            regime = "RISK_OFF"
        elif bertez_mode == "DEFENSIF" or inflation_regime:
            regime = "MMT_INFLATION"
        elif vix_val < 20:
            regime = "RISK_ON"
        else:
            regime = "NEUTRAL"

        # Allocations par régime — thèse Bertez MMT inflationniste :
        # obligations ↓25→12 | or ↑15→22 | commodités ↑2→8
        # MMT_INFLATION : bucket dédié actions_eu_energie_infra (TTE.PA ENGIE.PA VIE.PA SU.PA VPK.AS)
        _alloc = {
            "RISK_ON": {
                "actions_us": 40, "actions_eu": 20, "obligations": 15,
                "or": 10, "cash": 5, "crypto": 5, "commodites": 5,
            },
            "MMT_INFLATION": {
                "actions_us": 30, "actions_eu": 7,
                "actions_eu_energie_infra": 8,
                "obligations": 12,
                "or": 22,
                "cash": 10, "crypto": 3, "commodites": 8,
            },
            "NEUTRAL": {
                "actions_us": 30, "actions_eu": 15, "obligations": 12,
                "or": 22, "cash": 10, "crypto": 3, "commodites": 8,
            },
            "RISK_OFF": {
                "actions_us": 10, "actions_eu": 5, "obligations": 35,
                "or": 25, "cash": 20, "crypto": 0, "commodites": 5,
            },
        }

        _tickers = {
            "MMT_INFLATION": {
                "actions_eu_energie_infra": ["TTE.PA", "ENGIE.PA", "VIE.PA", "SU.PA", "VPK.AS", "GTT.PA"],
                "or": ["GLD", "GC=F"],
                "commodites": ["XLE", "CL=F"],
            },
            "RISK_OFF": {"or": ["GLD"], "obligations": ["TLT", "IEF"]},
        }

        short_signals = []
        if regime == "RISK_ON" and vix_val < 18:
            short_signals = ["NVDA", "SMCI", "QQQ"]
        elif bertez_mode == "DEFENSIF":
            short_signals = ["QQQ", "SPY"]

        return jsonify({
            "regime":             regime,
            "allocation":         _alloc[regime],
            "tickers_recommandes": _tickers.get(regime, {}),
            "short_signals":      short_signals,
            "vix":                round(vix_val, 1) if vix is not None else None,
            "bertez_mode":        bertez_mode,
            "inflation_regime":   inflation_regime,
            "updated_at":         datetime.utcnow().isoformat(),
        })
    except Exception as e:
        logger.error("cio allocation: %s", e)
        return jsonify({"erreur": str(e)}), 500


# ── Audit AGD-01 ──────────────────────────────────────────────────────────────

@app.route("/api/agd/audit")
def get_agd_audit():
    """Journal immuable AGD-01 — dernières N décisions avec prev_hash chain."""
    limit = min(int(request.args.get("limit", 30)), 200)
    try:
        from divisions.gerant_delegue.audit_agd import get_recent
        entries = get_recent(limit)
        return jsonify({"entries": entries, "count": len(entries)})
    except Exception as e:
        logger.error("agd audit: %s", e)
        return jsonify({"erreur": str(e)}), 500


# ── Prédictivité des signaux ──────────────────────────────────────────────────

@app.route("/api/signaux/predictivite")
def get_signaux_predictivite():
    """Taux de réussite Bertez + Morning Brief + historique récent."""
    try:
        from data.signal_history import get_stats, get_history
        stats   = get_stats()
        history = get_history(limit=20)
        return jsonify({"stats": stats, "history": history})
    except Exception as e:
        logger.error("signaux predictivite: %s", e)
        return jsonify({"erreur": str(e)}), 500


# ── Bertez Analyse ────────────────────────────────────────────────────────────

@app.route("/api/bertez/analyse")
def get_bertez_analyse():
    """
    Signal Bertez (WTI + macro) depuis le desk liquidité.
    Fournit mode, signal [-1,+1], prix WTI et thèse directionnelle.
    """
    try:
        from divisions.middle_office import get_liquidity_desk
        data        = get_liquidity_desk().get_data()
        bertez_sig  = data.get("bertez_signal")
        bertez_mode = data.get("bertez_mode") or "NEUTRE"

        _theses = {
            "DEFENSIF": ("WTI+USD fort → STAGFLATION → rotation actifs réels "
                         "(XLE, GLD, TTE.PA, SU.PA, VPK.AS)"),
            "OFFENSIF": ("WTI bas+USD faible → REFLATION → actions cycliques "
                         "(Finance, Tech, AMZN, META)"),
            "NEUTRE":   "Régime neutre — pas de signal Bertez directionnel fort.",
        }

        wti = None
        try:
            from divisions.middle_office.desk_liquidite.agents.agent_bertez import (
                get_last_bertez_result,
            )
            last = get_last_bertez_result()
            if last:
                wti = (
                    last.get("data", {})
                    .get("fred", {})
                    .get("wti_crude", {})
                    .get("latest")
                )
        except Exception:
            pass

        return jsonify({
            "mode":      bertez_mode,
            "signal":    bertez_sig,
            "wti_price": wti,
            "these":     _theses.get(bertez_mode, _theses["NEUTRE"]),
            "timestamp": datetime.utcnow().isoformat(),
        })
    except Exception as e:
        logger.error("bertez analyse: %s", e)
        return jsonify({"erreur": str(e)}), 500


# ── DSPX Dispersion ──────────────────────────────────────────────────────────

_dspx_cache:  dict = {}
_dspx_cache_ts: float = 0.0
_DSPX_TTL = 300   # 5 min

@app.route("/api/dspx/etat")
def get_dspx_etat():
    """
    Agent DSPX — dispersion implicite + corrélations rolling 30j.
    Source : ^DSPX (fallback ^SKEW) via yfinance.
    Régimes : FORTE / NORMALE / FAIBLE.
    """
    global _dspx_cache, _dspx_cache_ts
    now = _time.monotonic()
    if _dspx_cache and (now - _dspx_cache_ts) < _DSPX_TTL:
        return jsonify(_dspx_cache)
    try:
        import yfinance as yf
        import numpy as np

        # Fetch DSPX (fallback SKEW)
        dspx_val = None
        for ticker in ("^DSPX", "^SKEW"):
            try:
                hist = yf.Ticker(ticker).history(period="60d", interval="1d", auto_adjust=True)
                if not hist.empty:
                    dspx_val = float(hist["Close"].iloc[-1])
                    dspx_series = hist["Close"].dropna().values
                    break
            except Exception:
                continue

        percentile_50j = None
        regime = "NORMALE"
        signal = "NEUTRE"
        if dspx_val is not None and len(dspx_series) >= 2:
            window = dspx_series[-50:] if len(dspx_series) >= 50 else dspx_series
            pct = float(np.sum(window <= dspx_val) / len(window) * 100)
            percentile_50j = round(pct, 1)
            if pct >= 75:
                regime = "FORTE"
                signal = "STOCK_PICKING"
            elif pct <= 25:
                regime = "FAIBLE"
                signal = "BETA_ONLY"
            else:
                regime = "NORMALE"
                signal = "NEUTRE"

        # Rolling 30-day correlations vs basket
        corr_tickers = ["SPY", "TLT", "GLD", "QQQ", "IWM", "GC=F", "CL=F"]
        correlations: dict = {}
        try:
            import pandas as pd
            data = yf.download(
                " ".join(corr_tickers),
                period="35d",
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            closes = data["Close"] if "Close" in data.columns else data
            spy_ret = closes["SPY"].pct_change().dropna() if "SPY" in closes.columns else None
            if spy_ret is not None and len(spy_ret) >= 10:
                for sym in corr_tickers:
                    if sym == "SPY" or sym not in closes.columns:
                        continue
                    try:
                        sym_ret = closes[sym].pct_change().dropna()
                        n = min(len(spy_ret), len(sym_ret), 30)
                        if n >= 5:
                            c = float(np.corrcoef(spy_ret.values[-n:], sym_ret.values[-n:])[0, 1])
                            if not np.isnan(c):
                                correlations[sym] = round(c, 2)
                    except Exception:
                        pass
        except Exception:
            pass

        result = {
            "dspx":          round(dspx_val, 2) if dspx_val is not None else None,
            "percentile_50j": percentile_50j,
            "regime":         regime,
            "signal":         signal,
            "correlations":   correlations,
            "timestamp":      datetime.utcnow().isoformat(),
        }
        _dspx_cache    = result
        _dspx_cache_ts = now
        return jsonify(result)
    except Exception as e:
        logger.error("dspx etat: %s", e)
        if _dspx_cache:
            return jsonify(_dspx_cache)
        return jsonify({
            "dspx": None, "percentile_50j": None,
            "regime": "INCONNU", "signal": "—", "correlations": {},
            "erreur": str(e), "timestamp": datetime.utcnow().isoformat(),
        })


# ── Corrélations Actions/Obligations ─────────────────────────────────────────

_corr_cache:    dict = {}
_corr_cache_ts: float = 0.0
_CORR_TTL = 3600   # 1 h (données FRED ne changent pas à la minute)

_ACTIFS_INFLATION = [
    "GC=F", "GLD", "VPK.AS", "GTT.PA", "O", "BIPC", "SU.PA", "TTE.PA",
]
_ACTIFS_DECORR = ["TLT", "IEF", "GLD", "VPK.AS"]

@app.route("/api/correlations/actoblig")
def get_correlations_actoblig():
    """
    Corrélations SPY/TLT rolling 20j + 60j + inflation US (FRED CPIAUCSL).
    Régimes : REGIME_INFLATION / DECORRELATION / NEUTRE.
    """
    global _corr_cache, _corr_cache_ts
    now = _time.monotonic()
    if _corr_cache and (now - _corr_cache_ts) < _CORR_TTL:
        return jsonify(_corr_cache)
    try:
        import yfinance as yf
        import numpy as np

        hist = yf.download(
            "SPY TLT",
            period="70d",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        closes = hist["Close"] if "Close" in hist.columns else hist
        spy = closes["SPY"].pct_change().dropna() if "SPY" in closes.columns else None
        tlt = closes["TLT"].pct_change().dropna() if "TLT" in closes.columns else None

        corr_20j = corr_60j = None
        if spy is not None and tlt is not None:
            n20 = min(len(spy), len(tlt), 20)
            n60 = min(len(spy), len(tlt), 60)
            if n20 >= 5:
                c = np.corrcoef(spy.values[-n20:], tlt.values[-n20:])[0, 1]
                if not np.isnan(c):
                    corr_20j = round(float(c), 3)
            if n60 >= 20:
                c = np.corrcoef(spy.values[-n60:], tlt.values[-n60:])[0, 1]
                if not np.isnan(c):
                    corr_60j = round(float(c), 3)

        # Inflation US — lire depuis le cache Bertez/FRED ou valeur statique récente
        inflation_us = None
        try:
            from divisions.middle_office.desk_liquidite.agents.agent_bertez import (
                get_last_bertez_result,
            )
            last = get_last_bertez_result()
            if last:
                # FRED CPIAUCSL change_pct donne ~YoY si période = 12 mois
                cpi = last.get("data", {}).get("fred", {}).get("energy_cpi", {})
                if cpi.get("change_12m_pct") is not None:
                    inflation_us = round(float(cpi["change_12m_pct"]), 2)
        except Exception:
            pass

        # Régime
        if corr_20j is not None and corr_20j > 0 and (inflation_us is None or inflation_us > 2.5):
            regime = "REGIME_INFLATION"
            actifs = _ACTIFS_INFLATION
        elif corr_20j is not None and corr_20j < -0.3:
            regime = "DECORRELATION"
            actifs = _ACTIFS_DECORR
        else:
            regime = "NEUTRE"
            actifs = []

        result = {
            "correlation_20j":    corr_20j,
            "correlation_60j":    corr_60j,
            "inflation_us":       inflation_us,
            "regime":             regime,
            "actifs_recommandes": actifs,
            "timestamp":          datetime.utcnow().isoformat(),
        }
        _corr_cache    = result
        _corr_cache_ts = now
        return jsonify(result)
    except Exception as e:
        logger.error("correlations actoblig: %s", e)
        if _corr_cache:
            return jsonify(_corr_cache)
        return jsonify({
            "correlation_20j": None, "correlation_60j": None,
            "inflation_us": None, "regime": "INCONNU", "actifs_recommandes": [],
            "erreur": str(e), "timestamp": datetime.utcnow().isoformat(),
        })


@app.route("/api/scheduler/etat")
def get_scheduler_etat():
    try:
        jobs = []
        for job in _scheduler.get_jobs():
            jobs.append({
                "id":              job.id,
                "prochaine_exec":  job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger":         str(job.trigger),
                "dernier_resultat": _job_results.get(job.id, {}).get("statut", "pending"),
            })
        jobs.sort(key=lambda j: j["prochaine_exec"] or "9999")
        return jsonify({
            "running":  _scheduler.running,
            "nb_jobs":  len(jobs),
            "timezone": "Europe/Paris",
            "jobs":     jobs,
        })
    except Exception as e:
        logger.error("scheduler/etat: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/scheduler/resultats")
def get_scheduler_resultats():
    return jsonify(_job_results)


@app.route("/api/maintenance/health")
def get_maintenance_health():
    from maintenance import get_health as _health
    from config import DB_PATH
    return jsonify(_health(engine, DB_PATH, len(_ws_queues)))


# ---------------------------------------------------------------------------
# Alpha Lab — Pilier 4 Intelligence
# ---------------------------------------------------------------------------


@app.route("/api/alpha-lab/rapport")
def get_alpha_lab_rapport():
    """Rapport complet Alpha Lab : signaux backtestés + scores facteurs watchlist."""
    try:
        force = request.args.get("force", "0") == "1"
        from divisions.alpha_lab.valide_signaux import generer_rapport
        from divisions.alpha_lab.agent_facteurs import get_agent_facteurs
        rapport_signaux = generer_rapport(force=force)
        rapport_facteurs = get_agent_facteurs().scorer_watchlist(force=force)
        return jsonify({"signaux": rapport_signaux, "facteurs": rapport_facteurs})
    except Exception as exc:
        logger.error("alpha-lab/rapport: %s", exc)
        return jsonify({"erreur": str(exc)}), 500


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


# ── Veille Stratégique RSS ───────────────────────────────────────────────────

@app.route("/api/veille-strategique")
def get_veille_strategique():
    try:
        from divisions.gerant_delegue.agent_veille_strategique import get_agent_veille
        force = request.args.get("force", "0") == "1"
        agent = get_agent_veille()
        articles = agent.analyser(forcer=force)
        return jsonify({
            "articles": articles[:30],
            "etat":     agent.etat(),
        })
    except Exception as e:
        logger.error("veille-strategique: %s", e)
        return jsonify({"erreur": str(e)}), 500


@app.route("/api/veille-strategique/historique")
def get_veille_historique():
    try:
        from divisions.gerant_delegue.agent_veille_strategique import get_agent_veille
        return jsonify(get_agent_veille().historique(limite=100))
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


# ── Agent Flux Macro — Division Research ─────────────────────────────────────

@app.route("/api/flux-macro")
def get_flux_macro():
    """Analyse flux de capitaux : ratios, anomalies, CFTC, calendrier IPOs."""
    try:
        force = request.args.get("force", "0") == "1"
        from divisions.research.agent_flux_macro import get_agent_flux_macro
        return jsonify(get_agent_flux_macro().analyser(forcer=force))
    except Exception as exc:
        logger.error("flux-macro: %s", exc)
        return jsonify({"erreur": str(exc)}), 500


@app.route("/api/flux-macro/journal")
def get_flux_macro_journal():
    try:
        limite = int(request.args.get("limit", 50))
        from divisions.research.agent_flux_macro import get_agent_flux_macro
        return jsonify(get_agent_flux_macro().journal(limite=limite))
    except Exception as exc:
        logger.error("flux-macro/journal: %s", exc)
        return jsonify({"erreur": str(exc)}), 500


@app.route("/api/flux-macro/etat")
def get_flux_macro_etat():
    """Retourne l'état courant de l'agent (depuis cache, sans refetch)."""
    try:
        from divisions.research.agent_flux_macro import get_agent_flux_macro
        return jsonify(get_agent_flux_macro().etat())
    except Exception as exc:
        logger.error("flux-macro/etat: %s", exc)
        return jsonify({"erreur": str(exc)}), 500


@app.route("/api/flux-macro/scan-contexte", methods=["POST"])
def post_flux_macro_scan_contexte():
    """
    Scan contexte avec événement absorbeur injecté (Règle Monétaire Éternelle).
    Body JSON : {titre, valorisation, date_prevue, source, type, note}
    """
    body = request.get_json(silent=True) or {}
    if not body.get("titre"):
        return jsonify({"erreur": "champ 'titre' requis"}), 400
    try:
        from divisions.research.agent_flux_macro import get_agent_flux_macro
        return jsonify(get_agent_flux_macro().scan_contexte(body))
    except Exception as exc:
        logger.error("flux-macro/scan-contexte: %s", exc)
        return jsonify({"erreur": str(exc)}), 500


@app.route("/api/flux-macro/taux-reussite")
def get_flux_macro_taux_reussite():
    """Taux de réussite des signaux Flux Macro (signaux corrects / total avec verdict)."""
    try:
        from divisions.research.agent_flux_macro import get_agent_flux_macro
        return jsonify(get_agent_flux_macro().taux_reussite())
    except Exception as exc:
        logger.error("flux-macro/taux-reussite: %s", exc)
        return jsonify({"erreur": str(exc)}), 500


@app.route("/api/flux-macro/journal/<int:journal_id>/verdict", methods=["POST"])
def post_flux_macro_verdict(journal_id: int):
    """Enregistre manuellement un verdict a posteriori sur un signal journalisé."""
    body = request.get_json(silent=True) or {}
    verdict      = body.get("verdict")          # "CORRECT" | "INCORRECT"
    faux_positif = body.get("faux_positif")     # true | false | null
    if verdict not in ("CORRECT", "INCORRECT"):
        return jsonify({"erreur": "verdict doit être 'CORRECT' ou 'INCORRECT'"}), 400
    try:
        from divisions.research.agent_flux_macro import get_agent_flux_macro
        get_agent_flux_macro().mettre_a_jour_verdict(journal_id, verdict, faux_positif)
        tr = get_agent_flux_macro().taux_reussite()
        return jsonify({"status": "ok", "journal_id": journal_id,
                        "verdict": verdict, "taux_reussite": tr})
    except Exception as exc:
        logger.error("flux-macro/verdict: %s", exc)
        return jsonify({"erreur": str(exc)}), 500


@app.route("/api/flux-macro/rapport-flash", methods=["POST"])
def post_flux_macro_rapport_flash():
    """Génère un rapport flash immédiat (sans attendre le scheduler)."""
    try:
        from divisions.research.agent_flux_macro import get_agent_flux_macro
        agent = get_agent_flux_macro()
        result = agent.generer_rapport_flash()
        return jsonify(result)
    except Exception as exc:
        logger.error("flux-macro/rapport-flash: %s", exc)
        return jsonify({"erreur": str(exc)}), 500


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
    body = request.get_json(silent=True) or {}
    ticker = body.get("ticker", "")
    if not ticker:
        return jsonify({"erreur": "ticker requis"}), 400
    try:
        # Enrichit avec les données watchlist si disponibles en cache
        try:
            from divisions.investissement.watchlist import get_watchlist_manager
            wl_mgr = get_watchlist_manager()
            cached = wl_mgr.get_cached_result(ticker)
            if cached:
                body = {**cached, **body}
        except Exception as _ce:
            logger.warning("[Comite] Enrichissement watchlist erreur: %s", _ce)
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


@app.route("/api/comite-selection/decisions-agd")
def get_decisions_agd():
    try:
        import sqlite3 as _sqlite3
        import json as _json
        db_path = Path(__file__).resolve().parent.parent / "database" / "king_fund.db"
        with _sqlite3.connect(str(db_path)) as con:
            con.row_factory = _sqlite3.Row
            rows = con.execute(
                "SELECT * FROM decisions_agd ORDER BY ts DESC LIMIT 50"
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("conditions"):
                try:
                    d["conditions"] = _json.loads(d["conditions"])
                except Exception:
                    pass
            d.pop("donnees", None)
            result.append(d)
        return jsonify(result)
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

_scheduler   = BackgroundScheduler(timezone=pytz.timezone("Europe/Paris"))
_job_results: dict = {}   # {job_id: {statut, timestamp, detail}}


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
    misfire_grace_time=600,
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
    misfire_grace_time=600,
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
    misfire_grace_time=600,
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


def _job_alertes_prix():
    """Surveillance seuils prix d'entrée — toutes les 30 min entre 08h–20h."""
    try:
        from divisions.gerant_delegue.agent_alertes_prix import get_agent_alertes_prix
        get_agent_alertes_prix().verifier_seuils()
    except Exception as exc:
        logger.debug("[SCHEDULER] Alertes prix: %s", exc)


_scheduler.add_job(
    _job_alertes_prix,
    CronTrigger(minute="*/30", hour="8-20"),
    id="alertes_prix_surveillance",
    replace_existing=True,
)


def _job_calendrier_evenements():
    """Calendrier corporate — quotidien 08:05, alerte 2 jours avant earnings/dividendes."""
    try:
        from divisions.gerant_delegue.agent_calendrier import get_agent_calendrier
        get_agent_calendrier().verifier_evenements()
    except Exception as exc:
        logger.debug("[SCHEDULER] Calendrier: %s", exc)


_scheduler.add_job(
    _job_calendrier_evenements,
    CronTrigger(hour=8, minute=5),
    id="calendrier_surveillance",
    replace_existing=True,
)


def _job_alpha_lab():
    """Alpha Lab rapport mensuel — 1er du mois 07:00 Paris → envoyé à AGD-01 via Telegram."""
    logger.info("[SCHEDULER] Alpha Lab rapport mensuel")
    try:
        from divisions.alpha_lab.valide_signaux import generer_rapport
        from divisions.gerant_delegue.notifier import send
        rapport = generer_rapport(force=True)
        valides  = ", ".join(rapport.get("valides",  []) or ["aucun"])
        bruits   = ", ".join(rapport.get("bruits",   []) or ["aucun"])
        overfits = ", ".join(rapport.get("overfits", []) or ["aucun"])
        ts = rapport.get("ts", "")[:10]
        msg = (
            f"🔬 <b>Alpha Lab — Rapport Mensuel</b>\n"
            f"✅ Signaux VALIDES : {valides}\n"
            f"📊 Bruit : {bruits}\n"
            f"⚠️ Overfittés : {overfits}\n"
            f"Période : {ts}"
        )
        send(msg)
        logger.info("[SCHEDULER] ✓ Alpha Lab rapport mensuel envoyé Telegram")
    except Exception as exc:
        logger.error("[SCHEDULER] ✗ Alpha Lab: %s", exc)


_scheduler.add_job(
    _job_alpha_lab,
    CronTrigger(day=1, hour=7, minute=0),
    id="alpha_lab_mensuel",
    replace_existing=True,
    misfire_grace_time=600,
)


def _job_veille_strategique():
    """Veille stratégique RSS — toutes les heures."""
    try:
        from divisions.gerant_delegue.agent_veille_strategique import get_agent_veille
        get_agent_veille().analyser(forcer=True)
    except Exception as exc:
        logger.debug("[SCHEDULER] Veille stratégique: %s", exc)


_scheduler.add_job(
    _job_veille_strategique,
    CronTrigger(minute=5),   # toutes les heures à H:05
    id="veille_strategique_horaire",
    replace_existing=True,
)


def _job_backup():
    """Backup quotidien de king_fund.db — 04:00 Paris."""
    logger.info("[SCHEDULER] Backup quotidien king_fund.db")
    try:
        from maintenance.backup import faire_backup
        dest = faire_backup()
        _send_telegram(f"💾 <b>Backup OK</b>\n{dest.name}")
    except Exception as exc:
        logger.error("[SCHEDULER] ✗ Backup ÉCHEC: %s", exc)
        _send_telegram(f"⚠️ Backup ÉCHEC : {exc}")


_scheduler.add_job(
    _job_backup,
    CronTrigger(hour=4, minute=0),
    id="backup_quotidien",
    replace_existing=True,
    misfire_grace_time=600,
)


def _job_screener_mondial():
    """Scan Graham mondial — nuit à 02:30 UTC (~2 min sur 136 titres)."""
    logger.info("[SCHEDULER] Screener mondial démarrage")
    try:
        from divisions.research.agent_screener_mondial import get_screener_mondial
        candidats = get_screener_mondial().scanner()
        logger.info("[SCHEDULER] ✓ Screener mondial — %d candidats", len(candidats))
    except Exception as exc:
        logger.error("[SCHEDULER] ✗ Screener mondial ÉCHEC: %s", exc)


_scheduler.add_job(
    _job_screener_mondial,
    CronTrigger(hour=2, minute=30),
    id="screener_mondial",
    replace_existing=True,
    misfire_grace_time=600,
)


def _job_check_outcomes():
    """Évalue quotidiennement les prédictions Bertez/Morning Brief vs SPY (18:30 Paris)."""
    try:
        from data.signal_history import check_pending_outcomes
        n = check_pending_outcomes()
        if n:
            logger.info("[SCHEDULER] %d signal outcomes mis à jour", n)
    except Exception as e:
        logger.error("[SCHEDULER] check_outcomes: %s", e)


_scheduler.add_job(
    _job_check_outcomes,
    CronTrigger(hour=18, minute=30),
    id="check_signal_outcomes",
    replace_existing=True,
)


def _job_rapport_mensuel():
    """Rapport mensuel automatique — 1er du mois 07:30 Paris."""
    logger.info("[SCHEDULER] Rapport mensuel — 1er du mois")
    try:
        from divisions.rapports.rapport_mensuel import generer_rapport as _gen_mensuel
        chemin = _gen_mensuel(engine)
        logger.info("[SCHEDULER] ✓ Rapport mensuel → %s", chemin)
    except Exception as exc:
        logger.error("[SCHEDULER] ✗ Rapport mensuel ÉCHEC: %s", exc)
        _send_telegram(f"⚠️ Rapport mensuel ÉCHEC : {exc}")


_scheduler.add_job(
    _job_rapport_mensuel,
    CronTrigger(day=1, hour=7, minute=30),
    id="rapport_mensuel",
    replace_existing=True,
    misfire_grace_time=600,
)


def _job_rapport_annuel():
    """Rapport annuel bilan + fiscalité — 31 décembre 18:00 Paris."""
    logger.info("[SCHEDULER] Rapport annuel — 31 décembre")
    try:
        from divisions.rapports.rapport_annuel import generer_rapport as _gen_annuel
        chemin = _gen_annuel(engine)
        logger.info("[SCHEDULER] ✓ Rapport annuel → %s", chemin)
    except Exception as exc:
        logger.error("[SCHEDULER] ✗ Rapport annuel ÉCHEC: %s", exc)
        _send_telegram(f"⚠️ Rapport annuel ÉCHEC : {exc}")


_scheduler.add_job(
    _job_rapport_annuel,
    CronTrigger(month=12, day=31, hour=18, minute=0),
    id="rapport_annuel",
    replace_existing=True,
    misfire_grace_time=600,
)


def _job_suivi_pru():
    """Vérification alertes PRU — toutes les 30 min entre 09h–18h."""
    try:
        from data.suivi_pru import verifier_alertes
        alertes = verifier_alertes()
        if alertes:
            logger.info("[SCHEDULER] PRU — %d alerte(s) déclenchée(s)", len(alertes))
    except Exception as exc:
        logger.debug("[SCHEDULER] PRU: %s", exc)


_scheduler.add_job(
    _job_suivi_pru,
    CronTrigger(minute="*/30", hour="9-18"),
    id="suivi_pru_alertes",
    replace_existing=True,
)


def _job_autonomie_check():
    """Vérifie les validations expirées → AGD-01 passe en autonomie si 48h dépassées."""
    try:
        from divisions.gouvernance.autonomie import get_autonomie_manager
        expirees = get_autonomie_manager().check_timeouts()
        if expirees:
            logger.warning("[SCHEDULER] AUTONOMIE — %d validation(s) expirée(s)", len(expirees))
    except Exception as exc:
        logger.debug("[SCHEDULER] Autonomie: %s", exc)


_scheduler.add_job(
    _job_autonomie_check,
    CronTrigger(minute=15),   # toutes les heures à H:15
    id="autonomie_check_timeouts",
    replace_existing=True,
)


def _job_sync_gouvernance():
    """Synchronise le régime CIO → moteur de gouvernance (toutes les heures)."""
    try:
        from divisions.gouvernance.gouvernance import get_gouvernance_engine, NiveauAutorite
        gov = get_gouvernance_engine()
        # Sync régime CIO
        try:
            from app import engine as _engine  # noqa — référence circulaire ok ici
            hub = getattr(_engine, "_hub", None)
            if hub:
                bs_halt = hub.black_swan_halt
                vix = hub.last_vix if hasattr(hub, "last_vix") else None
                gov.notifier_black_swan(bs_halt, vix)
        except Exception:
            pass
        # Sync régime CIO Macro depuis dernier appel /api/cio/allocation
        try:
            import json
            from pathlib import Path
            cio_cache = Path(__file__).parent.parent / "data" / "cio_allocation_cache.json"
            if cio_cache.exists():
                data = json.loads(cio_cache.read_text(encoding="utf-8"))
                gov.notifier_regime_cio(data.get("regime", "NEUTRAL"))
        except Exception:
            pass
    except Exception as exc:
        logger.debug("[SCHEDULER] Sync gouvernance: %s", exc)


_scheduler.add_job(
    _job_sync_gouvernance,
    CronTrigger(minute=30),   # toutes les heures à H:30
    id="sync_gouvernance",
    replace_existing=True,
)


# ── Agent Flux Macro — 2×/jour : 10h00 et 18h00 Europe/Paris

def _job_flux_macro():
    logger.info("[SCHEDULER] Agent Flux Macro — analyse flux de capitaux")
    try:
        from divisions.research.agent_flux_macro import get_agent_flux_macro
        result = get_agent_flux_macro().analyser(forcer=True)
        nb_anom = len(result.get("anomalies", []))
        confiance = result.get("confiance", "?")
        logger.info(
            "[SCHEDULER] Flux Macro ✓ — %d anomalie(s), confiance=%s, sources=%d",
            nb_anom, confiance, result.get("nb_sources", 0),
        )
        if nb_anom == 0:
            logger.info("[SCHEDULER] Flux Macro — aucune anomalie significative")
    except Exception as exc:
        logger.error("[SCHEDULER] Flux Macro ÉCHEC: %s", exc)


_scheduler.add_job(
    _job_flux_macro,
    CronTrigger(hour="10,18", minute=0),   # 10h00 et 18h00 Europe/Paris
    id="flux_macro_biquotidien",
    replace_existing=True,
    misfire_grace_time=600,
)


def _job_flux_macro_hebdo():
    """Rapport hebdomadaire Flux Macro — lundi 07:00 UTC."""
    logger.info("[SCHEDULER] Flux Macro hebdo — génération rapport lundi 07:00 UTC")
    try:
        from divisions.research.agent_flux_macro import get_agent_flux_macro
        result = get_agent_flux_macro().generer_rapport_hebdo()
        logger.info(
            "[SCHEDULER] Flux Macro hebdo ✓ — sauvegardé : %s",
            result.get("chemin", "?"),
        )
    except Exception as exc:
        logger.error("[SCHEDULER] Flux Macro hebdo ÉCHEC: %s", exc)


_scheduler.add_job(
    _job_flux_macro_hebdo,
    CronTrigger(day_of_week="mon", hour=7, minute=0),   # lundi 07:00 UTC
    id="flux_macro_hebdo",
    replace_existing=True,
)


# ---------------------------------------------------------------------------
# Watchdog — alertes Telegram sur arrêt/crash du serveur
# ---------------------------------------------------------------------------

def _on_shutdown(msg: str = "arrêt normal") -> None:
    try:
        _scheduler.shutdown(wait=False)
        logger.info("[SHUTDOWN] APScheduler arrêté proprement")
    except Exception:
        pass
    try:
        engine.stop()
        logger.info("[SHUTDOWN] TradingEngine arrêté proprement")
    except Exception:
        pass
    _send_telegram(
        f"🔴 <b>King Fund — Serveur arrêté</b>\n"
        f"Motif : {msg}\n"
        f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )


def _crash_hook(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    import traceback
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical("Exception non gérée:\n%s", tb_str)
    _send_telegram(
        f"🚨 <b>King Fund — CRASH SERVEUR</b>\n"
        f"<code>{str(exc_value)[:300]}</code>"
    )


sys.excepthook = _crash_hook

atexit.register(_on_shutdown, "atexit (arrêt normal ou Ctrl+C)")

for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGBREAK", None)):
    if sig is not None:
        try:
            signal.signal(sig, lambda s, f: (_on_shutdown("SIGTERM/SIGBREAK"), sys.exit(0)))
        except Exception:
            pass


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
        f"• AGD-01 actif | Rapport lundi 08:00 + PDF 09:00\n"
        f"• Rapport mensuel : 1er du mois 07:30 (Claude + PDF)\n"
        f"• Rapport annuel : 31 déc. 18:00 (bilan + fiscalité FSC-FRA-01)\n"
        f"• Suivi PRU : alertes objectif/stop-loss toutes les 30 min\n"
        f"• Comité Sélection : chaque soir 23:00\n"
        f"• Actualités : toutes les 30 min\n"
        f"• Veille stratégique RSS : toutes les heures (Bertez/Dalio/Howell/InflationGuy)\n"
        f"• Alertes prix : VPK.AS&lt;44€ · BIPC&lt;35$ · DNB.OL&lt;280kr · TTE.PA&gt;-5%\n"
        f"• Backup quotidien 04:00 | Watchdog actif\n"
        f"• Flux Macro (Détective Capitaux) : 10h00 + 18h00 Paris\n"
        f"Objectif retraite Zoubida 2041 — 500 000€"
    )
    # Dev/Windows uniquement — sur RPi utiliser gunicorn via systemd (voir install_raspberry.sh)
    logger.info("Server starting on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)

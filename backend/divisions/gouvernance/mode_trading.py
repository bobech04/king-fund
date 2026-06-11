"""
Module de transition Simulation → Réel.

FLAG global MODE_TRADING :
  SIMULATION — traders utilisent le capital virtuel (STARTING_CAPITAL par défaut)
  REEL       — traders utilisent le capital réel injecté par Zoubida

Transition :
  1. POST /api/gouvernance/mode/basculer-reel {capital: 500}
     → Envoie alerte Telegram avec un validation_id
     → Statut passe à PENDING_REEL
  2. POST /api/gouvernance/mode/confirmer/{validation_id}
     → Bascule en mode REEL, injecte le capital, préserve l'historique simulation
     → Log la transition dans SQLite

L'historique de simulation reste intact (colonne mode='SIMULATION' en DB).
"""
from __future__ import annotations
import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_FILE = Path(__file__).resolve().parents[3] / "data" / "gouvernance" / "mode_trading.json"
_lock = threading.Lock()
_instance: "ModeTradingManager | None" = None

MODE_SIMULATION = "SIMULATION"
MODE_REEL       = "REEL"


class ModeTradingManager:
    """Gère la bascule simulation ↔ réel."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict = self._charger()

    # ------------------------------------------------------------------
    # Persistance
    # ------------------------------------------------------------------

    def _charger(self) -> dict:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _STATE_FILE.exists():
            try:
                return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "mode":           MODE_SIMULATION,
            "capital_reel":   0.0,
            "transition_ts":  None,
            "pending_bascule": None,   # {id, capital, soumis_ts, deadline_ts}
            "historique":     [],      # [{ts, mode_avant, mode_apres, capital, decideur}]
        }

    def _sauvegarder(self) -> None:
        try:
            _STATE_FILE.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("[MODE] Save: %s", e)

    # ------------------------------------------------------------------
    # Lecture du mode courant
    # ------------------------------------------------------------------

    def get_mode(self) -> str:
        with self._lock:
            # Source of truth: config_user.json si dispo
            try:
                from data.config_user import get_config
                return get_config().get("mode_trading", self._state["mode"])
            except Exception:
                return self._state["mode"]

    def get_capital_reel(self) -> float:
        with self._lock:
            try:
                from data.config_user import get_config
                return float(get_config().get("capital_reel_eur", self._state["capital_reel"]))
            except Exception:
                return self._state["capital_reel"]

    def is_reel(self) -> bool:
        return self.get_mode() == MODE_REEL

    # ------------------------------------------------------------------
    # Demande de bascule → réel
    # ------------------------------------------------------------------

    def demander_bascule_reel(self, capital_injecte: float) -> str:
        """
        Initie la procédure de bascule en mode REEL.
        Envoie une alerte Telegram et retourne un validation_id.
        """
        if capital_injecte <= 0:
            raise ValueError("Le capital injecté doit être positif")

        vid = str(uuid.uuid4())[:12]
        now = datetime.utcnow()
        deadline = now + timedelta(hours=24)

        pending = {
            "id":          vid,
            "capital":     capital_injecte,
            "soumis_ts":   now.isoformat(),
            "deadline_ts": deadline.isoformat(),
        }
        with self._lock:
            self._state["pending_bascule"] = pending
            self._sauvegarder()

        self._envoyer_alerte_telegram(vid, capital_injecte, deadline)
        logger.warning("[MODE] Bascule REEL demandée — capital %.0f€ — id=%s", capital_injecte, vid)
        return vid

    def _envoyer_alerte_telegram(self, vid: str, capital: float, deadline: datetime) -> None:
        try:
            from divisions.gerant_delegue.notifier import alerte
            alerte(
                f"⚠️ <b>BASCULE MODE RÉEL DEMANDÉE</b>\n\n"
                f"Capital à injecter : <b>{capital:,.0f}€</b>\n"
                f"ID validation : <code>{vid}</code>\n"
                f"Deadline : {deadline.strftime('%d/%m/%Y %H:%M')} UTC\n\n"
                f"🔴 Cette action est <b>irréversible</b> sans nouvelle confirmation.\n"
                f"L'historique de simulation sera préservé.\n\n"
                f"Pour confirmer :\n"
                f"<code>POST /api/gouvernance/mode/confirmer/{vid}</code>\n\n"
                f"Pour annuler :\n"
                f"<code>POST /api/gouvernance/mode/annuler/{vid}</code>"
            )
        except Exception as e:
            logger.debug("[MODE] Telegram: %s", e)

    # ------------------------------------------------------------------
    # Confirmation / Annulation
    # ------------------------------------------------------------------

    def confirmer_bascule(self, validation_id: str) -> dict:
        """Confirme la bascule en mode REEL. Retourne le nouvel état."""
        with self._lock:
            pending = self._state.get("pending_bascule")
            if not pending or pending.get("id") != validation_id:
                raise ValueError(f"Validation {validation_id} non trouvée ou expirée")

            deadline = datetime.fromisoformat(pending["deadline_ts"])
            if datetime.utcnow() > deadline:
                self._state["pending_bascule"] = None
                self._sauvegarder()
                raise ValueError("Délai de confirmation expiré (24h)")

            capital = pending["capital"]
            mode_avant = self._state["mode"]
            now = datetime.utcnow().isoformat()

            self._state["mode"]           = MODE_REEL
            self._state["capital_reel"]   = capital
            self._state["transition_ts"]  = now
            self._state["pending_bascule"] = None
            self._state.setdefault("historique", []).append({
                "ts":          now,
                "mode_avant":  mode_avant,
                "mode_apres":  MODE_REEL,
                "capital":     capital,
                "decideur":    "Zoubida",
            })
            self._sauvegarder()

        # Met à jour config_user.json aussi
        try:
            from data.config_user import update_config
            update_config("mode_trading", MODE_REEL)
            update_config("capital_reel_eur", capital)
        except Exception as e:
            logger.debug("[MODE] config_user update: %s", e)

        # Log gouvernance
        try:
            from divisions.gouvernance.gouvernance import get_gouvernance_engine, NiveauAutorite
            get_gouvernance_engine().soumettre_decision(
                "Zoubida", NiveauAutorite.AGD_01,
                "BASCULE_REEL", None,
                f"Capital réel injecté : {capital:,.0f}€",
            )
        except Exception:
            pass

        self._notifier_confirmation(capital)
        logger.warning("[MODE] ✓ Bascule MODE RÉEL confirmée — capital %.0f€", capital)
        return self.get_etat()

    def annuler_bascule(self, validation_id: str) -> bool:
        with self._lock:
            pending = self._state.get("pending_bascule")
            if not pending or pending.get("id") != validation_id:
                return False
            self._state["pending_bascule"] = None
            self._sauvegarder()
        logger.info("[MODE] Bascule REEL annulée")
        return True

    def revenir_simulation(self) -> dict:
        """Repasse en mode SIMULATION (sans perdre l'historique réel)."""
        with self._lock:
            mode_avant = self._state["mode"]
            now = datetime.utcnow().isoformat()
            self._state["mode"] = MODE_SIMULATION
            self._state.setdefault("historique", []).append({
                "ts":         now,
                "mode_avant": mode_avant,
                "mode_apres": MODE_SIMULATION,
                "capital":    self._state.get("capital_reel", 0),
                "decideur":   "Zoubida",
            })
            self._sauvegarder()

        try:
            from data.config_user import update_config
            update_config("mode_trading", MODE_SIMULATION)
        except Exception:
            pass

        logger.info("[MODE] Retour en MODE SIMULATION")
        return self.get_etat()

    def _notifier_confirmation(self, capital: float) -> None:
        try:
            from divisions.gerant_delegue.notifier import send
            send(
                f"✅ <b>MODE RÉEL ACTIVÉ</b>\n"
                f"Capital réel injecté : <b>{capital:,.0f}€</b>\n"
                f"L'historique de simulation est préservé.\n"
                f"Les traders utilisent désormais le capital réel."
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # API lecture
    # ------------------------------------------------------------------

    def get_etat(self) -> dict:
        with self._lock:
            state = dict(self._state)
        return {
            "mode":          state["mode"],
            "capital_reel":  state.get("capital_reel", 0),
            "transition_ts": state.get("transition_ts"),
            "en_attente":    state.get("pending_bascule") is not None,
            "pending":       state.get("pending_bascule"),
            "historique":    list(reversed(state.get("historique", [])[-10:])),
            "badge_couleur": "#ff4444" if state["mode"] == MODE_REEL else "#00e5a0",
            "ts": datetime.utcnow().isoformat(),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

def get_mode_trading() -> ModeTradingManager:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ModeTradingManager()
    return _instance

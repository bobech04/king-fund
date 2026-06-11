"""
Hiérarchie d'autorité formalisée du King Fund.

Niveaux (du plus prioritaire au moins prioritaire) :
  1. BLACK_SWAN  — arrêt d'urgence absolu (VIX ≥ 35)
  2. AGD_01      — Gérant Délégué (veto émotionnel, risque)
  3. CIO_MACRO   — CIO Allocation Macro (régime de marché)
  4. TRADER      — 30 traders algorithmiques

Règles de conflit :
  • Tout agent peut BLOQUER une décision d'un niveau inférieur.
  • Un agent ne peut PAS outrepasser un niveau supérieur.
  • Chaque conflit est loggué avec l'auteur, la raison et le bloqueur.
"""
from __future__ import annotations
import json
import logging
import sqlite3
import threading
import uuid
from enum import IntEnum
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH: Path | None = None
_lock = threading.Lock()
_instance: "GouvernanceEngine | None" = None


def _get_db() -> Path:
    global DB_PATH
    if DB_PATH is None:
        try:
            from config import DB_PATH as _dp
            DB_PATH = _dp
        except Exception:
            DB_PATH = Path(__file__).resolve().parents[3] / "database" / "king_fund.db"
    return DB_PATH


# ── Hiérarchie ────────────────────────────────────────────────────────────────

class NiveauAutorite(IntEnum):
    BLACK_SWAN = 1
    AGD_01     = 2
    CIO_MACRO  = 3
    TRADER     = 4


NIVEAU_LABELS = {
    NiveauAutorite.BLACK_SWAN: "Black Swan",
    NiveauAutorite.AGD_01:     "AGD-01 Gérant Délégué",
    NiveauAutorite.CIO_MACRO:  "CIO Macro",
    NiveauAutorite.TRADER:     "Trader",
}

# Durée pendant laquelle un veto AGD-01 bloque un ticker (minutes)
_VETO_AGD_DUREE_MIN = 60

# En régime CIO RISK_OFF : bloquer les BUY des traders
_CIO_REGIMES_BLOQUANTS = {"RISK_OFF"}


# ── Moteur de gouvernance ─────────────────────────────────────────────────────

class GouvernanceEngine:
    """Singleton thread-safe — arbitre toutes les décisions du fonds."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # État courant haute autorité
        self._black_swan_actif: bool = False
        self._cio_regime: str = "NEUTRAL"
        # Vetos AGD-01 en cours : {ticker: expiry_datetime}
        self._vetos_agd: dict[str, datetime] = {}
        self._init_db()

    # ------------------------------------------------------------------
    # Init DB
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        try:
            conn = sqlite3.connect(str(_get_db()), check_same_thread=False, timeout=15)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS gouvernance_log (
                    id          TEXT PRIMARY KEY,
                    ts          TEXT NOT NULL,
                    auteur      TEXT NOT NULL,
                    niveau      INTEGER NOT NULL,
                    action      TEXT NOT NULL,
                    ticker      TEXT,
                    raison      TEXT,
                    acceptee    INTEGER NOT NULL DEFAULT 1,
                    bloquee_par TEXT,
                    mode_trading TEXT DEFAULT 'SIMULATION'
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("[GOV] DB init: %s", e)

    # ------------------------------------------------------------------
    # API publique principale
    # ------------------------------------------------------------------

    def soumettre_decision(
        self,
        auteur:  str,
        niveau:  int,
        action:  str,
        ticker:  str | None = None,
        raison:  str = "",
    ) -> tuple[bool, str | None]:
        """
        Soumet une décision pour validation hiérarchique.
        Retourne (acceptee: bool, bloquee_par: str|None).
        """
        with self._lock:
            bloquee_par = self._evaluer(niveau, action, ticker)
            acceptee = bloquee_par is None
            self._logguer(auteur, niveau, action, ticker, raison, acceptee, bloquee_par)
            return acceptee, bloquee_par

    def autoriser_trade(
        self,
        trader_id: int,
        action: dict,
        ticker: str,
    ) -> tuple[bool, str | None]:
        """
        Vérifie si un trade de trader est autorisé selon la hiérarchie.
        Retourne (autorisé, raison_blocage).
        """
        act = action.get("action", "hold")
        if act == "hold":
            return True, None

        auteur = f"TRD{trader_id:02d}"
        raison = f"{act.upper()} {ticker} {action.get('amount', 0):.0f}€"
        return self.soumettre_decision(auteur, NiveauAutorite.TRADER, act, ticker, raison)

    # ------------------------------------------------------------------
    # Mise à jour état haute autorité
    # ------------------------------------------------------------------

    def notifier_black_swan(self, actif: bool, vix: float | None = None) -> None:
        with self._lock:
            self._black_swan_actif = actif
        if actif:
            self.soumettre_decision(
                "Black Swan Agent", NiveauAutorite.BLACK_SWAN,
                "HALT_ALL", None,
                f"VIX={vix:.1f}" if vix else "VIX critique",
            )

    def notifier_regime_cio(self, regime: str) -> None:
        with self._lock:
            self._cio_regime = regime

    def enregistrer_veto_agd(self, ticker: str, raison: str) -> None:
        """Enregistre un veto AGD-01 sur un ticker pendant _VETO_AGD_DUREE_MIN."""
        try:
            from data.config_user import get_config
            duree = get_config().get("gouvernance", {}).get("veto_agd_duree_minutes", _VETO_AGD_DUREE_MIN)
        except Exception:
            duree = _VETO_AGD_DUREE_MIN
        expiry = datetime.utcnow() + timedelta(minutes=duree)
        with self._lock:
            self._vetos_agd[ticker.upper()] = expiry
        self.soumettre_decision(
            "AGD-01", NiveauAutorite.AGD_01,
            "VETO", ticker, raison,
        )
        logger.info("[GOV] Veto AGD-01 sur %s jusqu'à %s", ticker, expiry.strftime("%H:%M"))

    # ------------------------------------------------------------------
    # Évaluation interne (appelée sous lock)
    # ------------------------------------------------------------------

    def _evaluer(self, niveau: int, action: str, ticker: str | None) -> str | None:
        """Retourne le nom du bloqueur si décision refusée, None si acceptée."""
        # Règle 1 : Black Swan bloque tout sauf BLACK_SWAN lui-même
        if self._black_swan_actif and niveau > NiveauAutorite.BLACK_SWAN:
            return "Black Swan (HALT actif)"

        # Règle 2 : Veto AGD-01 sur un ticker spécifique
        if ticker and niveau > NiveauAutorite.AGD_01:
            expiry = self._vetos_agd.get(ticker.upper())
            if expiry and datetime.utcnow() < expiry:
                return f"AGD-01 (veto {ticker} jusqu'à {expiry.strftime('%H:%M')})"
            elif expiry:
                del self._vetos_agd[ticker.upper()]  # veto expiré

        # Règle 3 : CIO RISK_OFF bloque les BUY des traders
        if (niveau >= NiveauAutorite.TRADER
                and action.lower() == "buy"
                and self._cio_regime in _CIO_REGIMES_BLOQUANTS):
            return f"CIO Macro (régime {self._cio_regime} — BUY bloqué)"

        return None

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _logguer(
        self, auteur: str, niveau: int, action: str, ticker: str | None,
        raison: str, acceptee: bool, bloquee_par: str | None,
    ) -> None:
        try:
            from data.config_user import get_config
            log_all = get_config().get("gouvernance", {}).get("log_tous_trades", False)
        except Exception:
            log_all = False

        # Ne logguer les trades acceptés que si log_tous_trades=True
        if acceptee and niveau == NiveauAutorite.TRADER and not log_all:
            return

        try:
            from data.config_user import get_config
            mode = get_config().get("mode_trading", "SIMULATION")
        except Exception:
            mode = "SIMULATION"

        entry = {
            "id":         str(uuid.uuid4())[:8],
            "ts":         datetime.utcnow().isoformat(),
            "auteur":     auteur,
            "niveau":     niveau,
            "action":     action,
            "ticker":     ticker,
            "raison":     raison[:200] if raison else "",
            "acceptee":   acceptee,
            "bloquee_par": bloquee_par,
            "mode_trading": mode,
        }
        try:
            conn = sqlite3.connect(str(_get_db()), check_same_thread=False, timeout=5)
            conn.execute(
                "INSERT OR IGNORE INTO gouvernance_log VALUES (?,?,?,?,?,?,?,?,?,?)",
                (entry["id"], entry["ts"], entry["auteur"], entry["niveau"],
                 entry["action"], entry["ticker"], entry["raison"],
                 int(entry["acceptee"]), entry["bloquee_par"], entry["mode_trading"]),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("[GOV] Log DB: %s", e)

        if not acceptee:
            logger.warning(
                "[GOV] BLOQUÉ — %s (%s) voulait %s %s → bloqué par %s",
                auteur, NIVEAU_LABELS.get(niveau, niveau),
                action, ticker or "", bloquee_par,
            )

    # ------------------------------------------------------------------
    # API lecture
    # ------------------------------------------------------------------

    def get_log(self, limit: int = 50) -> list[dict]:
        try:
            conn = sqlite3.connect(str(_get_db()), check_same_thread=False, timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM gouvernance_log ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_etat(self) -> dict:
        with self._lock:
            vetos = {t: dt.isoformat() for t, dt in self._vetos_agd.items()
                     if datetime.utcnow() < dt}
        try:
            from data.config_user import get_config
            cfg_gov = get_config().get("gouvernance", {})
        except Exception:
            cfg_gov = {}
        return {
            "hierarchie": [
                {"niveau": 1, "nom": "Black Swan",           "actif": self._black_swan_actif, "couleur": "#ff4444"},
                {"niveau": 2, "nom": "AGD-01 Gérant Délégué","actif": True,                   "couleur": "#ffd700"},
                {"niveau": 3, "nom": "CIO Macro",            "actif": True, "regime": self._cio_regime, "couleur": "#4488ff"},
                {"niveau": 4, "nom": "30 Traders",           "actif": True,                   "couleur": "#00e5a0"},
            ],
            "black_swan_actif":  self._black_swan_actif,
            "cio_regime":        self._cio_regime,
            "vetos_agd_actifs":  vetos,
            "hook_engine_actif": cfg_gov.get("activer_hook_engine", True),
            "ts": datetime.utcnow().isoformat(),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

def get_gouvernance_engine() -> GouvernanceEngine:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = GouvernanceEngine()
    return _instance

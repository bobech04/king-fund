"""
Agent Calendrier — alertes Telegram 2 jours avant earnings/dividendes.
"""
from __future__ import annotations
import json
import logging
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

_ETAT_FILE = Path(__file__).resolve().parents[2] / "data" / "alertes_calendrier_etat.json"

EARNINGS_TICKERS: list[dict[str, str]] = [
    {"ticker": "GTT.PA",  "nom": "GTT"},
    {"ticker": "TEL.OL",  "nom": "Telenor"},
    {"ticker": "TTE.PA",  "nom": "TotalEnergies"},
    {"ticker": "VPK.AS",  "nom": "Vopak"},
]

DIVIDENDS_TICKERS: list[dict[str, str]] = [
    {"ticker": "O",  "nom": "Realty Income"},
    {"ticker": "VZ", "nom": "Verizon"},
]

HORIZON_JOURS = 30   # fenêtre d'affichage frontend
ALERTE_AVANT  = 2    # jours avant l'événement pour déclencher alerte Telegram


def _to_date(val: Any) -> date | None:
    """Convertit un timestamp unix, date, ou string en date Python."""
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    try:
        import pandas as pd
        if hasattr(pd, "Timestamp") and isinstance(val, pd.Timestamp):
            return val.date()
    except ImportError:
        pass
    try:
        # Unix timestamp (integer)
        return datetime.fromtimestamp(int(val)).date()
    except (TypeError, ValueError, OSError):
        pass
    try:
        return datetime.fromisoformat(str(val)).date()
    except ValueError:
        pass
    return None


class AgentCalendrier:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._alertes: dict[str, str] = {}  # {"{ticker}_{type}_{date}": "YYYY-MM-DD alerte"}
        self._charger_etat()

    # ── Persistance anti-spam ────────────────────────────────────────

    def _charger_etat(self) -> None:
        try:
            if _ETAT_FILE.exists():
                self._alertes = json.loads(_ETAT_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[Calendrier] Chargement état: %s", e)
            self._alertes = {}

    def _sauver_etat(self) -> None:
        try:
            _ETAT_FILE.parent.mkdir(parents=True, exist_ok=True)
            _ETAT_FILE.write_text(json.dumps(self._alertes, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("[Calendrier] Sauvegarde état: %s", e)

    def _cle_event(self, ticker: str, type_evt: str, evt_date: date) -> str:
        return f"{ticker}_{type_evt}_{evt_date.isoformat()}"

    def _deja_alerte(self, cle: str) -> bool:
        return cle in self._alertes

    def _marquer_alerte(self, cle: str) -> None:
        self._alertes[cle] = date.today().isoformat()
        self._sauver_etat()

    # ── Fetch données Yahoo Finance ─────────────────────────────────

    def _fetch_earnings(self, ticker: str) -> date | None:
        try:
            cal = yf.Ticker(ticker).calendar
            if cal is None:
                return None
            # calendar peut être un dict ou un DataFrame selon la version de yfinance
            if isinstance(cal, dict):
                val = cal.get("Earnings Date") or cal.get("earnings_date")
                if isinstance(val, (list, tuple)):
                    val = val[0] if val else None
                return _to_date(val)
            # DataFrame : ligne "Earnings Date"
            import pandas as pd
            if isinstance(cal, pd.DataFrame):
                if "Earnings Date" in cal.index:
                    raw = cal.loc["Earnings Date"].iloc[0]
                    return _to_date(raw)
        except Exception as e:
            logger.debug("[Calendrier] Earnings %s: %s", ticker, e)
        return None

    def _fetch_dividende(self, ticker: str) -> date | None:
        try:
            info = yf.Ticker(ticker).info or {}
            val = info.get("exDividendDate") or info.get("dividendDate")
            return _to_date(val)
        except Exception as e:
            logger.debug("[Calendrier] Dividende %s: %s", ticker, e)
        return None

    # ── Logique principale ──────────────────────────────────────────

    def verifier_evenements(self) -> list[dict[str, Any]]:
        """Vérifie les prochains événements, alerte Telegram si dans ALERTE_AVANT jours."""
        from . import notifier
        today     = date.today()
        resultats = []

        # Earnings
        for item in EARNINGS_TICKERS:
            ticker = item["ticker"]
            nom    = item["nom"]
            evt_dt = self._fetch_earnings(ticker)
            if evt_dt is None:
                continue
            jours = (evt_dt - today).days
            if 0 <= jours <= HORIZON_JOURS:
                r = {
                    "ticker":         ticker,
                    "nom":            nom,
                    "type":           "earnings",
                    "date":           evt_dt.isoformat(),
                    "jours_restants": jours,
                }
                resultats.append(r)
                if 0 <= jours <= ALERTE_AVANT:
                    cle = self._cle_event(ticker, "earnings", evt_dt)
                    with self._lock:
                        if not self._deja_alerte(cle):
                            notifier.alerte(
                                f"📋 Earnings dans {jours}j — {nom} ({ticker})",
                                f"Date publication résultats : <b>{evt_dt.strftime('%d/%m/%Y')}</b>",
                                niveau="warning",
                            )
                            self._marquer_alerte(cle)

        # Dividendes
        for item in DIVIDENDS_TICKERS:
            ticker = item["ticker"]
            nom    = item["nom"]
            evt_dt = self._fetch_dividende(ticker)
            if evt_dt is None:
                continue
            jours = (evt_dt - today).days
            if 0 <= jours <= HORIZON_JOURS:
                r = {
                    "ticker":         ticker,
                    "nom":            nom,
                    "type":           "dividende",
                    "date":           evt_dt.isoformat(),
                    "jours_restants": jours,
                }
                resultats.append(r)
                if 0 <= jours <= ALERTE_AVANT:
                    cle = self._cle_event(ticker, "dividende", evt_dt)
                    with self._lock:
                        if not self._deja_alerte(cle):
                            notifier.alerte(
                                f"💰 Dividende ex-date dans {jours}j — {nom} ({ticker})",
                                f"Date ex-dividende : <b>{evt_dt.strftime('%d/%m/%Y')}</b>",
                                niveau="dividende",
                            )
                            self._marquer_alerte(cle)

        resultats.sort(key=lambda x: x["date"])
        return resultats

    def prochains_evenements(self) -> list[dict[str, Any]]:
        """Retourne les événements des 30 prochains jours (pour affichage frontend)."""
        return self.verifier_evenements()


_instance: AgentCalendrier | None = None


def get_agent_calendrier() -> AgentCalendrier:
    global _instance
    if _instance is None:
        _instance = AgentCalendrier()
    return _instance

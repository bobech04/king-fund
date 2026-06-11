"""
Agent Alertes Prix — surveille 4 seuils d'entrée, alerte Telegram 1x/jour/ticker max.
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

# Dossier de persistance anti-spam
_ETAT_FILE = Path(__file__).resolve().parents[2] / "data" / "alertes_prix_etat.json"

SEUILS: list[dict[str, Any]] = [
    {"ticker": "VPK.AS", "nom": "Vopak",             "seuil": 44.0,  "devise": "EUR", "type": "SOUS"},
    {"ticker": "BIPC",   "nom": "Brookfield Infra",   "seuil": 35.0,  "devise": "USD", "type": "SOUS"},
    {"ticker": "DNB.OL", "nom": "DNB Bank",            "seuil": 280.0, "devise": "NOK", "type": "SOUS"},
    {"ticker": "TTE.PA", "nom": "TotalEnergies",       "seuil": -5.0,  "devise": "EUR", "type": "BAISSE_JOUR"},
]

_NOM_DEVISE = {"EUR": "€", "USD": "$", "NOK": "kr"}


def _safe(v, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        f = float(v)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


class AgentAlertesPrix:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._alertes_jour: dict[str, str] = {}  # {ticker: "YYYY-MM-DD"}
        self._charger_etat()

    # ── Persistance anti-spam ────────────────────────────────────────

    def _charger_etat(self) -> None:
        try:
            if _ETAT_FILE.exists():
                self._alertes_jour = json.loads(_ETAT_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[AlertesPrix] Chargement état: %s", e)
            self._alertes_jour = {}

    def _sauver_etat(self) -> None:
        try:
            _ETAT_FILE.parent.mkdir(parents=True, exist_ok=True)
            _ETAT_FILE.write_text(json.dumps(self._alertes_jour, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("[AlertesPrix] Sauvegarde état: %s", e)

    def _deja_alerte_aujourd_hui(self, ticker: str) -> bool:
        return self._alertes_jour.get(ticker) == date.today().isoformat()

    def _marquer_alerte(self, ticker: str) -> None:
        self._alertes_jour[ticker] = date.today().isoformat()
        self._sauver_etat()

    # ── Vérification seuils ─────────────────────────────────────────

    def verifier_seuils(self) -> list[dict[str, Any]]:
        """Vérifie chaque seuil, envoie alertes Telegram si déclenché. Retourne l'état complet."""
        from . import notifier
        resultats = []
        for s in SEUILS:
            ticker  = s["ticker"]
            nom     = s["nom"]
            seuil   = s["seuil"]
            devise  = s["devise"]
            symbole = _NOM_DEVISE.get(devise, devise)
            type_   = s["type"]
            try:
                info        = yf.Ticker(ticker).info or {}
                prix        = _safe(info.get("currentPrice")) or _safe(info.get("regularMarketPrice"))
                prev_close  = _safe(info.get("previousClose")) or _safe(info.get("regularMarketPreviousClose"))

                variation_pct: float | None = None
                if prix is not None and prev_close is not None and prev_close > 0:
                    variation_pct = (prix - prev_close) / prev_close * 100

                # Évaluation du seuil
                declenche = False
                if type_ == "SOUS" and prix is not None:
                    declenche = prix < seuil
                elif type_ == "BAISSE_JOUR" and variation_pct is not None:
                    declenche = variation_pct < seuil

                statut = "ALERTE" if declenche else "OK"
                derniere_alerte = self._alertes_jour.get(ticker)

                # Envoi Telegram anti-spam
                with self._lock:
                    if declenche and not self._deja_alerte_aujourd_hui(ticker):
                        if type_ == "SOUS":
                            corps = (
                                f"Prix actuel : <b>{prix:.2f}{symbole}</b> "
                                f"(seuil BUY : {seuil}{symbole})\n"
                                f"Variation : {variation_pct:+.2f}%" if variation_pct is not None
                                else f"Prix actuel : <b>{prix:.2f}{symbole}</b> (seuil : {seuil}{symbole})"
                            )
                            notifier.alerte(
                                f"BUY Signal — {nom} ({ticker})",
                                f"Prix actuel : <b>{prix:.2f}{symbole}</b> (seuil BUY : {seuil}{symbole})" +
                                (f"\nVariation : {variation_pct:+.2f}%" if variation_pct is not None else ""),
                                niveau="critique",
                            )
                        else:  # BAISSE_JOUR
                            notifier.alerte(
                                f"Recul journalier — {nom} ({ticker})",
                                f"Baisse : <b>{variation_pct:+.2f}%</b> (seuil : {seuil}%)\n"
                                f"Prix : {prix:.2f}{symbole} · Clôture préc. : {prev_close:.2f}{symbole}",
                                niveau="critique",
                            )
                        self._marquer_alerte(ticker)
                        derniere_alerte = date.today().isoformat()

                resultats.append({
                    "ticker":           ticker,
                    "nom":              nom,
                    "seuil":            seuil,
                    "devise":           devise,
                    "type":             type_,
                    "prix_actuel":      round(prix, 2) if prix is not None else None,
                    "variation_jour_pct": round(variation_pct, 2) if variation_pct is not None else None,
                    "statut":           statut,
                    "derniere_alerte":  derniere_alerte,
                    "timestamp":        datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                logger.warning("[AlertesPrix] %s erreur: %s", ticker, e)
                resultats.append({
                    "ticker":  ticker,
                    "nom":     nom,
                    "seuil":   seuil,
                    "devise":  devise,
                    "type":    type_,
                    "statut":  "ERREUR",
                    "erreur":  str(e),
                    "derniere_alerte": self._alertes_jour.get(ticker),
                })
        return resultats

    def etat(self) -> list[dict[str, Any]]:
        """Retourne l'état des seuils depuis le cache (sans appel YF). Pour affichage frontend."""
        resultats = []
        for s in SEUILS:
            resultats.append({
                "ticker":          s["ticker"],
                "nom":             s["nom"],
                "seuil":           s["seuil"],
                "devise":          s["devise"],
                "type":            s["type"],
                "derniere_alerte": self._alertes_jour.get(s["ticker"]),
            })
        return resultats


_instance: AgentAlertesPrix | None = None


def get_agent_alertes_prix() -> AgentAlertesPrix:
    global _instance
    if _instance is None:
        _instance = AgentAlertesPrix()
    return _instance

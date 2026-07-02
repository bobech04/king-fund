"""
Agent Alertes Prix — surveille seuils d'entrée, alerte Telegram 1x/jour/ticker max.
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
_ETAT_FILE    = Path(__file__).resolve().parents[2] / "data" / "alertes_prix_etat.json"
_SEUILS_ACHAT = Path(__file__).resolve().parents[3] / "data" / "seuils_achat.json"

SEUILS: list[dict[str, Any]] = [
    {"ticker": "VPK.AS", "nom": "Vopak",             "seuil": 44.0,  "devise": "EUR", "type": "SOUS"},
    {"ticker": "BIPC",   "nom": "Brookfield Infra",   "seuil": 35.0,  "devise": "USD", "type": "SOUS"},
    {"ticker": "DNB.OL", "nom": "DNB Bank",            "seuil": 280.0, "devise": "NOK", "type": "SOUS"},
    {"ticker": "TTE.PA", "nom": "TotalEnergies",       "seuil": -5.0,  "devise": "EUR", "type": "BAISSE_JOUR"},
]

_NOM_DEVISE = {"EUR": "€", "USD": "$", "NOK": "kr"}

# ── Seuils accélérés — régime CRISE_LIQUIDITE (Agent Flux Macro) ──────────
# Milieu de la fourchette 5-10% demandée (ex: Engie 27-28€ → 25-26€ pendant la crise).
_REDUCTION_CRISE_LIQUIDITE_PCT = 0.07

NOTE_CRISE_LIQUIDITE = (
    "⚠️ Contexte CRISE_LIQUIDITE actif — la baisse peut s'amplifier, "
    "patience recommandée avant d'acheter même si le seuil est atteint."
)


def _regime_crise_liquidite_forte() -> bool:
    """Interroge l'Agent Flux Macro (cache) — True si régime CRISE_LIQUIDITE confirmé confiance FORTE."""
    try:
        from divisions.research.agent_flux_macro import get_agent_flux_macro
        return bool(get_agent_flux_macro().regime_actuel().get("crise_liquidite_forte"))
    except Exception as e:
        logger.debug("[AlertesPrix] régime flux macro indisponible: %s", e)
        return False


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
        crise = _regime_crise_liquidite_forte()
        resultats = []
        for s in SEUILS:
            ticker  = s["ticker"]
            nom     = s["nom"]
            seuil   = s["seuil"]
            devise  = s["devise"]
            symbole = _NOM_DEVISE.get(devise, devise)
            type_   = s["type"]
            # Seuils accélérés : abaisse temporairement le seuil BUY pendant CRISE_LIQUIDITE
            seuil_effectif = (
                round(seuil * (1 - _REDUCTION_CRISE_LIQUIDITE_PCT), 2)
                if crise and type_ == "SOUS" else seuil
            )
            try:
                info        = yf.Ticker(ticker).info or {}
                prix        = _safe(info.get("currentPrice")) or _safe(info.get("regularMarketPrice"))
                prev_close  = _safe(info.get("previousClose")) or _safe(info.get("regularMarketPreviousClose"))

                variation_pct: float | None = None
                if prix is not None and prev_close is not None and prev_close > 0:
                    variation_pct = (prix - prev_close) / prev_close * 100

                # Évaluation du seuil (seuil_effectif = seuil normal hors CRISE_LIQUIDITE)
                declenche = False
                if type_ == "SOUS" and prix is not None:
                    declenche = prix < seuil_effectif
                elif type_ == "BAISSE_JOUR" and variation_pct is not None:
                    declenche = variation_pct < seuil_effectif

                statut = "ALERTE" if declenche else "OK"
                derniere_alerte = self._alertes_jour.get(ticker)

                # Envoi Telegram anti-spam
                with self._lock:
                    if declenche and not self._deja_alerte_aujourd_hui(ticker):
                        if type_ == "SOUS":
                            corps = (
                                f"Prix actuel : <b>{prix:.2f}{symbole}</b> "
                                f"(seuil BUY : {seuil_effectif}{symbole}"
                                + (f", normal {seuil}{symbole}" if crise else "") + ")"
                                + (f"\nVariation : {variation_pct:+.2f}%" if variation_pct is not None else "")
                                + (f"\n\n{NOTE_CRISE_LIQUIDITE}" if crise else "")
                            )
                            notifier.alerte(
                                f"BUY Signal — {nom} ({ticker})",
                                corps,
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
                    "seuil_effectif":   seuil_effectif,
                    "devise":           devise,
                    "type":             type_,
                    "prix_actuel":      round(prix, 2) if prix is not None else None,
                    "variation_jour_pct": round(variation_pct, 2) if variation_pct is not None else None,
                    "statut":           statut,
                    "regime_crise_liquidite": crise and type_ == "SOUS",
                    "note":             NOTE_CRISE_LIQUIDITE if (declenche and crise and type_ == "SOUS") else None,
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

    # ── Seuils d'achat watchlist (seuils_achat.json) ────────────────

    def verifier_seuils_watchlist(self) -> list[dict[str, Any]]:
        """Vérifie les seuils d'achat personnalisés de la watchlist.
        Envoie Telegram '🎯 SEUIL ATTEINT' si le prix est dans la zone d'achat.
        Anti-spam 1x/jour/ticker.
        """
        from . import notifier

        # Charge les seuils depuis le fichier
        try:
            if not _SEUILS_ACHAT.exists():
                return []
            seuils = json.loads(_SEUILS_ACHAT.read_text("utf-8"))
        except Exception as e:
            logger.warning("[AlertesPrix] Chargement seuils_achat.json: %s", e)
            return []

        resultats = []
        _NOM_DEV = {"EUR": "€", "USD": "$", "NOK": " NOK"}
        crise = _regime_crise_liquidite_forte()

        for s in seuils:
            ticker = s.get("ticker", "")
            nom    = s.get("nom", ticker)
            sh     = s.get("seuil_haut")
            sb     = s.get("seuil_bas")
            devise = s.get("devise", "")
            sym    = _NOM_DEV.get(devise, devise)
            key    = f"wl_{ticker}"  # clé anti-spam distincte des seuils classiques

            # Seuils accélérés : abaisse temporairement la zone d'achat pendant CRISE_LIQUIDITE
            if crise:
                sh_eff = round(sh * (1 - _REDUCTION_CRISE_LIQUIDITE_PCT), 2) if sh is not None else None
                sb_eff = round(sb * (1 - _REDUCTION_CRISE_LIQUIDITE_PCT), 2) if sb is not None else None
            else:
                sh_eff, sb_eff = sh, sb

            try:
                info = yf.Ticker(ticker).info or {}
                prix = _safe(info.get("currentPrice")) or _safe(info.get("regularMarketPrice"))
                if prix is None:
                    resultats.append({"ticker": ticker, "statut": "ERREUR", "erreur": "prix indisponible"})
                    continue

                # Détermination de la zone d'achat
                dans_zone = False
                if sb_eff is not None and sh_eff is not None:
                    dans_zone = sb_eff <= prix <= sh_eff
                    label = f"{sb_eff}–{sh_eff}{sym}"
                elif sh_eff is not None:
                    dans_zone = prix <= sh_eff
                    label = f"< {sh_eff}{sym}"
                else:
                    label = "—"

                statut = "SEUIL_ATTEINT" if dans_zone else "OK"

                with self._lock:
                    if dans_zone and self._alertes_jour.get(key) != date.today().isoformat():
                        corps = (
                            f"<b>{nom}</b> ({ticker}) à <b>{prix:.2f}{sym}</b>\n"
                            f"Zone d'achat : {label}"
                            + (f" (normal : {sb}–{sh}{sym})" if crise and sb is not None and sh is not None else "")
                            + (f"\n\n{NOTE_CRISE_LIQUIDITE}" if crise else "")
                        )
                        notifier.alerte(f"🎯 SEUIL ATTEINT : {ticker}", corps, niveau="critique")
                        self._alertes_jour[key] = date.today().isoformat()
                        self._sauver_etat()

                resultats.append({
                    "ticker":        ticker,
                    "nom":           nom,
                    "prix_actuel":   round(prix, 2),
                    "seuil_label":   label,
                    "dans_zone":     dans_zone,
                    "statut":        statut,
                    "regime_crise_liquidite": crise,
                    "note":          NOTE_CRISE_LIQUIDITE if (dans_zone and crise) else None,
                    "derniere_alerte": self._alertes_jour.get(key),
                })
            except Exception as e:
                logger.warning("[AlertesPrix] seuil_watchlist %s: %s", ticker, e)
                resultats.append({"ticker": ticker, "statut": "ERREUR", "erreur": str(e)})

        return resultats


_instance: AgentAlertesPrix | None = None


def get_agent_alertes_prix() -> AgentAlertesPrix:
    global _instance
    if _instance is None:
        _instance = AgentAlertesPrix()
    return _instance

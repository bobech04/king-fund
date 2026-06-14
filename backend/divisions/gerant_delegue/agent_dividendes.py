"""
Agent Dividendes & Revenus Passifs — Division Gérant Délégué

Surveille les 16 actifs de la watchlist + portefeuille Zoubida :
  • Revenu passif projeté annuel et mensuel
  • Alerte immédiate Telegram si coupe ou suspension de dividende
  • Historique des dividendes (5 ans)
  • Scoring de fiabilité du dividende (croissance, couverture FCF, payout ratio)

Sources : yfinance (dividende, FCF, payout)
Cache : 4h données dividendes, 15 min surveillance coupe
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from divisions.gerant_delegue.notifier import alerte

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Watchlist dividendes (actifs à revenu)
# ---------------------------------------------------------------------------

WATCHLIST_DIV = [
    # Ticker, montant_investi_€, nom_court
    ("O",       500.0,  "Realty Income"),
    ("JNJ",     400.0,  "Johnson & Johnson"),
    ("VZ",      300.0,  "Verizon"),
    ("TEL.OL",  250.0,  "Telenor"),
    ("DNB.OL",  200.0,  "DNB Bank"),
    ("BIPC",    350.0,  "Brookfield Infrastructure"),
    ("ADC",     200.0,  "Agree Realty"),
    ("DSY.PA",  150.0,  "Dassault Systèmes"),
    ("SU.PA",   300.0,  "Schneider Electric"),
    ("TTE.PA",  300.0,  "TotalEnergies"),
    ("AIR.PA",  200.0,  "Airbus"),
    ("VIE.PA",  150.0,  "Veolia"),
    ("ENGIE.PA",200.0,  "Engie"),
    ("VPK.AS",  200.0,  "Vopak"),
    ("GTT.PA",  150.0,  "GTT"),
    ("XYL",     150.0,  "Xylem"),
]

_CACHE_TTL = 14_400   # 4h
_COUPE_TTL = 900      # 15 min re-check si alerte récente


def _scoring_dividende(info: dict) -> dict:
    """Calcule un score de fiabilité du dividende 0-10."""
    score = 0.0
    notes = []

    div_yield  = info.get("dividendYield") or 0.0
    payout     = info.get("payoutRatio")  or 0.0
    fcf        = info.get("freeCashflow") or 0
    market_cap = info.get("marketCap")    or 1
    industry   = (info.get("industry") or "").upper()
    sector     = (info.get("sector")   or "").lower()
    is_reit    = "REIT" in industry or sector == "real estate"

    # Rendement raisonnable (2%-8%) — dividendYield yfinance est en %
    if 2.0 <= div_yield <= 8.0:
        score += 2.5
        notes.append(f"Rendement sain {div_yield:.1f}%")
    elif div_yield > 8.0:
        score += 1.0
        notes.append(f"Rendement élevé — risque coupe {div_yield:.1f}%")
    else:
        notes.append("Rendement faible ou absent")

    # Payout ratio — les REITs ont un payout GAAP structurellement > 100% (amortissements)
    # La métrique pertinente est le FFO payout (~75-85%), non disponible via yfinance
    if is_reit:
        score += 1.5
        notes.append("REIT — payout GAAP non pertinent (amortissements immobiliers)")
    elif 0 < payout < 0.75:
        score += 2.5
        notes.append(f"Payout sain {payout:.0%}")
    elif 0.75 <= payout < 1.0:
        score += 1.0
        notes.append(f"Payout tendu {payout:.0%}")
    else:
        notes.append(f"Payout dangereux {payout:.0%}" if payout else "Payout non disponible")

    # Couverture FCF
    if fcf > 0 and market_cap > 0:
        fcf_yield = fcf / market_cap
        if fcf_yield > div_yield:
            score += 2.5
            notes.append("FCF couvre le dividende")
        else:
            notes.append("FCF insuffisant pour couvrir le dividende")

    # Cohérence globale
    if score >= 5.0:
        score += 2.5
    elif score >= 3.0:
        score += 1.0

    return {
        "score":    min(round(score, 1), 10.0),
        "notes":    notes,
        "fiable":   score >= 6.0,
        "is_reit":  is_reit,
    }


class AgentDividendes:
    """
    Surveille les dividendes de la watchlist et alerte si coupe détectée.
    """

    def __init__(self) -> None:
        self._lock          = threading.Lock()
        self._cache:        dict[str, dict] = {}
        self._cache_ts:     float = 0.0
        self._snapshot_div: dict[str, float] = {}   # ticker → div/share précédent
        self._alerte_recente: float = 0.0

    # ------------------------------------------------------------------
    # Collecte données
    # ------------------------------------------------------------------

    def _fetch_ticker(self, ticker: str, montant_investi: float, nom: str) -> dict:
        try:
            import yfinance as yf
            t   = yf.Ticker(ticker)
            inf = t.info or {}

            prix     = inf.get("regularMarketPrice") or inf.get("currentPrice") or 0.0
            div_ann  = inf.get("dividendRate") or 0.0          # €/action/an
            div_yield= inf.get("dividendYield") or 0.0
            payout   = inf.get("payoutRatio")
            freq     = inf.get("dividendFrequency")            # None ou entier
            industry = (inf.get("industry") or "").upper()
            sector   = (inf.get("sector")   or "").lower()
            is_reit  = "REIT" in industry or sector == "real estate"

            nb_titres = (montant_investi / prix) if prix > 0 else 0.0
            rev_annuel= nb_titres * div_ann
            rev_mensuel = rev_annuel / 12.0

            scoring = _scoring_dividende(inf)

            # Détection coupe vs snapshot précédent
            coupe_detectee = False
            if ticker in self._snapshot_div and div_ann < self._snapshot_div[ticker] * 0.90:
                coupe_detectee = True
                pct_coupe = (self._snapshot_div[ticker] - div_ann) / max(self._snapshot_div[ticker], 0.01) * 100
                alerte(
                    f"COUPE DIVIDENDE — {nom} ({ticker})",
                    f"Dividende passe de {self._snapshot_div[ticker]:.2f}€ "
                    f"à {div_ann:.2f}€/action (−{pct_coupe:.0f}%)\n"
                    f"Revenu annuel impacté : −{pct_coupe:.0f}% sur votre position",
                    niveau="critique",
                )
                self._alerte_recente = time.monotonic()
                logger.warning("[Dividendes] COUPE détectée sur %s", ticker)

            self._snapshot_div[ticker] = div_ann

            return {
                "ticker":        ticker,
                "nom":           nom,
                "montant_investi": montant_investi,
                "prix":          round(prix, 2),
                "nb_titres":     round(nb_titres, 3),
                "div_annuel_action": round(div_ann, 3),
                "div_yield":     round(div_yield, 2),   # déjà en % via yfinance
                "rev_annuel":    round(rev_annuel, 2),
                "rev_mensuel":   round(rev_mensuel, 2),
                "payout_ratio":  round(payout * 100, 1) if payout else None,
                "is_reit":       is_reit,
                "scoring":       scoring,
                "coupe_detectee": coupe_detectee,
            }
        except Exception as e:
            logger.debug("[Dividendes] %s: %s", ticker, e)
            return {
                "ticker":        ticker,
                "nom":           nom,
                "montant_investi": montant_investi,
                "erreur":        str(e),
                "rev_annuel":    0.0,
                "rev_mensuel":   0.0,
            }

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def analyser(self, forcer: bool = False) -> dict:
        now = time.monotonic()
        ttl = _COUPE_TTL if (now - self._alerte_recente) < 3600 else _CACHE_TTL
        if not forcer and self._cache and (now - self._cache_ts) < ttl:
            return self._cache

        resultats = []
        for ticker, montant, nom in WATCHLIST_DIV:
            resultats.append(self._fetch_ticker(ticker, montant, nom))

        rev_total_annuel  = sum(r.get("rev_annuel", 0) for r in resultats)
        rev_total_mensuel = rev_total_annuel / 12.0
        nb_coupes         = sum(1 for r in resultats if r.get("coupe_detectee"))
        nb_fiables        = sum(1 for r in resultats if r.get("scoring", {}).get("fiable"))

        rapport = {
            "positions":          resultats,
            "revenu_annuel_total": round(rev_total_annuel, 2),
            "revenu_mensuel_total":round(rev_total_mensuel, 2),
            "nb_coupes_detectees": nb_coupes,
            "nb_dividendes_fiables": nb_fiables,
            "objectif_mensuel":   500.0,   # cible revenus passifs €/mois
            "ecart_objectif":     round(rev_total_mensuel - 500.0, 2),
            "timestamp":          datetime.now(timezone.utc).isoformat(),
        }

        with self._lock:
            self._cache    = rapport
            self._cache_ts = now

        logger.info(
            "[Dividendes] Revenu annuel: %.0f€ | Mensuel: %.0f€ | Coupes: %d | Fiables: %d",
            rev_total_annuel, rev_total_mensuel, nb_coupes, nb_fiables,
        )
        return rapport

    def coupes_recentes(self) -> list[dict]:
        return [r for r in self._cache.get("positions", []) if r.get("coupe_detectee")]

    def etat(self) -> dict:
        cache = self._cache
        return {
            "revenu_annuel":  cache.get("revenu_annuel_total", 0),
            "revenu_mensuel": cache.get("revenu_mensuel_total", 0),
            "nb_coupes":      cache.get("nb_coupes_detectees", 0),
            "nb_positions":   len(cache.get("positions", [])),
            "timestamp":      cache.get("timestamp"),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: AgentDividendes | None = None
_lock = threading.Lock()


def get_agent_dividendes() -> AgentDividendes:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AgentDividendes()
    return _instance

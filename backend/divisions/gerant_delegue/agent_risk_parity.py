"""
Agent Risk Parity — Division Gérant Délégué
Méthode Bridgewater / Ray Dalio — "All Weather"

Principe : chaque classe d'actif contribue ÉGALEMENT au risque total du portefeuille.
Contribution risque = (poids × volatilité) / volatilité_portefeuille

Classes d'actifs surveillées :
  ACTIONS_US     — SPY  (proxy S&P 500)
  ACTIONS_EU     — EXW1.DE (proxy Euro Stoxx)
  OBLIGATIONS_LT — TLT  (Treasuries 20+)
  OBLIGATIONS_IT — IEF  (Treasuries 7-10)
  OR             — GLD
  CRYPTO         — BTC-USD
  CASH           — allocation résiduelle

Seuils :
  • Contribution risque hors cible > ±10pp → alerte WARNING
  • Contribution risque hors cible > ±20pp → alerte CRITIQUE + suggestion rééquilibrage
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from divisions.gerant_delegue.notifier import alerte

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration classes d'actifs
# ---------------------------------------------------------------------------

CLASSES = [
    # (label, ticker_proxy, poids_actuel_%, poids_cible_%)
    ("ACTIONS_US",      "SPY",      25.0, 18.0),
    ("ACTIONS_EU",      "EXW1.DE",  15.0, 12.0),
    ("OBLIGATIONS_LT",  "TLT",      20.0, 25.0),
    ("OBLIGATIONS_IT",  "IEF",      15.0, 20.0),
    ("OR",              "GLD",      15.0, 15.0),
    ("CRYPTO",          "BTC-USD",   5.0,  5.0),
    ("CASH",            None,        5.0,  5.0),
]

_LOOKBACK_DAYS  = 60      # volatilité rolling 60 jours
_CACHE_TTL      = 7200    # 2h
_SEUIL_WARNING  = 10.0    # pp écart contribution risque
_SEUIL_CRITIQUE = 20.0    # pp écart → alerte critique


def _vol_annualisee(returns: "np.ndarray") -> float:
    if len(returns) < 5:
        return 0.20
    return float(np.std(returns, ddof=1) * np.sqrt(252))


class AgentRiskParity:
    """
    Calcule la contribution au risque par classe d'actif
    et suggère un rééquilibrage selon la méthode Risk Parity de Dalio.
    """

    def __init__(self) -> None:
        self._lock       = threading.Lock()
        self._cache:     dict = {}
        self._cache_ts:  float = 0.0

    # ------------------------------------------------------------------
    # Données de marché
    # ------------------------------------------------------------------

    def _fetch_vols(self) -> dict[str, float]:
        vols: dict[str, float] = {}
        tickers = [c[1] for c in CLASSES if c[1] is not None]
        if not tickers:
            return vols
        try:
            import yfinance as yf
            data = yf.download(
                " ".join(tickers),
                period=f"{_LOOKBACK_DAYS + 5}d",
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            closes = data["Close"] if "Close" in data.columns else data
            for ticker in tickers:
                try:
                    col = closes[ticker] if ticker in closes.columns else closes
                    ret = col.pct_change().dropna().values[-_LOOKBACK_DAYS:]
                    vols[ticker] = _vol_annualisee(ret)
                except Exception:
                    vols[ticker] = 0.20
        except Exception as e:
            logger.debug("[RiskParity] Download: %s", e)
            for ticker in tickers:
                vols[ticker] = 0.20
        return vols

    # ------------------------------------------------------------------
    # Calcul Risk Parity
    # ------------------------------------------------------------------

    def analyser(self, forcer: bool = False) -> dict:
        now = time.monotonic()
        if not forcer and self._cache and (now - self._cache_ts) < _CACHE_TTL:
            return self._cache

        vols = self._fetch_vols()
        total_poids = sum(c[2] for c in CLASSES)

        resultats = []
        risque_contributions = []

        for label, ticker, poids_actuel, poids_cible in CLASSES:
            vol = vols.get(ticker, 0.05) if ticker else 0.01
            contribution_brute = (poids_actuel / 100.0) * vol
            risque_contributions.append(contribution_brute)

        vol_portefeuille = sum(risque_contributions)
        if vol_portefeuille <= 0:
            vol_portefeuille = 0.10

        # Poids Risk Parity cibles (contribution égale)
        n_classes = len(CLASSES)
        contribution_cible_pct = 100.0 / n_classes

        alertes_generees = []
        for i, (label, ticker, poids_actuel, poids_dalio) in enumerate(CLASSES):
            vol = vols.get(ticker, 0.05) if ticker else 0.01
            contribution_brute = risque_contributions[i]
            contribution_pct   = (contribution_brute / vol_portefeuille) * 100.0

            ecart_vs_egalite  = contribution_pct - contribution_cible_pct
            ecart_vs_dalio    = poids_actuel - poids_dalio

            statut = "OK"
            if abs(ecart_vs_egalite) >= _SEUIL_CRITIQUE:
                statut = "CRITIQUE"
            elif abs(ecart_vs_egalite) >= _SEUIL_WARNING:
                statut = "WARNING"

            if statut == "CRITIQUE" and label not in [a["classe"] for a in alertes_generees]:
                alertes_generees.append({"classe": label, "ecart": ecart_vs_egalite, "statut": statut})

            # Poids Risk Parity calculé (contribution × vol_portefeuille / vol_classe)
            poids_rp = (contribution_cible_pct / 100.0 * vol_portefeuille / max(vol, 0.001)) * 100.0
            poids_rp = min(max(round(poids_rp, 1), 0.0), 50.0)

            resultats.append({
                "classe":              label,
                "ticker_proxy":        ticker or "CASH",
                "poids_actuel_pct":    round(poids_actuel, 1),
                "poids_cible_dalio":   round(poids_dalio, 1),
                "poids_risk_parity":   round(poids_rp, 1),
                "volatilite_annuelle": round(vol * 100, 1),
                "contribution_risque_pct": round(contribution_pct, 1),
                "ecart_vs_egalite":    round(ecart_vs_egalite, 1),
                "statut":              statut,
            })

        # Envoi alertes Telegram
        for a in alertes_generees:
            signe = "surpondérée" if a["ecart"] > 0 else "sous-pondérée"
            alerte(
                f"Risk Parity — déséquilibre {a['classe']}",
                f"Classe {a['classe']} {signe} en risque.\n"
                f"Contribution actuelle : {contribution_cible_pct + a['ecart']:.1f}% "
                f"(cible: {contribution_cible_pct:.1f}%)\n"
                f"Action : rééquilibrer vers cible Risk Parity.",
                niveau="critique" if a["statut"] == "CRITIQUE" else "warning",
            )

        rebalancement = self._calculer_rebalancement(resultats)

        rapport = {
            "classes":               resultats,
            "vol_portefeuille_pct":  round(vol_portefeuille * 100, 1),
            "contribution_cible_pct": round(contribution_cible_pct, 1),
            "nb_desequilibres":      sum(1 for r in resultats if r["statut"] != "OK"),
            "rebalancement":         rebalancement,
            "methode":               "Risk Parity Dalio — All Weather",
            "timestamp":             datetime.now(timezone.utc).isoformat(),
        }

        with self._lock:
            self._cache    = rapport
            self._cache_ts = now

        logger.info(
            "[RiskParity] Vol port: %.1f%% | Déséquilibres: %d",
            vol_portefeuille * 100, rapport["nb_desequilibres"],
        )
        return rapport

    def _calculer_rebalancement(self, resultats: list[dict]) -> list[dict]:
        """Retourne les mouvements suggérés pour atteindre le Risk Parity."""
        mouvements = []
        for r in resultats:
            delta = r["poids_risk_parity"] - r["poids_actuel_pct"]
            if abs(delta) >= 2.0:
                mouvements.append({
                    "classe":  r["classe"],
                    "ticker":  r["ticker_proxy"],
                    "action":  "AUGMENTER" if delta > 0 else "RÉDUIRE",
                    "delta_pct": round(delta, 1),
                })
        mouvements.sort(key=lambda x: abs(x["delta_pct"]), reverse=True)
        return mouvements

    def etat(self) -> dict:
        cache = self._cache
        return {
            "vol_portefeuille": cache.get("vol_portefeuille_pct"),
            "nb_desequilibres": cache.get("nb_desequilibres", 0),
            "rebalancement":    cache.get("rebalancement", []),
            "timestamp":        cache.get("timestamp"),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: AgentRiskParity | None = None
_lock = threading.Lock()


def get_agent_risk_parity() -> AgentRiskParity:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AgentRiskParity()
    return _instance

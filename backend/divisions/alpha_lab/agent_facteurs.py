"""
Alpha Lab — Agent Facteurs Académiques
Implémente les 4 facteurs classiques pour scorer chaque actif de la watchlist :
  • Value      : P/B + P/E inversés (moins cher → score élevé)
  • Momentum   : rendement 12-1 mois (skip last month)
  • Quality    : ROE + ratio dette/capitaux propres
  • LowVol     : volatilité annualisée 252j inversée
Score composite 0-100 + rang cross-sectionnel.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

WATCHLIST_TICKERS: list[str] = [
    "VPK.AS", "GTT.PA", "O",    "JNJ",    "VZ",
    "TEL.OL", "DNB.OL", "BIPC", "ADC",    "DSY.PA",
    "SU.PA",  "TTE.PA", "AIR.PA",
]

# Poids des facteurs dans le score composite
WEIGHTS = {
    "value":    0.25,
    "momentum": 0.25,
    "quality":  0.25,
    "lowvol":   0.25,
}

_singleton: Optional["AgentFacteurs"] = None
_singleton_lock = threading.Lock()


def get_agent_facteurs() -> "AgentFacteurs":
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = AgentFacteurs()
    return _singleton


def _safe_float(v) -> Optional[float]:
    try:
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return None


class AgentFacteurs:
    CACHE_TTL = 3_600  # 1 heure

    def __init__(self):
        self._cache: Optional[dict] = None
        self._cache_ts: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Interface publique
    # ------------------------------------------------------------------

    def scorer_watchlist(self, force: bool = False) -> dict:
        """
        Calcule les scores factoriels pour tous les actifs de la watchlist.
        Retourne dict avec clés : ts, duree_s, actifs (liste triée par composite desc).
        """
        with self._lock:
            if not force and self._cache and (time.time() - self._cache_ts) < self.CACHE_TTL:
                return self._cache

        t0 = time.time()
        logger.info("Alpha Lab [Facteurs] calcul scores watchlist…")

        resultats: list[dict] = []
        for ticker in WATCHLIST_TICKERS:
            try:
                scores = self._scorer_ticker(ticker)
                resultats.append(scores)
                logger.debug("Alpha Lab [Facteurs] %s → composite=%.1f", ticker, scores["composite"])
            except Exception as exc:
                logger.warning("Alpha Lab [Facteurs] %s échec: %s", ticker, exc)
                resultats.append({
                    "ticker":    ticker,
                    "erreur":    str(exc),
                    "scores":    {"value": 50, "momentum": 50, "quality": 50, "lowvol": 50},
                    "details":   {},
                    "composite": 50.0,
                })

        resultats = self._ajouter_rangs(resultats)
        resultats.sort(key=lambda x: x.get("composite", 0), reverse=True)

        rapport = {
            "ts":      datetime.utcnow().isoformat(),
            "duree_s": round(time.time() - t0, 1),
            "actifs":  resultats,
        }

        with self._lock:
            self._cache    = rapport
            self._cache_ts = time.time()

        logger.info("Alpha Lab [Facteurs] terminé en %.1fs — %d actifs scorés", time.time() - t0, len(resultats))
        return rapport

    # ------------------------------------------------------------------
    # Score par ticker
    # ------------------------------------------------------------------

    def _scorer_ticker(self, ticker: str) -> dict:
        t = yf.Ticker(ticker)
        info = t.fast_info.__dict__ if hasattr(t, "fast_info") else {}
        full_info = {}
        try:
            full_info = t.info or {}
        except Exception:
            pass

        # ── Données de prix ─────────────────────────────────────────────────
        hist_mo = t.history(period="14mo", interval="1mo")
        hist_dy = t.history(period="1y",   interval="1d")

        # Momentum 12-1 (return sur 12 mois en sautant le dernier mois)
        if len(hist_mo) >= 13:
            ret_12_1 = float(hist_mo["Close"].iloc[-2] / hist_mo["Close"].iloc[0] - 1)
        elif len(hist_mo) >= 2:
            ret_12_1 = float(hist_mo["Close"].iloc[-1] / hist_mo["Close"].iloc[0] - 1)
        else:
            ret_12_1 = 0.0

        # Volatilité annualisée 252j
        if len(hist_dy) >= 21:
            dr = hist_dy["Close"].pct_change().dropna()
            vol_252 = float(dr.std() * np.sqrt(252))
        else:
            vol_252 = 0.20  # défaut 20 %

        # ── Fondamentaux ────────────────────────────────────────────────────
        pb      = _safe_float(full_info.get("priceToBook"))
        pe      = _safe_float(full_info.get("trailingPE") or full_info.get("forwardPE"))
        roe     = _safe_float(full_info.get("returnOnEquity"))
        debt_eq = _safe_float(full_info.get("debtToEquity"))

        # ── Score Value (0-100) ─────────────────────────────────────────────
        # P/B : < 1 → 100, > 5 → 0
        score_pb = max(0.0, min(100.0, (5.0 - (pb or 3.0)) / 4.0 * 100.0)) if pb else 50.0
        # P/E : < 8 → 100, > 40 → 0
        score_pe = max(0.0, min(100.0, (40.0 - (pe or 20.0)) / 32.0 * 100.0)) if pe else 50.0
        score_value = (score_pb + score_pe) / 2.0

        # ── Score Momentum (0-100) ──────────────────────────────────────────
        # −30 % → 0, +30 % → 100
        score_momentum = max(0.0, min(100.0, (ret_12_1 + 0.30) / 0.60 * 100.0))

        # ── Score Quality (0-100) ───────────────────────────────────────────
        # ROE : < 0 → 0, > 20 % → 100
        score_roe  = max(0.0, min(100.0, (roe or 0.10) / 0.20 * 100.0)) if roe is not None else 50.0
        # Debt/Equity : < 30 → 100, > 200 → 0
        score_debt = max(0.0, min(100.0, (200.0 - (debt_eq or 80.0)) / 170.0 * 100.0)) if debt_eq is not None else 50.0
        score_quality = (score_roe + score_debt) / 2.0

        # ── Score LowVol (0-100) ────────────────────────────────────────────
        # vol < 10 % → 100, vol > 50 % → 0
        score_lowvol = max(0.0, min(100.0, (0.50 - vol_252) / 0.40 * 100.0))

        # ── Composite ───────────────────────────────────────────────────────
        composite = (
            WEIGHTS["value"]    * score_value
            + WEIGHTS["momentum"] * score_momentum
            + WEIGHTS["quality"]  * score_quality
            + WEIGHTS["lowvol"]   * score_lowvol
        )

        return {
            "ticker": ticker,
            "scores": {
                "value":    round(score_value,    1),
                "momentum": round(score_momentum, 1),
                "quality":  round(score_quality,  1),
                "lowvol":   round(score_lowvol,   1),
            },
            "details": {
                "pb":       round(pb, 2)      if pb is not None   else None,
                "pe":       round(pe, 1)      if pe is not None   else None,
                "mom_12_1": round(ret_12_1 * 100.0, 1),
                "vol_252":  round(vol_252  * 100.0, 1),
                "roe":      round(roe * 100.0, 1) if roe is not None else None,
                "debt_eq":  round(debt_eq, 1)     if debt_eq is not None else None,
            },
            "composite": round(composite, 1),
        }

    # ------------------------------------------------------------------
    # Rang cross-sectionnel
    # ------------------------------------------------------------------

    @staticmethod
    def _ajouter_rangs(actifs: list[dict]) -> list[dict]:
        """Ajoute composite_rank 0-100 basé sur le rang relatif cross-sectionnel."""
        n = len(actifs)
        if n < 2:
            for a in actifs:
                a["composite_rank"] = 50.0
            return actifs

        composites = np.array([a.get("composite", 50.0) for a in actifs], dtype=float)
        sorted_idx = np.argsort(composites)
        ranks = np.empty(n, dtype=float)
        for rank, idx in enumerate(sorted_idx):
            ranks[idx] = rank / (n - 1) * 100.0

        for i, a in enumerate(actifs):
            a["composite_rank"] = round(float(ranks[i]), 1)

        return actifs

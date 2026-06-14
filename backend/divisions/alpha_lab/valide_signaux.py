"""
Alpha Lab — Validateur de Signaux
Teste le signal Bertez et les archétypes des 30 traders sur données historiques longues.
Verdict par signal : VALIDE / BRUIT / OVERFITTE.
Rapport mensuel envoyé à AGD-01 via Telegram.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from .data_loader import load_french_factors, load_shiller_sp500
from .backtester import backtest, BacktestResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Crises historiques testées
# ---------------------------------------------------------------------------

CRISES: dict[str, tuple[str, str]] = {
    "1973_oil_shock":    ("1973-10-01", "1974-09-30"),
    "1979_iran_volcker": ("1979-06-01", "1980-07-31"),
    "2000_dotcom":       ("2000-03-01", "2002-10-31"),
    "2008_gfc":          ("2007-10-01", "2009-03-31"),
    "2020_covid":        ("2020-02-01", "2020-04-30"),
    "2022_tightening":   ("2022-01-01", "2022-12-31"),
}

# ---------------------------------------------------------------------------
# Archétypes des 30 traders (groupés par division)
# ---------------------------------------------------------------------------

TRADER_ARCHETYPES: dict[str, list[int]] = {
    "Momentum":     [2, 6, 10, 14, 22],                       # Expert Tech
    "MeanRev":      [1, 5, 8, 13, 16, 20],                    # Investissement
    "Macro":        [4, 7, 17, 23, 29],                        # Banque Centrale
    "TrendFollow":  [3, 11, 15, 21, 26],                       # Crypto
    "Fundamental":  [9, 12, 18, 24, 25, 27, 28, 30],          # Commerce + Value
}

# ---------------------------------------------------------------------------
# Cache global
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_cache: Optional[dict] = None
_cache_ts: float = 0.0
CACHE_TTL = 6 * 3_600  # 6 heures


# ---------------------------------------------------------------------------
# Construction des signaux
# ---------------------------------------------------------------------------

def _mkt_returns(french: dict) -> Optional[pd.Series]:
    """Rendement marché mensuel = Mkt-RF + RF (facteurs French)."""
    ff3 = french.get("ff3")
    if ff3 is None:
        return None
    mkt_rf = ff3.get("Mkt-RF") if "Mkt-RF" in ff3.columns else ff3.iloc[:, 0]
    rf     = ff3["RF"] if "RF" in ff3.columns else pd.Series(0.0, index=ff3.index)
    return (mkt_rf + rf).rename("mkt")


def _bertez_signal(french: dict, shiller: Optional[pd.DataFrame]) -> pd.Series:
    """
    Proxy du signal Bertez sur données historiques longues.
    Logique : quand HML (value spread) < 0 ET CAPE > 25 → régime défensif (−1)
    → le signal correspond à l'aversion aux actifs risqués chère à Bruno Bertez
      (économie-énergie sous tension, prime de risque comprimée).
    Signal = −1 (défensif) ou +1 (offensif).
    """
    ff3 = french.get("ff3")
    if ff3 is None or "HML" not in ff3.columns:
        return pd.Series(dtype=float)

    hml = ff3["HML"]
    signal = pd.Series(1.0, index=hml.index)

    if shiller is not None and "cape" in shiller.columns:
        cape = shiller["cape"].dropna()
        cape.index = pd.to_datetime(cape.index)
        cape = cape[~cape.index.duplicated(keep="last")]
        cape = cape.reindex(hml.index, method="ffill")
        # Défensif si spreads value négatifs + marchés chers
        defensif = (hml < 0) & (cape > 25)
        signal[defensif] = -1.0
    else:
        signal[hml < 0] = -1.0

    return signal.rename("Bertez_Energy")


def _archetype_signal(french: dict, archetype: str) -> pd.Series:
    """
    Signal académique simple pour chaque archétype de trader.
    Utilise les facteurs French comme proxy des stratégies réelles.
    """
    ff3 = french.get("ff3")
    ff5 = french.get("ff5")
    mom = french.get("mom")

    if ff3 is None or "Mkt-RF" not in ff3.columns:
        return pd.Series(dtype=float)

    mkt = ff3["Mkt-RF"]

    if archetype == "Momentum" and mom is not None:
        # UMD (Up Minus Down) : signal positif si momentum positif
        umd_col = next((c for c in mom.columns if any(k in c for k in ("Mom", "UMD", "WML"))), None)
        if umd_col:
            umd = mom[umd_col]
            sig = np.sign(umd.rolling(3).mean())
            return pd.Series(sig, index=umd.index).rename(archetype)

    if archetype == "MeanRev":
        # Contre-tendance : long si marché a chuté sur 3 mois
        r3 = mkt.rolling(3).sum()
        sig = np.where(r3 < -0.06, 1.0, np.where(r3 > 0.12, -0.50, 0.0))
        return pd.Series(sig, index=mkt.index).rename(archetype)

    if archetype == "Macro" and ff5 is not None:
        # RMW (Robust Minus Weak profitability) comme proxy qualité macro
        rmw_col = next((c for c in ff5.columns if "RMW" in c), None)
        if rmw_col:
            rmw = ff5[rmw_col]
            sig = np.sign(rmw.rolling(6).mean())
            return pd.Series(sig, index=rmw.index).rename(archetype)

    if archetype == "TrendFollow":
        # Trend-following classique : long si prix > MA 12 mois
        ma12 = mkt.rolling(12).mean()
        sig  = np.where(mkt > ma12, 1.0, 0.0)
        return pd.Series(sig, index=mkt.index).rename(archetype)

    if archetype == "Fundamental" and "HML" in ff3.columns:
        # Value : long si HML positif (value surperforme growth)
        hml = ff3["HML"]
        sig = np.sign(hml.rolling(3).mean())
        return pd.Series(sig, index=hml.index).rename(archetype)

    # Fallback : toujours long marché
    return pd.Series(1.0, index=mkt.index).rename(archetype)


# ---------------------------------------------------------------------------
# Performance par crise
# ---------------------------------------------------------------------------

def _crises_performance(signal: pd.Series, returns: pd.Series) -> dict:
    """
    Calcule rendement total + Sharpe de la stratégie sur chaque crise historique.
    """
    sig_shifted = signal.shift(1).fillna(0).clip(-1, 1)
    strat       = sig_shifted * returns
    perf: dict[str, dict] = {}

    for name, (start, end) in CRISES.items():
        mask = (returns.index >= start) & (returns.index <= end)
        if mask.sum() < 2:
            continue
        r_crise = strat[mask]
        std = r_crise.std()
        perf[name] = {
            "rendement_total": round(float(r_crise.sum()), 4),
            "n_mois":          int(mask.sum()),
            "sharpe":          round(float(r_crise.mean() / (std + 1e-9) * (12 ** 0.5)), 2),
            "periode":         f"{start} → {end}",
        }
    return perf


# ---------------------------------------------------------------------------
# Rapport complet
# ---------------------------------------------------------------------------

def generer_rapport(force: bool = False) -> dict:
    """
    Lance tous les backtests et retourne le rapport complet (cache 6 h).
    Incluant : signal Bertez, 5 archétypes, performance sur 6 crises.
    """
    global _cache, _cache_ts

    with _LOCK:
        if not force and _cache is not None and (time.time() - _cache_ts) < CACHE_TTL:
            logger.debug("Alpha Lab [ValidSignaux] cache hit")
            return _cache

    t0 = time.time()
    logger.info("Alpha Lab [ValidSignaux] génération rapport complet…")

    # Chargement données
    try:
        french  = load_french_factors()
        shiller = load_shiller_sp500()
    except Exception as exc:
        err = {"erreur": str(exc), "ts": datetime.utcnow().isoformat()}
        logger.error("Alpha Lab [DataLoader] %s", exc)
        return err

    mkt = _mkt_returns(french)
    if mkt is None:
        return {"erreur": "Facteurs Mkt-RF manquants", "ts": datetime.utcnow().isoformat()}

    signaux: dict[str, BacktestResult] = {}

    # ── Signal Bertez ────────────────────────────────────────────────────────
    bertez = _bertez_signal(french, shiller)
    if not bertez.empty:
        common = bertez.index.intersection(mkt.index)
        if len(common) >= 60:
            res = backtest(bertez.loc[common], mkt.loc[common], "Bertez_Energy")
            res.crises_perf = _crises_performance(bertez.loc[common], mkt.loc[common])
            signaux["Bertez_Energy"] = res
            logger.info("Alpha Lab [Bertez] → %s | Sharpe OOS=%.2f | t=%.2f",
                        res.verdict, res.sharpe_oos, res.t_stat)

    # ── Archétypes 30 traders ────────────────────────────────────────────────
    for archetype in TRADER_ARCHETYPES:
        sig = _archetype_signal(french, archetype)
        if sig.empty:
            continue
        common = sig.index.intersection(mkt.index)
        if len(common) < 60:
            continue
        res = backtest(sig.loc[common], mkt.loc[common], archetype)
        res.crises_perf = _crises_performance(sig.loc[common], mkt.loc[common])
        signaux[archetype] = res
        logger.info("Alpha Lab [%s] → %s | Sharpe OOS=%.2f | t=%.2f",
                    archetype, res.verdict, res.sharpe_oos, res.t_stat)

    # ── Résumé ───────────────────────────────────────────────────────────────
    valides  = [k for k, v in signaux.items() if v.verdict == "VALIDE"]
    bruits   = [k for k, v in signaux.items() if v.verdict == "BRUIT"]
    overfits = [k for k, v in signaux.items() if v.verdict == "OVERFITTE"]

    rapport = {
        "ts":             datetime.utcnow().isoformat(),
        "duree_s":        round(time.time() - t0, 1),
        "n_signaux":      len(signaux),
        "valides":        valides,
        "bruits":         bruits,
        "overfits":       overfits,
        "crises_testees": list(CRISES.keys()),
        "signaux":        {k: v.to_dict() for k, v in signaux.items()},
        "traders_map":    TRADER_ARCHETYPES,
        "signal_regime_coherent": _check_regime_coherence(valides),
    }

    with _LOCK:
        _cache    = rapport
        _cache_ts = time.time()

    logger.info(
        "Alpha Lab [ValidSignaux] rapport généré en %.1fs — %d signaux "
        "(✅%d VALIDES | 🔇%d BRUITS | ⚠️%d OVERFITS)",
        time.time() - t0, len(signaux), len(valides), len(bruits), len(overfits),
    )

    # ── Bloc 3 : Bertez VALIDE → soumettre à AGD-01 pour avocat du diable ──
    if "Bertez_Energy" in valides:
        _notifier_agd01_bertez_valide(signaux.get("Bertez_Energy"))

    return rapport


def _check_regime_coherence(valides: list) -> bool:
    """
    Retourne True si TrendFollow est VALIDE ET que le Flux Macro détecte CRISE_LIQUIDITE.
    Utilisé pour le badge cross-agent dans le frontend (Bloc 4).
    Silencieux en cas d'erreur (Flux Macro peut ne pas avoir encore tourné).
    """
    if "TrendFollow" not in valides:
        return False
    try:
        from divisions.research.agent_flux_macro import get_agent_flux_macro
        cache = get_agent_flux_macro()._cache
        if cache is None:
            return False
        regime = (cache.get("regime") or {}).get("regime", "")
        return regime == "CRISE_LIQUIDITE"
    except Exception:
        return False


def _notifier_agd01_bertez_valide(res) -> None:
    """
    Quand le signal Bertez passe VALIDE (t≥2 + Sharpe OOS≥0.5),
    soumet le résultat à AGD-01 pour avocat du diable et audit.
    Ne bloque pas le rapport en cas d'erreur.
    """
    try:
        from divisions.gerant_delegue.agd_01 import get_gerant_delegue
        agd = get_gerant_delegue()
        contexte = (
            f"[ALPHA LAB — BERTEZ SIGNAL VALIDE]\n"
            f"Signal Bertez_Energy validé statistiquement :\n"
            f"  t-stat={res.t_stat:.2f} (seuil≥2.0) | Sharpe OOS={res.sharpe_oos:.3f} (seuil≥0.50)\n"
            f"  Sharpe IS={res.sharpe_is:.3f} | Max Drawdown={res.max_drawdown*100:.1f}%\n"
            f"  Observations={res.n_obs} mois (French 1926+)\n\n"
            "Proxy HML<0 + CAPE>25 → régime défensif Bertez activé.\n"
            "Confronte cette validation académique à ta thèse macro actuelle.\n"
            "Donne 3 raisons pour lesquelles ce signal pourrait être faux ou non applicable aujourd'hui."
        )
        result = agd.evaluer_decision(
            ticker="ALPHA_LAB_BERTEZ",
            action="signal_valide",
            montant=0.0,
            contexte=contexte,
            perf_annualisee=0.0,
            patrimoine=18082.0,
        )
        decision = result.get("decision", "")
        logger.info("[AlphaLab] AGD-01 réponse Bertez VALIDE → %s", decision)
    except Exception as exc:
        logger.debug("[AlphaLab] AGD-01 notification Bertez: %s", exc)

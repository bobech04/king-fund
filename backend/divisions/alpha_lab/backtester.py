"""
Alpha Lab — Moteur de Backtest
Walk-forward train/test split, t-stat, Sharpe annualisé, max drawdown.
Détection de 3 régimes : bull / bear / crisis.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ANNUALISE = 12  # rendements mensuels → Sharpe annualisé

# ---------------------------------------------------------------------------
# Dataclass résultat
# ---------------------------------------------------------------------------


@dataclass
class BacktestResult:
    signal_name:    str
    sharpe_is:      float   # Sharpe in-sample (tout l'historique)
    sharpe_oos:     float   # Sharpe out-of-sample (walk-forward moyen)
    t_stat:         float   # t-test H0: rendement moyen = 0
    p_value:        float
    max_drawdown:   float   # drawdown maximum (négatif)
    n_obs:          int
    regime_sharpes: dict = field(default_factory=dict)
    crises_perf:    dict = field(default_factory=dict)
    verdict:        str  = "INCONNU"

    def to_dict(self) -> dict:
        return {
            "signal":         self.signal_name,
            "sharpe_is":      round(self.sharpe_is,    3),
            "sharpe_oos":     round(self.sharpe_oos,   3),
            "t_stat":         round(self.t_stat,       3),
            "p_value":        round(self.p_value,      4),
            "max_drawdown":   round(self.max_drawdown, 3),
            "n_obs":          self.n_obs,
            "regime_sharpes": {k: round(v, 3) for k, v in self.regime_sharpes.items()},
            "crises_perf":    self.crises_perf,
            "verdict":        self.verdict,
        }


# ---------------------------------------------------------------------------
# Métriques de base
# ---------------------------------------------------------------------------


def _sharpe(returns: pd.Series) -> float:
    r = returns.dropna()
    if len(r) < 6 or r.std() < 1e-10:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(ANNUALISE))


def _max_drawdown(returns: pd.Series) -> float:
    cum  = (1 + returns.fillna(0)).cumprod()
    peak = cum.cummax()
    dd   = (cum - peak) / peak.replace(0, np.nan)
    return float(dd.min()) if not dd.empty else 0.0


def _t_stat(returns: pd.Series):
    """t-test contre H0: mu = 0. Retourne (t, p)."""
    r = returns.dropna()
    n = len(r)
    if n < 6:
        return 0.0, 1.0
    mu  = r.mean()
    sem = r.std(ddof=1) / np.sqrt(n)
    if sem < 1e-12:
        return 0.0, 1.0
    t = mu / sem
    # p-value approximée via loi normale (assez fiable pour n > 30)
    from math import erfc, sqrt
    p = float(erfc(abs(t) / sqrt(2)))
    return float(t), p


# ---------------------------------------------------------------------------
# Détection de régimes
# ---------------------------------------------------------------------------


def detect_regimes(returns: pd.Series) -> pd.Series:
    """
    Étiquette chaque observation mensuelle avec un régime marché :
      bull   : rendement cumulé 12 mois glissants > médiane des rendements 12 mois
      crisis : drawdown cumulé 12 mois glissants < −20 %
      bear   : toutes les autres observations
    """
    rolling12 = returns.rolling(12).sum()
    median12  = rolling12.median()

    cum  = (1 + returns).cumprod()
    peak = cum.rolling(12, min_periods=1).max()
    dd12 = (cum - peak) / peak.replace(0, np.nan)

    regime = pd.Series("bear", index=returns.index, dtype=object)
    regime[rolling12 > median12] = "bull"
    regime[dd12 < -0.20]         = "crisis"
    return regime


# ---------------------------------------------------------------------------
# Walk-forward split
# ---------------------------------------------------------------------------


def _walk_forward_splits(n: int, n_splits: int = 5, min_train_frac: float = 0.50):
    """
    Expanding-window walk-forward.
    Retourne une liste de (slice_train, slice_test).
    """
    min_train = max(24, int(n * min_train_frac))   # au moins 24 mois d'entraînement
    remaining = n - min_train
    if remaining < n_splits:
        n_splits = max(1, remaining)
    test_size = remaining // n_splits

    splits = []
    for i in range(n_splits):
        train_end  = min_train + i * test_size
        test_start = train_end
        test_end   = min(n, test_start + test_size)
        if test_end <= test_start:
            break
        splits.append((slice(0, train_end), slice(test_start, test_end)))
    return splits


# ---------------------------------------------------------------------------
# Moteur principal
# ---------------------------------------------------------------------------


def backtest(
    signal:      pd.Series,
    returns:     pd.Series,
    signal_name: str = "signal",
    n_splits:    int = 5,
) -> BacktestResult:
    """
    Backtest d'un signal contre une série de rendements mensuels.

    signal  : pd.Series — valeur positive = long, négative = short/cash.
              Décalé d'un mois pour éviter le look-ahead.
    returns : pd.Series de rendements mensuels décimaux (ex: 0.02 = +2 %).
    """
    # Alignement strict
    common = signal.index.intersection(returns.index)
    if len(common) < 24:
        return BacktestResult(
            signal_name=signal_name, sharpe_is=0, sharpe_oos=0,
            t_stat=0, p_value=1, max_drawdown=0, n_obs=len(common),
            verdict="BRUIT",
        )

    sig = signal.loc[common].fillna(0)
    ret = returns.loc[common].fillna(0)

    # Rendements de la stratégie (signal décalé d'1 mois)
    sig_shifted  = sig.shift(1).fillna(0).clip(-1, 1)
    strat_ret    = sig_shifted * ret

    # ── Métriques globales ───────────────────────────────────────────────────
    sharpe_is  = _sharpe(strat_ret)
    t, p       = _t_stat(strat_ret)
    mdd        = _max_drawdown(strat_ret)

    # ── Walk-forward OOS ────────────────────────────────────────────────────
    n      = len(strat_ret)
    splits = _walk_forward_splits(n, n_splits)
    oos_sharpes = [_sharpe(strat_ret.iloc[ts]) for _, ts in splits]
    sharpe_oos  = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0

    # ── Régimes ────────────────────────────────────────────────────────────
    regimes = detect_regimes(ret)
    regime_sharpes: dict[str, float] = {}
    for r_name in ("bull", "bear", "crisis"):
        mask = regimes == r_name
        if mask.sum() >= 12:
            regime_sharpes[r_name] = _sharpe(strat_ret[mask])

    # ── Verdict ────────────────────────────────────────────────────────────
    if abs(t) >= 2.0 and sharpe_oos >= 0.50:
        verdict = "VALIDE"
    elif abs(t) >= 2.0 and sharpe_oos < 0.25:
        verdict = "OVERFITTE"
    else:
        verdict = "BRUIT"

    return BacktestResult(
        signal_name=signal_name,
        sharpe_is=sharpe_is,
        sharpe_oos=sharpe_oos,
        t_stat=float(t),
        p_value=float(p),
        max_drawdown=mdd,
        n_obs=n,
        regime_sharpes=regime_sharpes,
        verdict=verdict,
    )

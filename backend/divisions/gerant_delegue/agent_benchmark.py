"""
Agent Benchmark — Division Gérant Délégué

Compare la performance du portefeuille King Fund vs :
  • CAC 40         (^FCHI)
  • S&P 500        (^GSPC)
  • MSCI World     (URTH — iShares MSCI World ETF)

Métriques calculées :
  • Performance absolue (%) sur 1j, 1s, 1m, 3m, YTD
  • Alpha réel = perf_portefeuille − perf_benchmark (annualisé)
  • Sharpe ratio (portefeuille vs rf = 3.5%)
  • Max Drawdown
  • Beta du portefeuille vs S&P 500

Cache : 1h
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logger = logging.getLogger(__name__)

BENCHMARKS = {
    "CAC40":     "^FCHI",
    "SP500":     "^GSPC",
    "MSCI_WORLD":"URTH",
}
_TAUX_SANS_RISQUE = 0.035   # 3.5% annuel
_CACHE_TTL        = 3600    # 1h
_BATTLE_START     = date(2026, 5, 30)


def _perf_pct(series: "Any", n: int) -> float | None:
    """Performance sur n dernières barres (%)."""
    try:
        arr = series.dropna().values
        if len(arr) < n + 1:
            return None
        return round((arr[-1] / arr[-(n + 1)] - 1) * 100, 2)
    except Exception:
        return None


def _max_drawdown(series: "Any") -> float | None:
    try:
        arr = series.dropna().values
        if len(arr) < 2:
            return None
        peak = arr[0]
        max_dd = 0.0
        for val in arr:
            peak = max(peak, val)
            dd   = (val - peak) / peak * 100
            max_dd = min(max_dd, dd)
        return round(max_dd, 2)
    except Exception:
        return None


def _sharpe(returns: "Any", rf_daily: float) -> float | None:
    try:
        import numpy as np
        arr   = returns.dropna().values
        exc   = arr - rf_daily
        if len(exc) < 10 or np.std(exc, ddof=1) == 0:
            return None
        return round(float(np.mean(exc) / np.std(exc, ddof=1) * (252 ** 0.5)), 2)
    except Exception:
        return None


def _beta(port_ret: "Any", bench_ret: "Any") -> float | None:
    try:
        import numpy as np
        p = port_ret.dropna().values
        b = bench_ret.dropna().values
        n = min(len(p), len(b))
        if n < 10:
            return None
        cov  = np.cov(p[-n:], b[-n:])[0][1]
        var  = np.var(b[-n:], ddof=1)
        return round(cov / var, 2) if var > 0 else None
    except Exception:
        return None


class AgentBenchmark:
    """
    Compare le portefeuille King Fund aux indices de référence.
    """

    def __init__(self) -> None:
        self._lock      = threading.Lock()
        self._cache:    dict = {}
        self._cache_ts: float = 0.0

    # ------------------------------------------------------------------
    # Collecte
    # ------------------------------------------------------------------

    def _fetch_benchmark(self, label: str, ticker: str) -> dict:
        try:
            import yfinance as yf
            hist = yf.Ticker(ticker).history(period="6mo", interval="1d", auto_adjust=True)
            if hist.empty:
                return {"label": label, "ticker": ticker, "erreur": "Pas de données"}

            close = hist["Close"]
            rets  = close.pct_change()

            perfs: dict[str, Any] = {}
            for label_p, n_bars in [("1j", 1), ("1s", 5), ("1m", 21), ("3m", 63), ("YTD", None)]:
                if label_p == "YTD":
                    debut_ytd = date(date.today().year, 1, 1)
                    sub = close[close.index.date >= debut_ytd]
                    if len(sub) >= 2:
                        perfs["YTD"] = round((sub.iloc[-1] / sub.iloc[0] - 1) * 100, 2)
                    else:
                        perfs["YTD"] = None
                else:
                    perfs[label_p] = _perf_pct(close, n_bars)

            return {
                "label":        label,
                "ticker":       ticker,
                "prix":         round(float(close.iloc[-1]), 2),
                "performances": perfs,
                "max_drawdown": _max_drawdown(close),
                "sharpe":       _sharpe(rets, _TAUX_SANS_RISQUE / 252),
            }
        except Exception as e:
            logger.debug("[Benchmark] %s: %s", ticker, e)
            return {"label": label, "ticker": ticker, "erreur": str(e)}

    def _fetch_portfolio_nav(self) -> list[float] | None:
        """Récupère l'historique NAV du King Fund depuis la DB SQLite."""
        try:
            from config import DB_PATH
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute(
                """SELECT timestamp, total_value
                   FROM snapshots
                   ORDER BY timestamp ASC
                   LIMIT 500"""
            ).fetchall()
            conn.close()
            if not rows:
                return None
            # total_value = somme valeur tous traders
            navs: dict[str, float] = {}
            for ts, val in rows:
                day = ts[:10]
                navs[day] = navs.get(day, 0) + float(val)
            return list(navs.values())
        except Exception as e:
            logger.debug("[Benchmark] NAV DB: %s", e)
            return None

    # ------------------------------------------------------------------
    # Analyse principale
    # ------------------------------------------------------------------

    def analyser(self, nav_series: list[float] | None = None, forcer: bool = False) -> dict:
        now = time.monotonic()
        if not forcer and self._cache and (now - self._cache_ts) < _CACHE_TTL:
            return self._cache

        # Benchmarks
        bench_data = {}
        for label, ticker in BENCHMARKS.items():
            bench_data[label] = self._fetch_benchmark(label, ticker)

        # NAV King Fund
        if nav_series is None:
            nav_series = self._fetch_portfolio_nav()

        portfolio_perfs: dict[str, Any] = {}
        alpha:           dict[str, Any] = {}
        sharpe_port = None
        beta_sp500  = None
        max_dd_port = None

        if nav_series and len(nav_series) >= 2:
            try:
                import numpy as np
                import pandas as pd
                nav_arr = np.array(nav_series, dtype=float)
                nav_s   = pd.Series(nav_arr)
                rets    = nav_s.pct_change().dropna()

                for label_p, n_bars in [("1j", 1), ("1s", 5), ("1m", 21), ("3m", 63)]:
                    portfolio_perfs[label_p] = _perf_pct(nav_s, n_bars)

                portfolio_perfs["total"] = round((nav_arr[-1] / nav_arr[0] - 1) * 100, 2)
                n_jours  = len(nav_arr) - 1
                if n_jours > 0:
                    portfolio_perfs["annualise"] = round(
                        ((nav_arr[-1] / nav_arr[0]) ** (252 / n_jours) - 1) * 100, 2
                    )

                sharpe_port = _sharpe(rets, _TAUX_SANS_RISQUE / 252)
                max_dd_port = _max_drawdown(nav_s)

                # Alpha réel vs chaque benchmark
                for label, bdata in bench_data.items():
                    perf_b = bdata.get("performances", {}).get("total") or bdata.get("performances", {}).get("YTD")
                    if perf_b is not None and portfolio_perfs.get("total") is not None:
                        alpha[label] = round(portfolio_perfs["total"] - perf_b, 2)

            except Exception as e:
                logger.debug("[Benchmark] Calcul portfolio: %s", e)

        rapport = {
            "benchmarks":        bench_data,
            "portfolio":         {
                "performances":  portfolio_perfs,
                "sharpe":        sharpe_port,
                "max_drawdown":  max_dd_port,
                "beta_sp500":    beta_sp500,
            },
            "alpha_reel":        alpha,
            "taux_sans_risque":  _TAUX_SANS_RISQUE,
            "periode_battle":    str(_BATTLE_START),
            "timestamp":         datetime.now(timezone.utc).isoformat(),
        }

        with self._lock:
            self._cache    = rapport
            self._cache_ts = now

        logger.info(
            "[Benchmark] Alpha vs SP500: %s | Sharpe: %s",
            alpha.get("SP500", "N/A"), sharpe_port,
        )
        return rapport

    def etat(self) -> dict:
        cache = self._cache
        return {
            "alpha":    cache.get("alpha_reel", {}),
            "sharpe":   cache.get("portfolio", {}).get("sharpe"),
            "drawdown": cache.get("portfolio", {}).get("max_drawdown"),
            "timestamp":cache.get("timestamp"),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: AgentBenchmark | None = None
_lock = threading.Lock()


def get_agent_benchmark() -> AgentBenchmark:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AgentBenchmark()
    return _instance

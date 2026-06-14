"""
Watchlist actifs King Fund — analyse pipeline 17 étapes + données yfinance.
"""
from __future__ import annotations
import json
import logging
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

from .pipeline import InvestmentPipeline

logger = logging.getLogger(__name__)

CACHE_TTL  = 3_600  # 1 h
_EXTRA_PATH = Path(__file__).parent.parent.parent.parent / "data" / "watchlist_extra.json"

WATCHLIST: list[dict[str, str]] = [
    {"ticker": "VPK.AS",  "nom": "Vopak",                   "bourse": "Euronext Amsterdam"},
    {"ticker": "GTT.PA",  "nom": "GTT",                      "bourse": "Euronext Paris"},
    {"ticker": "O",       "nom": "Realty Income",             "bourse": "NYSE"},
    {"ticker": "JNJ",     "nom": "Johnson & Johnson",         "bourse": "NYSE"},
    {"ticker": "VZ",      "nom": "Verizon",                   "bourse": "NYSE"},
    {"ticker": "TEL.OL",  "nom": "Telenor",                  "bourse": "Oslo Bors"},
    {"ticker": "DNB.OL",  "nom": "DNB Bank",                 "bourse": "Oslo Bors"},
    {"ticker": "BIPC",    "nom": "Brookfield Infrastructure", "bourse": "NYSE"},
    {"ticker": "ADC",     "nom": "Agree Realty",              "bourse": "NYSE"},
    {"ticker": "TTE.PA",  "nom": "TotalEnergies",            "bourse": "Euronext Paris"},
]


# Charge les tickers ajoutés dynamiquement (persistance JSON)
try:
    if _EXTRA_PATH.exists():
        _existing_tickers = {w["ticker"] for w in WATCHLIST}
        for _extra in json.loads(_EXTRA_PATH.read_text("utf-8")):
            if _extra.get("ticker") and _extra["ticker"] not in _existing_tickers:
                WATCHLIST.append(_extra)
                _existing_tickers.add(_extra["ticker"])
except Exception:
    pass


def _safe(v, default=None):
    if v is None:
        return default
    try:
        f = float(v)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


class WatchlistManager:
    def __init__(self) -> None:
        self._pipeline  = InvestmentPipeline()
        self._cache:    dict[str, dict] = {}
        self._cache_ts: dict[str, float] = {}
        self._lock = threading.Lock()

    def analyser_watchlist(self, force: bool = False) -> list[dict[str, Any]]:
        """Lance le pipeline 17 étapes sur les 13 actifs et retourne les résultats."""
        now = time.monotonic()
        results = []
        for item in WATCHLIST:
            ticker = item["ticker"]
            if not force:
                with self._lock:
                    if ticker in self._cache and (now - self._cache_ts.get(ticker, 0.0)) < CACHE_TTL:
                        results.append(self._cache[ticker])
                        continue
            r = self._analyser_un(ticker, item)
            with self._lock:
                self._cache[ticker]    = r
                self._cache_ts[ticker] = now
            results.append(r)
        return results

    def get_cached_result(self, ticker: str) -> dict | None:
        with self._lock:
            return self._cache.get(ticker)

    def add_ticker(self, ticker: str) -> None:
        """Ajoute un ticker en mémoire et le persiste dans watchlist_extra.json."""
        with self._lock:
            if any(w["ticker"] == ticker for w in WATCHLIST):
                return
            item: dict[str, str] = {"ticker": ticker, "nom": ticker, "bourse": "—"}
            WATCHLIST.append(item)
            try:
                extras: list = json.loads(_EXTRA_PATH.read_text("utf-8")) if _EXTRA_PATH.exists() else []
            except Exception:
                extras = []
            if not any(e.get("ticker") == ticker for e in extras):
                extras.append(item)
                _EXTRA_PATH.parent.mkdir(parents=True, exist_ok=True)
                _EXTRA_PATH.write_text(json.dumps(extras, ensure_ascii=False, indent=2), encoding="utf-8")

    def _analyser_un(self, ticker: str, item: dict) -> dict[str, Any]:
        ts = datetime.now(timezone.utc).isoformat()
        try:
            analysis = self._pipeline.analyze(ticker)
            info     = yf.Ticker(ticker).info or {}

            prix   = _safe(info.get("currentPrice"))
            target = _safe(info.get("targetMeanPrice"))
            marge  = ((target - prix) / prix) if (prix and target and prix > 0) else None

            return {
                "ticker":         ticker,
                "nom":            item["nom"],
                "bourse":         item["bourse"],
                "score":          analysis["score"],
                "signal":         analysis["signal"].upper(),   # BUY | HOLD | SELL
                "stages":         analysis["stages"],
                "prix_actuel":    prix,
                "target_price":   target,
                "marge_securite": round(marge, 4) if marge is not None else None,
                "per":            _safe(info.get("trailingPE")),
                "pbr":            _safe(info.get("priceToBook")),
                "dividende":      _safe(info.get("dividendYield")),
                "secteur":        info.get("sector"),
                "beta":           _safe(info.get("beta")),
                "timestamp":      ts,
            }
        except Exception as e:
            logger.warning("Watchlist %s erreur: %s", ticker, e)
            return {
                "ticker":    ticker,
                "nom":       item["nom"],
                "bourse":    item["bourse"],
                "erreur":    str(e),
                "timestamp": ts,
            }


_instance: WatchlistManager | None = None


def get_watchlist_manager() -> WatchlistManager:
    global _instance
    if _instance is None:
        _instance = WatchlistManager()
    return _instance

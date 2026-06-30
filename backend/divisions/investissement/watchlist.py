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
_EXTRA_PATH   = Path(__file__).parent.parent.parent.parent / "data" / "watchlist_extra.json"
_SEUILS_PATH  = Path(__file__).parent.parent.parent.parent / "data" / "seuils_achat.json"

# ── Éligibilité PEA automatique ─────────────────────────────────────────────────
#
# Règle : les titres dont le siège social est dans l'UE ou l'EEE (Espace Économique
# Européen = UE + Norvège + Islande + Liechtenstein) sont éligibles au PEA.
# Le Royaume-Uni est EXCLU depuis le Brexit (2021).
#
# Source yfinance : info["country"] — code ISO 3166-1 alpha-2 (FR, DE, NO, US…)
# Cas particuliers connus → table de surcharge manuelle _PEA_MANUAL_OVERRIDE.

_EU_EEA_COUNTRIES: frozenset[str] = frozenset({
    # Union Européenne
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI",
    "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
    "NL", "PL", "PT", "RO", "SE", "SI", "SK",
    # EEE hors UE
    "NO", "IS", "LI",
})

# Surcharges manuelles : True = PEA, False = CTO
# Prennent le dessus sur la détection automatique via yfinance.
_PEA_MANUAL_OVERRIDE: dict[str, bool] = {
    "SHEL.L": False,   # Shell → UK depuis 2022, exclusion PEA confirmée
    "BIPC":   False,   # Brookfield Infrastructure Partners → Canada (TSX)
    "XYL":    False,   # Xylem → USA
    "O":      False,   # Realty Income → USA
    "JNJ":    False,   # Johnson & Johnson → USA
    "VZ":     False,   # Verizon → USA
    "ADC":    False,   # Agree Realty → USA
    "WPM":    False,   # Wheaton → Canada
    "UEC":    False,   # Uranium Energy → USA
    "RY":     False,   # Royal Bank → Canada
    "MAIN":   False,   # Main Street → USA
    "MRK":    False,   # Merck → USA
    "MSFT":   False,   # Microsoft → USA
    "NTR":    False,   # Nutrien → Canada
    "MOS":    False,   # Mosaic → USA
    "TPL":    False,   # Texas Pacific → USA
    "KB":     False,   # KB Financial → Korea
    "PBR":    False,   # Petrobras → Brazil
    "PG":     False,   # P&G → USA
    "KO":     False,   # Coca-Cola → USA
    "NEE":    False,   # NextEra → USA
    "WMS":    False,   # Advanced Drainage → USA
    "0857.HK": False,  # PetroChina → China
    "0941.HK": False,  # China Mobile → China
    # Oslo Børs (Norvège = EEE) → PEA
    "TEL.OL": True,
    "DNB.OL": True,
    "YAR.OL": True,
}

# Tickers historiquement non-éligibles (conservé pour compatibilité)
_PEA_INELIGIBLE: frozenset[str] = frozenset(
    t for t, eligible in _PEA_MANUAL_OVERRIDE.items() if not eligible
)


def _pea_eligible(ticker: str, info: dict) -> bool:
    """Détermine l'éligibilité PEA du ticker.
    Priorité : surcharge manuelle > pays yfinance.
    """
    if ticker in _PEA_MANUAL_OVERRIDE:
        return _PEA_MANUAL_OVERRIDE[ticker]
    country = (info.get("country") or "").upper()
    if country:
        return country in _EU_EEA_COUNTRIES
    # Heuristique sur la bourse si pays absent
    bourse_lower = (info.get("exchange") or "").lower()
    if any(x in bourse_lower for x in ("paris", "amsterdam", "frankfurt", "oslo", "milan", "madrid")):
        return True
    return False

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
    {"ticker": "ENGI.PA", "nom": "Engie",                    "bourse": "Euronext Paris"},
]


def _charger_seuils_achat() -> dict[str, dict]:
    """Retourne un dict {ticker: seuil_info} depuis seuils_achat.json."""
    try:
        if _SEUILS_PATH.exists():
            return {s["ticker"]: s for s in json.loads(_SEUILS_PATH.read_text("utf-8"))}
    except Exception:
        pass
    return {}


_SEUILS_ACHAT: dict[str, dict] = _charger_seuils_achat()


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

            # Seuil d'achat personnalisé
            seuil_info   = _SEUILS_ACHAT.get(ticker)
            seuil_label  = None
            ecart_seuil  = None
            dans_zone    = None
            if seuil_info and prix is not None:
                sh = seuil_info.get("seuil_haut")
                sb = seuil_info.get("seuil_bas")
                devise = seuil_info.get("devise", "")
                symbole = {"EUR": "€", "USD": "$", "NOK": "NOK"}.get(devise, devise)
                if sb is not None:
                    seuil_label = f"Zone {sb}–{sh} {symbole}"
                    dans_zone   = sb <= prix <= sh if sh else prix <= sh  # type: ignore[operator]
                    ecart_seuil = round(prix - sb, 2) if sb else None
                elif sh is not None:
                    seuil_label = f"< {sh} {symbole}"
                    dans_zone   = prix < sh
                    ecart_seuil = round(prix - sh, 2)

            pea = _pea_eligible(ticker, info)
            return {
                "ticker":         ticker,
                "nom":            item["nom"],
                "bourse":         item["bourse"],
                "pea_eligible":   pea,
                "pays":           info.get("country"),
                "score":          analysis["score"],
                "signal":         analysis["signal"].upper(),   # BUY | HOLD | SELL
                "stages":         analysis["stages"],
                "rsi_macd":       analysis.get("rsi_macd"),
                "prix_actuel":    prix,
                "target_price":   target,
                "marge_securite": round(marge, 4) if marge is not None else None,
                "per":            _safe(info.get("trailingPE")),
                "pbr":            _safe(info.get("priceToBook")),
                "dividende":      _safe(info.get("dividendYield")),
                "secteur":        info.get("sector"),
                "beta":           _safe(info.get("beta")),
                "timestamp":      ts,
                # Seuil d'achat
                "seuil_achat":    seuil_info.get("seuil_haut") if seuil_info else None,
                "seuil_bas":      seuil_info.get("seuil_bas")  if seuil_info else None,
                "seuil_devise":   seuil_info.get("devise")      if seuil_info else None,
                "seuil_label":    seuil_label,
                "ecart_seuil":    ecart_seuil,
                "dans_zone_achat": dans_zone,
            }
        except Exception as e:
            logger.warning("Watchlist %s erreur: %s", ticker, e)
            return {
                "ticker":       ticker,
                "nom":          item["nom"],
                "bourse":       item["bourse"],
                "pea_eligible": _pea_eligible(ticker, {}),
                "erreur":       str(e),
                "timestamp":    ts,
            }


_instance: WatchlistManager | None = None


def get_watchlist_manager() -> WatchlistManager:
    global _instance
    if _instance is None:
        _instance = WatchlistManager()
    return _instance

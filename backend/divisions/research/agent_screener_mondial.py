"""
AgentScreenerMondial — scan nuitique Yahoo Finance.

Scans ~150 titres (US, EU, Asie) chaque nuit, filtre selon les critères Graham :
  PER < 15 | PBR < 1.5 | dividende > 3% | D/E < 100 | croissance revenus > 0
Produit une liste de 10 candidats classés par score Graham composite.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Univers de ~150 titres couvrant US / EU / Asie — axés valeur & dividende
# ---------------------------------------------------------------------------
UNIVERSE: list[dict[str, str]] = [
    # ── US — dividendes & valeur ───────────────────────────────────────────
    {"ticker": "T",      "nom": "AT&T",               "marche": "NYSE"},
    {"ticker": "VZ",     "nom": "Verizon",             "marche": "NYSE"},
    {"ticker": "MO",     "nom": "Altria",              "marche": "NYSE"},
    {"ticker": "PM",     "nom": "Philip Morris",       "marche": "NYSE"},
    {"ticker": "KO",     "nom": "Coca-Cola",           "marche": "NYSE"},
    {"ticker": "PEP",    "nom": "PepsiCo",             "marche": "NYSE"},
    {"ticker": "JNJ",    "nom": "J&J",                 "marche": "NYSE"},
    {"ticker": "PFE",    "nom": "Pfizer",              "marche": "NYSE"},
    {"ticker": "ABBV",   "nom": "AbbVie",              "marche": "NYSE"},
    {"ticker": "MRK",    "nom": "Merck",               "marche": "NYSE"},
    {"ticker": "CVX",    "nom": "Chevron",             "marche": "NYSE"},
    {"ticker": "XOM",    "nom": "ExxonMobil",          "marche": "NYSE"},
    {"ticker": "COP",    "nom": "ConocoPhillips",      "marche": "NYSE"},
    {"ticker": "USB",    "nom": "US Bancorp",          "marche": "NYSE"},
    {"ticker": "WFC",    "nom": "Wells Fargo",         "marche": "NYSE"},
    {"ticker": "BAC",    "nom": "Bank of America",     "marche": "NYSE"},
    {"ticker": "C",      "nom": "Citigroup",           "marche": "NYSE"},
    {"ticker": "JPM",    "nom": "JPMorgan Chase",      "marche": "NYSE"},
    {"ticker": "GS",     "nom": "Goldman Sachs",       "marche": "NYSE"},
    {"ticker": "O",      "nom": "Realty Income",       "marche": "NYSE"},
    {"ticker": "VTR",    "nom": "Ventas REIT",         "marche": "NYSE"},
    {"ticker": "SPG",    "nom": "Simon Property",      "marche": "NYSE"},
    {"ticker": "WPC",    "nom": "W.P. Carey",          "marche": "NYSE"},
    {"ticker": "ADC",    "nom": "Agree Realty",        "marche": "NYSE"},
    {"ticker": "BIPC",   "nom": "Brookfield Infra",    "marche": "NYSE"},
    {"ticker": "ED",     "nom": "Con Edison",          "marche": "NYSE"},
    {"ticker": "DUK",    "nom": "Duke Energy",         "marche": "NYSE"},
    {"ticker": "SO",     "nom": "Southern Company",    "marche": "NYSE"},
    {"ticker": "D",      "nom": "Dominion Energy",     "marche": "NYSE"},
    {"ticker": "IBM",    "nom": "IBM",                 "marche": "NYSE"},
    {"ticker": "MMM",    "nom": "3M",                  "marche": "NYSE"},
    {"ticker": "GE",     "nom": "GE",                  "marche": "NYSE"},
    {"ticker": "HON",    "nom": "Honeywell",           "marche": "NASDAQ"},
    {"ticker": "CAT",    "nom": "Caterpillar",         "marche": "NYSE"},
    {"ticker": "DE",     "nom": "Deere & Co",          "marche": "NYSE"},
    {"ticker": "LMT",    "nom": "Lockheed Martin",     "marche": "NYSE"},
    {"ticker": "RTX",    "nom": "Raytheon",            "marche": "NYSE"},
    {"ticker": "NUE",    "nom": "Nucor",               "marche": "NYSE"},
    {"ticker": "CF",     "nom": "CF Industries",       "marche": "NYSE"},
    {"ticker": "IP",     "nom": "Intl Paper",          "marche": "NYSE"},
    {"ticker": "WBA",    "nom": "Walgreens",           "marche": "NASDAQ"},
    {"ticker": "CLX",    "nom": "Clorox",              "marche": "NYSE"},
    {"ticker": "KHC",    "nom": "Kraft Heinz",         "marche": "NASDAQ"},
    {"ticker": "CL",     "nom": "Colgate",             "marche": "NYSE"},
    {"ticker": "PG",     "nom": "Procter & Gamble",    "marche": "NYSE"},
    # ── Europe / Euronext / LSE ────────────────────────────────────────────
    {"ticker": "TTE.PA",  "nom": "TotalEnergies",      "marche": "Euronext Paris"},
    {"ticker": "BNP.PA",  "nom": "BNP Paribas",        "marche": "Euronext Paris"},
    {"ticker": "ACA.PA",  "nom": "Crédit Agricole",    "marche": "Euronext Paris"},
    {"ticker": "SAN.PA",  "nom": "Sanofi",             "marche": "Euronext Paris"},
    {"ticker": "MC.PA",   "nom": "LVMH",               "marche": "Euronext Paris"},
    {"ticker": "OR.PA",   "nom": "L'Oréal",            "marche": "Euronext Paris"},
    {"ticker": "AI.PA",   "nom": "Air Liquide",        "marche": "Euronext Paris"},
    {"ticker": "DG.PA",   "nom": "Vinci",              "marche": "Euronext Paris"},
    {"ticker": "ENGI.PA", "nom": "Engie",              "marche": "Euronext Paris"},
    {"ticker": "ORA.PA",  "nom": "Orange",             "marche": "Euronext Paris"},
    {"ticker": "VIE.PA",  "nom": "Veolia",             "marche": "Euronext Paris"},
    {"ticker": "SU.PA",   "nom": "Schneider Electric", "marche": "Euronext Paris"},
    {"ticker": "GTT.PA",  "nom": "GTT",                "marche": "Euronext Paris"},
    {"ticker": "DSY.PA",  "nom": "Dassault Systèmes",  "marche": "Euronext Paris"},
    {"ticker": "AIR.PA",  "nom": "Airbus",             "marche": "Euronext Paris"},
    {"ticker": "VPK.AS",  "nom": "Vopak",              "marche": "Euronext Amsterdam"},
    {"ticker": "ASML.AS", "nom": "ASML",               "marche": "Euronext Amsterdam"},
    {"ticker": "HEIA.AS", "nom": "Heineken",           "marche": "Euronext Amsterdam"},
    {"ticker": "NN.AS",   "nom": "NN Group",           "marche": "Euronext Amsterdam"},
    {"ticker": "RAND.AS", "nom": "Randstad",           "marche": "Euronext Amsterdam"},
    {"ticker": "TEL.OL",  "nom": "Telenor",            "marche": "Oslo Bors"},
    {"ticker": "DNB.OL",  "nom": "DNB Bank",           "marche": "Oslo Bors"},
    {"ticker": "EQNR.OL", "nom": "Equinor",            "marche": "Oslo Bors"},
    {"ticker": "YAR.OL",  "nom": "Yara International", "marche": "Oslo Bors"},
    {"ticker": "ORK.OL",  "nom": "Orkla",              "marche": "Oslo Bors"},
    {"ticker": "BARC.L",  "nom": "Barclays",           "marche": "LSE"},
    {"ticker": "LLOY.L",  "nom": "Lloyds Banking",     "marche": "LSE"},
    {"ticker": "BP.L",    "nom": "BP",                 "marche": "LSE"},
    {"ticker": "SHEL.L",  "nom": "Shell",              "marche": "LSE"},
    {"ticker": "VOD.L",   "nom": "Vodafone",           "marche": "LSE"},
    {"ticker": "BT.L",    "nom": "BT Group",           "marche": "LSE"},
    {"ticker": "AZN.L",   "nom": "AstraZeneca",        "marche": "LSE"},
    {"ticker": "GSK.L",   "nom": "GSK",                "marche": "LSE"},
    {"ticker": "ULVR.L",  "nom": "Unilever",           "marche": "LSE"},
    {"ticker": "IMB.L",   "nom": "Imperial Brands",    "marche": "LSE"},
    {"ticker": "BATS.L",  "nom": "BAT",                "marche": "LSE"},
    {"ticker": "BA.L",    "nom": "BAE Systems",        "marche": "LSE"},
    {"ticker": "LGEN.L",  "nom": "Legal & General",    "marche": "LSE"},
    {"ticker": "PRU.L",   "nom": "Prudential",         "marche": "LSE"},
    {"ticker": "MNG.L",   "nom": "M&G",                "marche": "LSE"},
    # ── Allemagne / XETRA ─────────────────────────────────────────────────
    {"ticker": "ALV.DE",  "nom": "Allianz",            "marche": "XETRA"},
    {"ticker": "MUV2.DE", "nom": "Munich Re",          "marche": "XETRA"},
    {"ticker": "DBK.DE",  "nom": "Deutsche Bank",      "marche": "XETRA"},
    {"ticker": "MBG.DE",  "nom": "Mercedes-Benz",      "marche": "XETRA"},
    {"ticker": "BMW.DE",  "nom": "BMW",                "marche": "XETRA"},
    {"ticker": "VOW3.DE", "nom": "Volkswagen",         "marche": "XETRA"},
    {"ticker": "BAYN.DE", "nom": "Bayer",              "marche": "XETRA"},
    {"ticker": "BASF.DE", "nom": "BASF",               "marche": "XETRA"},
    {"ticker": "EON.DE",  "nom": "E.ON",               "marche": "XETRA"},
    {"ticker": "RWE.DE",  "nom": "RWE",                "marche": "XETRA"},
    {"ticker": "SIE.DE",  "nom": "Siemens",            "marche": "XETRA"},
    {"ticker": "DTE.DE",  "nom": "Deutsche Telekom",   "marche": "XETRA"},
    # ── Asie ──────────────────────────────────────────────────────────────
    {"ticker": "7203.T",  "nom": "Toyota",             "marche": "Tokyo"},
    {"ticker": "7267.T",  "nom": "Honda",              "marche": "Tokyo"},
    {"ticker": "6758.T",  "nom": "Sony",               "marche": "Tokyo"},
    {"ticker": "8306.T",  "nom": "Mitsubishi UFJ",     "marche": "Tokyo"},
    {"ticker": "8316.T",  "nom": "Sumitomo Mitsui",    "marche": "Tokyo"},
    {"ticker": "9433.T",  "nom": "KDDI",               "marche": "Tokyo"},
    {"ticker": "9432.T",  "nom": "NTT",                "marche": "Tokyo"},
    {"ticker": "4502.T",  "nom": "Takeda Pharma",      "marche": "Tokyo"},
    {"ticker": "8411.T",  "nom": "Mizuho",             "marche": "Tokyo"},
    {"ticker": "5401.T",  "nom": "Nippon Steel",       "marche": "Tokyo"},
    {"ticker": "0941.HK", "nom": "China Mobile",       "marche": "HK"},
    {"ticker": "0857.HK", "nom": "PetroChina",         "marche": "HK"},
    {"ticker": "2388.HK", "nom": "BOC Hong Kong",      "marche": "HK"},
    {"ticker": "1038.HK", "nom": "CKI Holdings",       "marche": "HK"},
    {"ticker": "0003.HK", "nom": "HK&China Gas",       "marche": "HK"},
    {"ticker": "SAMPO.HE","nom": "Sampo",              "marche": "Helsinki"},
    {"ticker": "NESTE.HE","nom": "Neste",              "marche": "Helsinki"},
    {"ticker": "WKL.AS",  "nom": "Wolters Kluwer",     "marche": "Euronext Amsterdam"},
    {"ticker": "PHIA.AS", "nom": "Philips",            "marche": "Euronext Amsterdam"},
    {"ticker": "MT.AS",   "nom": "ArcelorMittal",      "marche": "Euronext Amsterdam"},
    {"ticker": "AD.AS",   "nom": "Ahold Delhaize",     "marche": "Euronext Amsterdam"},
    {"ticker": "ABN.AS",  "nom": "ABN AMRO",           "marche": "Euronext Amsterdam"},
    {"ticker": "ING.AS",  "nom": "ING Group",          "marche": "Euronext Amsterdam"},
    {"ticker": "EXC",     "nom": "Exelon",             "marche": "NYSE"},
    {"ticker": "NEE",     "nom": "NextEra Energy",     "marche": "NYSE"},
    {"ticker": "PCG",     "nom": "PG&E",               "marche": "NYSE"},
    {"ticker": "WEC",     "nom": "WEC Energy",         "marche": "NYSE"},
    {"ticker": "AEP",     "nom": "American Electric",  "marche": "NYSE"},
    {"ticker": "ETR",     "nom": "Entergy",            "marche": "NYSE"},
    {"ticker": "FE",      "nom": "FirstEnergy",        "marche": "NYSE"},
    {"ticker": "PPL",     "nom": "PPL Corp",           "marche": "NYSE"},
    {"ticker": "OKE",     "nom": "ONEOK",              "marche": "NYSE"},
    {"ticker": "WMB",     "nom": "Williams Cos",       "marche": "NYSE"},
    {"ticker": "EPD",     "nom": "Enterprise Products","marche": "NYSE"},
    {"ticker": "KMI",     "nom": "Kinder Morgan",      "marche": "NYSE"},
    {"ticker": "MMP",     "nom": "Magellan Midstream",  "marche": "NYSE"},
    {"ticker": "HP",      "nom": "Helmerich & Payne",  "marche": "NYSE"},
    {"ticker": "VLO",     "nom": "Valero Energy",      "marche": "NYSE"},
    {"ticker": "MPC",     "nom": "Marathon Petroleum", "marche": "NYSE"},
]

# Critères de filtrage Graham
_PER_MAX      = 15.0
_PBR_MAX      = 1.5
_DIV_MIN      = 0.03    # 3%
_DE_MAX       = 100.0   # D/E < 100
_GROWTH_MIN   = 0.0     # croissance positive

# Cache TTL : 20h (le screener tourne à 23h, résultats valides jusqu'au lendemain)
_CACHE_TTL    = 20 * 3_600

_BATCH_PAUSE  = 0.3    # secondes entre batches pour éviter rate-limit Yahoo


def _safe(val, default=None):
    if val is None:
        return default
    try:
        f = float(val)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def _graham_score(info: dict) -> float:
    """Score composite Graham 0-100 (filtrage + classement)."""
    per     = _safe(info.get("trailingPE"))
    pbr     = _safe(info.get("priceToBook"))
    div     = _safe(info.get("dividendYield"), 0.0)
    de      = _safe(info.get("debtToEquity"),  999.0)
    growth  = _safe(info.get("revenueGrowth"), -1.0)
    cr      = _safe(info.get("currentRatio"),  0.0)

    # Normalisation des facteurs → [0, 1]
    s_per   = max(0.0, (_PER_MAX - per) / _PER_MAX)          if per   and per > 0  else 0.0
    s_pbr   = max(0.0, (_PBR_MAX - pbr) / _PBR_MAX)          if pbr   and pbr > 0  else 0.0
    s_div   = min(1.0, div / 0.08)                            if div   else 0.0
    s_de    = max(0.0, (_DE_MAX  - de)  / _DE_MAX)           if de    else 0.0
    s_grow  = min(1.0, max(0.0, growth / 0.10))               if growth else 0.0
    s_cr    = min(1.0, max(0.0, (cr - 1.0) / 2.0))           if cr    else 0.0

    # Poids Graham : valeur > dividende > bilan > croissance
    total = (
        s_per  * 0.25 +
        s_pbr  * 0.20 +
        s_div  * 0.25 +
        s_de   * 0.15 +
        s_grow * 0.10 +
        s_cr   * 0.05
    )
    return round(total * 100, 1)


class AgentScreenerMondial:
    """
    Scanne l'univers de ~150 titres via Yahoo Finance.
    Filtre selon critères Graham → top 10 candidats.
    """

    def __init__(self) -> None:
        self._lock       = threading.Lock()
        self._candidats: list[dict[str, Any]] = []
        self._ts_run:    datetime | None       = None
        self._ts_cache:  float                 = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_candidats(self) -> list[dict[str, Any]]:
        """Retourne les 10 derniers candidats (peut être vide si pas encore lancé)."""
        with self._lock:
            return list(self._candidats)

    def get_ts_run(self) -> datetime | None:
        with self._lock:
            return self._ts_run

    def scanner(self) -> list[dict[str, Any]]:
        """Lance le scan complet, met à jour les candidats, retourne les 10 meilleurs."""
        logger.info("[ScreenerMondial] Démarrage scan — %d titres dans l'univers", len(UNIVERSE))
        candidats = []

        for i, item in enumerate(UNIVERSE):
            ticker  = item["ticker"]
            info    = self._fetch_info(ticker)
            if not info:
                continue
            if not self._passe_filtres(info):
                continue
            score  = _graham_score(info)
            per    = _safe(info.get("trailingPE"))
            pbr    = _safe(info.get("priceToBook"))
            div    = _safe(info.get("dividendYield"), 0.0)
            de     = _safe(info.get("debtToEquity"))
            growth = _safe(info.get("revenueGrowth"))
            prix   = _safe(info.get("currentPrice"))

            candidats.append({
                "ticker":         ticker,
                "nom":            item["nom"],
                "marche":         item["marche"],
                "score_graham":   score,
                "per":            per,
                "pbr":            pbr,
                "dividende":      round(div * 100, 2) if div else None,
                "dette_equity":   de,
                "croissance_rev": round(growth * 100, 2) if growth is not None else None,
                "prix":           prix,
                "secteur":        info.get("sector"),
                "pays":           info.get("country"),
            })

            if i % 20 == 0:
                time.sleep(_BATCH_PAUSE)

        # Tri par score Graham décroissant → top 10
        top10 = sorted(candidats, key=lambda x: x["score_graham"], reverse=True)[:10]

        ts_now = datetime.now(timezone.utc)
        with self._lock:
            self._candidats = top10
            self._ts_run    = ts_now
            self._ts_cache  = time.monotonic()

        logger.info(
            "[ScreenerMondial] Scan terminé : %d filtrés → %d candidats | top: %s",
            len(candidats), len(top10),
            [c["ticker"] for c in top10],
        )
        return top10

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fetch_info(self, ticker: str) -> dict:
        try:
            info = yf.Ticker(ticker).info or {}
            return info
        except Exception as e:
            logger.debug("[ScreenerMondial] %s — erreur yfinance: %s", ticker, e)
            return {}

    def _passe_filtres(self, info: dict) -> bool:
        per    = _safe(info.get("trailingPE"))
        pbr    = _safe(info.get("priceToBook"))
        div    = _safe(info.get("dividendYield"), 0.0)
        de     = _safe(info.get("debtToEquity"))
        growth = _safe(info.get("revenueGrowth"))

        if per    is None or per    <= 0 or per    >= _PER_MAX:   return False
        if pbr    is None or pbr    <= 0 or pbr    >= _PBR_MAX:   return False
        if div    is None or div    < _DIV_MIN:                    return False
        if de     is not None and de >= _DE_MAX:                   return False
        if growth is not None and growth < _GROWTH_MIN:            return False
        return True


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: AgentScreenerMondial | None = None
_lock = threading.Lock()


def get_screener_mondial() -> AgentScreenerMondial:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AgentScreenerMondial()
    return _instance

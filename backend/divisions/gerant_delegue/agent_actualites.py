"""
Agent Actualités Pertinentes — Division Gérant Délégué

Filtre les actualités en 3 niveaux :
  CRITIQUE  — risque systémique immédiat → alerte Telegram immédiate
  IMPORTANT — décision macro ou événement marché significatif → alerte Telegram
  INFO      — veille sectorielle, logué seulement

Sources : NewsAPI · RSS banques centrales · Yahoo Finance headlines
Cache : 30 min actualités, 5 min flux urgents
"""
from __future__ import annotations

import hashlib
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
# Mots-clés par niveau de criticité
# ---------------------------------------------------------------------------

_CRITIQUE_KW = [
    "crash", "effondrement", "faillite", "défaut souverain", "bank run",
    "bank failure", "circuit breaker", "trading halt", "contagion",
    "black monday", "lehman", "systemic risk", "flash crash",
    "hawkish surprise", "emergency rate cut", "emergency hike",
    "guerre nucléaire", "nuclear", "sanctions", "gel avoirs",
    "suspension bourse", "circuit breaker", "vix spike", "vix > 40",
]

_IMPORTANT_KW = [
    "fed rate", "taux directeur", "inflation cpi", "pce inflation",
    "nonfarm payroll", "chômage", "unemployment", "pib", "gdp",
    "résultats trimestriels", "earnings beat", "earnings miss",
    "banque centrale", "central bank", "bce", "boj", "fed",
    "rally", "correction", "bear market", "recession",
    "opec", "oil", "pétrole", "wti", "brent",
    "dollar index", "dxy", "yuan", "yen carry",
    "emerging markets", "marchés émergents", "em selloff",
    "crypto crash", "bitcoin halving", "etf bitcoin",
    "spread crédit", "credit spread", "high yield",
]

_TICKERS_WATCHLIST = [
    "VPK.AS", "GTT.PA", "O", "JNJ", "VZ", "TEL.OL", "DNB.OL",
    "BIPC", "ADC", "DSY.PA", "SU.PA", "TTE.PA", "AIR.PA",
    "VIE.PA", "ENGIE.PA", "XYL",
    "AAPL", "MSFT", "TSLA", "NVDA", "META", "BTC-USD", "ETH-USD",
]

_CACHE_TTL_NORMAL  = 1800   # 30 min
_CACHE_TTL_CRITIQUE = 300   # 5 min si alerte récente


def _niveau_article(titre: str, description: str) -> str:
    texte = (titre + " " + (description or "")).lower()
    for kw in _CRITIQUE_KW:
        if kw in texte:
            return "CRITIQUE"
    for kw in _IMPORTANT_KW:
        if kw in texte:
            return "IMPORTANT"
    for ticker in _TICKERS_WATCHLIST:
        if ticker.lower().replace("-", "") in texte.replace("-", ""):
            return "IMPORTANT"
    return "INFO"


def _fingerprint(article: dict) -> str:
    key = (article.get("titre", "") + article.get("url", ""))[:120]
    return hashlib.md5(key.encode()).hexdigest()[:12]


class AgentActualites:
    """
    Surveille les actualités financières et envoie des alertes Telegram ciblées.
    """

    def __init__(self) -> None:
        self._lock          = threading.Lock()
        self._vus:          set[str] = set()
        self._cache:        list[dict] = []
        self._cache_ts:     float = 0.0
        self._dernier_critique: float = 0.0

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def _fetch_newsapi(self) -> list[dict]:
        try:
            from config import NEWS_API_KEY
            if not NEWS_API_KEY:
                return []
            import requests
            url = "https://newsapi.org/v2/everything"
            params = {
                "q":        "finance OR bourse OR market crash OR fed OR BCE OR crypto",
                "language": "fr,en",
                "sortBy":   "publishedAt",
                "pageSize": 30,
                "apiKey":   NEWS_API_KEY,
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
            return [
                {
                    "titre":       a.get("title", ""),
                    "description": a.get("description", ""),
                    "url":         a.get("url", ""),
                    "source":      a.get("source", {}).get("name", ""),
                    "publie_a":    a.get("publishedAt", ""),
                }
                for a in articles
            ]
        except Exception as e:
            logger.debug("[Actualites] NewsAPI: %s", e)
            return []

    def _fetch_yahoo_headlines(self) -> list[dict]:
        articles = []
        try:
            import yfinance as yf
            for ticker in ["^GSPC", "^FCHI", "BTC-USD"]:
                try:
                    news = yf.Ticker(ticker).news or []
                    for n in news[:5]:
                        ts = n.get("providerPublishTime") or 0
                        if ts > 86400:  # timestamp valide (> 02/01/1970)
                            pub = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                        else:
                            pub = datetime.now(timezone.utc).isoformat()
                        articles.append({
                            "titre":       n.get("title", ""),
                            "description": n.get("summary", ""),
                            "url":         n.get("link", ""),
                            "source":      "Yahoo Finance",
                            "publie_a":    pub,
                        })
                except Exception:
                    pass
        except Exception as e:
            logger.debug("[Actualites] Yahoo headlines: %s", e)
        return articles

    # ------------------------------------------------------------------
    # Analyse et filtrage
    # ------------------------------------------------------------------

    def analyser(self, forcer: bool = False) -> list[dict]:
        """Récupère, filtre et retourne la liste des actualités pertinentes."""
        now = time.monotonic()
        ttl = _CACHE_TTL_CRITIQUE if (now - self._dernier_critique) < 3600 else _CACHE_TTL_NORMAL

        if not forcer and self._cache and (now - self._cache_ts) < ttl:
            return self._cache

        bruts = self._fetch_newsapi() + self._fetch_yahoo_headlines()
        tries: list[dict] = []

        for art in bruts:
            fp = _fingerprint(art)
            if fp in self._vus:
                continue
            niveau = _niveau_article(art["titre"], art.get("description", ""))
            art["niveau"] = niveau
            art["fp"]     = fp
            tries.append(art)

        # Trier : CRITIQUE > IMPORTANT > INFO
        ordre = {"CRITIQUE": 0, "IMPORTANT": 1, "INFO": 2}
        tries.sort(key=lambda a: ordre.get(a["niveau"], 3))

        # Alertes Telegram pour les nouveaux articles CRITIQUE / IMPORTANT
        for art in tries:
            if art["fp"] in self._vus:
                continue
            self._vus.add(art["fp"])
            if art["niveau"] == "CRITIQUE":
                self._dernier_critique = time.monotonic()
                alerte(
                    f"ACTUALITÉ CRITIQUE",
                    f"📰 {art['titre']}\n"
                    f"Source : {art['source']}\n"
                    f"{art.get('url', '')}",
                    niveau="critique",
                )
            elif art["niveau"] == "IMPORTANT":
                alerte(
                    f"Actualité importante",
                    f"📰 {art['titre']}\n"
                    f"Source : {art['source']}",
                    niveau="warning",
                )

        with self._lock:
            self._cache    = tries
            self._cache_ts = now

        logger.info(
            "[Actualites] %d articles — CRITIQUE:%d IMPORTANT:%d INFO:%d",
            len(tries),
            sum(1 for a in tries if a["niveau"] == "CRITIQUE"),
            sum(1 for a in tries if a["niveau"] == "IMPORTANT"),
            sum(1 for a in tries if a["niveau"] == "INFO"),
        )
        return tries

    def critiques(self) -> list[dict]:
        return [a for a in self.analyser() if a["niveau"] == "CRITIQUE"]

    def importantes(self) -> list[dict]:
        return [a for a in self.analyser() if a["niveau"] in ("CRITIQUE", "IMPORTANT")]

    def etat(self) -> dict:
        cache = self._cache
        return {
            "nb_total":     len(cache),
            "nb_critique":  sum(1 for a in cache if a["niveau"] == "CRITIQUE"),
            "nb_important": sum(1 for a in cache if a["niveau"] == "IMPORTANT"),
            "nb_info":      sum(1 for a in cache if a["niveau"] == "INFO"),
            "derniere_maj": datetime.fromtimestamp(
                self._cache_ts, tz=timezone.utc
            ).isoformat() if self._cache_ts else None,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: AgentActualites | None = None
_lock = threading.Lock()


def get_agent_actualites() -> AgentActualites:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AgentActualites()
    return _instance

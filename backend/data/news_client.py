import sys
import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import NEWS_API_KEY

logger = logging.getLogger(__name__)

_BASE         = "https://newsapi.org/v2/everything"
_TTL          = 4 * 3600   # 4 heures
_MAX_REQ_HOUR = 10          # plan gratuit NewsAPI

_POSITIVE = frozenset([
    "surge", "rally", "gain", "rise", "jump", "beat", "record", "high",
    "growth", "profit", "soar", "upgrade", "bullish", "strong", "boost",
    "buy", "outperform", "positive", "upbeat", "expand",
])
_NEGATIVE = frozenset([
    "fall", "drop", "crash", "loss", "decline", "miss", "cut", "low",
    "weak", "risk", "fear", "sell", "downgrade", "bearish", "slump",
    "layoff", "fine", "lawsuit", "warning", "recession",
])


def _score(texts: list[str]) -> float:
    pos = neg = 0
    for t in texts:
        words = t.lower().split()
        pos += sum(1 for w in words if w in _POSITIVE)
        neg += sum(1 for w in words if w in _NEGATIVE)
    total = pos + neg
    return 0.0 if total == 0 else (pos - neg) / total


class _RateLimiter:
    """Fenêtre glissante : max N requêtes par heure."""

    def __init__(self, max_per_hour: int):
        self._max  = max_per_hour
        self._lock = threading.Lock()
        self._timestamps: list[float] = []

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            cutoff = now - 3600
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            if len(self._timestamps) < self._max:
                self._timestamps.append(now)
                return True
            remaining = 3600 - (now - self._timestamps[0])
            logger.warning(
                "NewsAPI rate limit (10 req/h) atteint — quota disponible dans %.0fs", remaining
            )
            return False


_rate_limiter = _RateLimiter(_MAX_REQ_HOUR)


class NewsClient:
    def __init__(self):
        self._lock      = threading.Lock()
        self._cache:     dict[str, float] = {}
        self._cache_ts:  dict[str, float] = {}
        self._in_flight: set[str]         = set()
        # 2 workers max : les fetches sont parallélisés mais contrôlés
        self._executor  = ThreadPoolExecutor(max_workers=2, thread_name_prefix="news-fetch")

    def _fetch(self, query: str) -> list[str] | None:
        """None = échec (rate limit ou erreur réseau). [] = 0 articles (résultat valide)."""
        if not NEWS_API_KEY:
            return None
        if not _rate_limiter.allow():
            return None
        try:
            r = requests.get(
                _BASE,
                params={
                    "q":        query,
                    "language": "en",
                    "sortBy":   "publishedAt",
                    "pageSize": 20,
                    "apiKey":   NEWS_API_KEY,
                },
                timeout=8,
            )
            r.raise_for_status()
            arts = r.json().get("articles", [])
            return [
                (a.get("title") or "") + " " + (a.get("description") or "")
                for a in arts
            ]
        except Exception as e:
            logger.warning("NewsAPI [%r]: %s", query, e)
            return None

    def _fetch_and_cache(self, query: str) -> None:
        """Worker arrière-plan : 1 appel API, mise à jour cache partagé.
        N'écrit dans le cache QUE si le fetch a réussi (évite de cacher un échec)."""
        try:
            texts = self._fetch(query)
            if texts is None:
                # rate limit ou erreur réseau — conserver la valeur existante en cache
                return
            score = _score(texts)
            with self._lock:
                self._cache[query]    = score
                self._cache_ts[query] = time.monotonic()
            logger.debug("News [%r] → %+.3f (%d articles)", query, score, len(texts))
        finally:
            with self._lock:
                self._in_flight.discard(query)

    def get_sentiment(self, query: str) -> float:
        """Score [-1, +1] lu depuis le cache partagé. Ne bloque jamais.
        Déclenche un refresh en arrière-plan si le cache est expiré ou absent."""
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(query, 0.0)
            ts     = self._cache_ts.get(query, 0.0)
            if ts and now - ts < _TTL:
                return cached            # cache valide — aucun appel API
            if query not in self._in_flight:
                self._in_flight.add(query)
                self._executor.submit(self._fetch_and_cache, query)
        # Retourne la valeur stale (ou 0.0) pendant que le fetch tourne en fond
        return cached


_instance: NewsClient | None = None
_lock = threading.Lock()


def get_news_client() -> NewsClient:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = NewsClient()
    return _instance

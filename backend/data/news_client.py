import sys
import time
import threading
import logging
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
        self._lock     = threading.Lock()
        self._cache:    dict = {}
        self._cache_ts: dict = {}

    def _fetch(self, query: str) -> list[str]:
        if not NEWS_API_KEY:
            return []
        if not _rate_limiter.allow():
            return []
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
            logger.warning(f"NewsAPI [{query!r}]: {e}")
            return []

    def get_sentiment(self, query: str) -> float:
        """Score in [-1.0, +1.0] for a news query. 0.0 on error or missing key."""
        now = time.monotonic()
        with self._lock:
            if query in self._cache and now - self._cache_ts[query] < _TTL:
                return self._cache[query]
        texts = self._fetch(query)
        score = _score(texts)
        with self._lock:
            self._cache[query]    = score
            self._cache_ts[query] = now
        logger.debug(f"News [{query!r}] → {score:+.3f} ({len(texts)} articles)")
        return score


_instance: NewsClient | None = None
_lock = threading.Lock()


def get_news_client() -> NewsClient:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = NewsClient()
    return _instance

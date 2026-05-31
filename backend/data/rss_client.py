import sys
import time
import threading
import logging
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

_TTL = 3_600  # 1 h — news headlines are stable within the hour

_HAWKISH = frozenset([
    "hike", "raise", "raised", "hawkish", "tighten", "tightening",
    "inflation", "overheat", "above target", "vigilant",
    "rate increase", "higher rates", "restrictive",
])
_DOVISH = frozenset([
    "cut", "cuts", "lower", "reduce", "ease", "easing", "dovish",
    "accommodation", "support", "below target", "downside",
    "recession", "slowdown", "concern", "pause", "hold",
])

_HEADERS = {"User-Agent": "king-fund/1.0"}


def _score(headlines: list[str]) -> float:
    """
    Sentiment from headlines: -1.0 hawkish (bearish equities)
                               +1.0 dovish  (bullish equities)
    """
    hawk = dove = 0
    for h in headlines:
        words = h.lower().split()
        hawk += sum(1 for w in words if w in _HAWKISH)
        dove += sum(1 for w in words if w in _DOVISH)
    total = hawk + dove
    return 0.0 if total == 0 else (dove - hawk) / total


class RSSClient:
    def __init__(self):
        self._lock     = threading.Lock()
        self._cache:    dict = {}
        self._cache_ts: dict = {}

    def _fetch(self, url: str) -> list[str]:
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            root = ET.fromstring(raw)

            # RSS 2.0
            titles = [
                (item.findtext("title") or "").strip()
                for item in root.iter("item")
                if (item.findtext("title") or "").strip()
            ]
            if not titles:
                # Atom 1.0
                for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                    t = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
                    if t:
                        titles.append(t)
            return titles[:15]
        except Exception as e:
            logger.debug(f"RSS [{url!r}]: {e}")
            return []

    def get_items(self, url: str, n: int = 10) -> list[str]:
        """Cached list of recent headlines from a feed URL."""
        now = time.monotonic()
        with self._lock:
            if url in self._cache and now - self._cache_ts[url] < _TTL:
                return self._cache[url][:n]
        items = self._fetch(url)
        with self._lock:
            self._cache[url]    = items
            self._cache_ts[url] = now
        logger.debug(f"RSS fetched {len(items)} items from {url!r}")
        return items[:n]

    def get_bias(self, url: str) -> float:
        """
        Hawkish/dovish bias from RSS headlines.
          -1.0 = very hawkish  (bearish for equities)
          +1.0 = very dovish   (bullish for equities)
           0.0 = neutral / unavailable
        """
        items = self.get_items(url)
        return _score(items) if items else 0.0


_instance: RSSClient | None = None
_lock = threading.Lock()


def get_rss_client() -> RSSClient:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = RSSClient()
    return _instance

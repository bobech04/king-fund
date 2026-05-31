import sys
import time
import threading
import logging
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FRED_API_KEY

logger = logging.getLogger(__name__)

_BASE   = "https://api.stlouisfed.org/fred/series/observations"
_TTL    = 86_400  # 24 h — FRED series are daily


class FredClient:
    def __init__(self):
        self._lock     = threading.Lock()
        self._cache:    dict = {}
        self._cache_ts: dict = {}

    def _fetch(self, series_id: str) -> float | None:
        if not FRED_API_KEY:
            return None
        try:
            r = requests.get(
                _BASE,
                params={
                    "series_id":  series_id,
                    "api_key":    FRED_API_KEY,
                    "file_type":  "json",
                    "limit":      5,
                    "sort_order": "desc",
                },
                timeout=8,
            )
            r.raise_for_status()
            for obs in r.json().get("observations", []):
                v = obs.get("value", ".")
                if v not in (".", ""):
                    return float(v)
        except Exception as e:
            logger.warning(f"FRED [{series_id}]: {e}")
        return None

    def _get(self, series_id: str, fallback: float = 0.0) -> float:
        now = time.monotonic()
        with self._lock:
            if series_id in self._cache and now - self._cache_ts[series_id] < _TTL:
                return self._cache[series_id]
        value = self._fetch(series_id)
        if value is None:
            value = fallback
        with self._lock:
            self._cache[series_id]    = value
            self._cache_ts[series_id] = now
        return value

    def fed_rate(self) -> float:
        """Federal Funds Effective Rate (%)."""
        return self._get("FEDFUNDS")

    def treasury_10y(self) -> float:
        """10-Year Treasury Constant Maturity Rate (%)."""
        return self._get("GS10")

    def macro_bias(self) -> float:
        """
        Float in [-1.0, +1.0].
          +1.0 = dovish (low rates)  → bullish for equities
          -1.0 = hawkish (high rates) → bearish for equities
          0.0 returned when no key or API failure.
        Neutral midpoint calibrated at 2.5 % average rate.
        """
        rate = self.fed_rate()
        t10y = self.treasury_10y()
        if rate == 0.0 and t10y == 0.0:
            return 0.0
        avg  = (rate + t10y) / 2.0
        bias = 1.0 - (avg / 2.5)         # 0 % → +1.0, 2.5 % → 0.0, 5 % → -1.0
        return max(-1.0, min(1.0, bias))


_instance: FredClient | None = None
_lock = threading.Lock()


def get_fred_client() -> FredClient:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = FredClient()
    return _instance

import sys
import time
import threading
import logging
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ALPHA_VANTAGE_API_KEY

logger = logging.getLogger(__name__)

_BASE = "https://www.alphavantage.co/query"
_TTL  = 300   # 5 min — free tier: 5 req/min, 500 req/day


class AlphaVantageClient:
    def __init__(self):
        self._lock     = threading.Lock()
        self._cache:    dict = {}
        self._cache_ts: dict = {}

    def _fetch_quote(self, symbol: str) -> dict:
        if not ALPHA_VANTAGE_API_KEY:
            return {}
        try:
            r = requests.get(
                _BASE,
                params={
                    "function": "GLOBAL_QUOTE",
                    "symbol":   symbol,
                    "apikey":   ALPHA_VANTAGE_API_KEY,
                },
                timeout=8,
            )
            r.raise_for_status()
            return r.json().get("Global Quote", {})
        except Exception as e:
            logger.warning(f"AlphaVantage [{symbol}]: {e}")
            return {}

    def get_quote(self, symbol: str) -> dict:
        now = time.monotonic()
        key = f"q_{symbol}"
        with self._lock:
            if key in self._cache and now - self._cache_ts[key] < _TTL:
                return self._cache[key]
        data = self._fetch_quote(symbol)
        with self._lock:
            self._cache[key]    = data
            self._cache_ts[key] = now
        return data

    def get_price_signal(self, symbol: str) -> float:
        """
        Directional signal in [-1.0, +1.0] from today's % change.
        Maps ±5 % → ±1.0. Returns 0.0 on error or missing data.
        """
        quote = self.get_quote(symbol)
        raw   = quote.get("10. change percent", "0%").replace("%", "").strip()
        try:
            pct = float(raw)
        except ValueError:
            return 0.0
        return max(-1.0, min(1.0, pct / 5.0))


_instance: AlphaVantageClient | None = None
_lock = threading.Lock()


def get_alphavantage_client() -> AlphaVantageClient:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AlphaVantageClient()
    return _instance

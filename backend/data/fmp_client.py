import sys
import time
import threading
import logging
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

# yfinance.Ticker.info scrapes Yahoo Finance — cache aggressively to avoid rate limits
_TTL = 3_600  # 1 h


class FMPClient:
    """
    Fundamental metrics client — backed by Yahoo Finance (yfinance).
    Public interface is unchanged from the former FMP version so all
    Division Investissement traders continue to work without modification.
    """

    def __init__(self):
        self._lock     = threading.Lock()
        self._cache:    dict = {}
        self._cache_ts: dict = {}

    def _fetch_metrics(self, symbol: str) -> dict:
        try:
            return yf.Ticker(symbol).info or {}
        except Exception as e:
            logger.warning(f"yfinance fundamentals [{symbol}]: {e}")
            return {}

    def get_metrics(self, symbol: str) -> dict:
        now = time.monotonic()
        with self._lock:
            if symbol in self._cache and now - self._cache_ts[symbol] < _TTL:
                return self._cache[symbol]
        data = self._fetch_metrics(symbol)
        with self._lock:
            self._cache[symbol]    = data
            self._cache_ts[symbol] = now
        return data

    def fundamental_signal(self, symbol: str) -> float:
        """
        Score in [-1.0, +1.0] from Yahoo Finance TTM fundamentals.
          +1.0 = solid  → justifies aggressive position
          -1.0 = stretched / deteriorating → reduce exposure
          0.0  = unavailable (crypto tickers) or neutral.
        Composite of: trailing P/E, ROE, revenue growth (equal weight, ±0.5 each).
        """
        if "-" in symbol:   # crypto tickers have no equity fundamentals
            return 0.0
        m = self.get_metrics(symbol)
        if not m:
            return 0.0

        score  = 0.0
        pe     = m.get("trailingPE")
        roe    = m.get("returnOnEquity")
        growth = m.get("revenueGrowth")

        if pe is not None and pe > 0:
            # P/E < 15 = great (+0.5), 25 = neutral, > 50 = stretched (-0.5)
            score += max(-0.5, min(0.5, (25.0 - pe) / 50.0))
        if roe is not None:
            # ROE 30 % = full positive, 0 % = neutral, negative ROE = full negative
            score += max(-0.5, min(0.5, roe / 0.30))
        if growth is not None:
            # +20 % revenue growth = full positive, 0 % = neutral, -20 % = full negative
            score += max(-0.5, min(0.5, growth / 0.20))

        return max(-1.0, min(1.0, score))


_instance: FMPClient | None = None
_lock = threading.Lock()


def get_fmp_client() -> FMPClient:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = FMPClient()
    return _instance

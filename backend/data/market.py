import sys
import time
import logging
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MARKET_CACHE_TTL

logger = logging.getLogger(__name__)


class MarketData:
    """
    Single point of contact for all market data.
    Fetches prices in one batch call per tick, caches the result, and falls back
    to the last known values if Yahoo Finance is unreachable.
    """

    def __init__(self, symbols: list):
        self.symbols = symbols
        self._cache: dict = {}
        self._cache_ts: float = 0.0

    # ------------------------------------------------------------------
    # Current prices
    # ------------------------------------------------------------------

    def get_prices(self) -> dict:
        now = time.monotonic()
        if self._cache and now - self._cache_ts < MARKET_CACHE_TTL:
            return self._cache.copy()
        try:
            fresh = self._fetch_prices()
            if fresh:
                self._cache.update(fresh)
                self._cache_ts = now
                logger.debug(f"Prices refreshed for {list(fresh.keys())}")
        except Exception as e:
            logger.warning(f"Price fetch failed, using cache: {e}")
        return self._cache.copy()

    def _fetch_prices(self) -> dict:
        data = yf.download(
            self.symbols,
            period="1d",
            interval="1m",
            progress=False,
            auto_adjust=True,
        )
        prices = {}
        for sym in self.symbols:
            try:
                if len(self.symbols) > 1:
                    close = data["Close"][sym].dropna()
                else:
                    close = data["Close"].dropna()
                if not close.empty:
                    prices[sym] = float(close.iloc[-1])
            except Exception as e:
                logger.warning(f"Could not parse price for {sym}: {e}")
        return prices

    # ------------------------------------------------------------------
    # Historical close prices (used by traders to bootstrap indicators)
    # ------------------------------------------------------------------

    def get_history(self, symbol: str, period: str = "5d", interval: str = "1h") -> list:
        """
        Returns a list of close prices (oldest → newest).
        5 days at 1-hour interval gives ~35 data points, enough for RSI-14 and MACD-26.
        Raises no exception — returns [] on failure.
        """
        try:
            hist = yf.Ticker(symbol).history(period=period, interval=interval)
            return hist["Close"].dropna().tolist()
        except Exception as e:
            logger.warning(f"Could not fetch history for {symbol}: {e}")
            return []

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MeanReversionStrategy
from data.news_client import get_news_client
from data.alphavantage_client import get_alphavantage_client


class Trader(BaseTrader):
    """Expert Sectoriel Social — sentiment News + signal Alpha Vantage."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name          = "TIDE"
        self.strategy      = "Mean reversion lent · META + News/AV"
        self._symbol       = "META"
        self._strat        = MeanReversionStrategy(window=25, k=2.0)
        self._history:list = []
        self._news         = get_news_client()
        self._av           = get_alphavantage_client()
        self._query        = "meta META facebook instagram social media advertising"

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig = self._strat.signal(self._history)
        ext = (self._news.get_sentiment(self._query) + self._av.get_price_signal(self._symbol)) / 2.0
        if sig == "buy":
            return self._buy(self._symbol, 0.35, prices) if ext > -0.4 else self._hold()
        if sig == "sell":
            return self._sell(self._symbol, 0.7) if ext < 0.4 else self._hold()
        return self._hold()

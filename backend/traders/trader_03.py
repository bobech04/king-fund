import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MomentumStrategy
from data.news_client import get_news_client
from data.alphavantage_client import get_alphavantage_client
from data.liquidity_client import get_liquidity_client


class Trader(BaseTrader):
    """Expert Sectoriel Crypto — sentiment News + Alpha Vantage + liquidity regime."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name          = "CHASE"
        self.strategy      = "Momentum crypto · BTC + News/AV + Liquidité"
        self._symbol       = "BTC-USD"
        self._strat        = MomentumStrategy(short_window=7, long_window=25, threshold=0.006)
        self._history:list = []
        self._news         = get_news_client()
        self._av           = get_alphavantage_client()
        self._liq          = get_liquidity_client()
        self._query        = "bitcoin BTC cryptocurrency market"

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig = self._strat.signal(self._history)
        ext = (self._news.get_sentiment(self._query) + self._av.get_price_signal(self._symbol)) / 2.0
        liq = self._liq.liquidity_bias()  # crypto is highly sensitive to global liquidity
        if sig == "buy":
            # In tight liquidity crypto dumps hard — scale down position
            fraction = max(0.15, 0.5 + liq * 0.3)
            return self._buy(self._symbol, fraction, prices) if ext > -0.4 else self._hold()
        if sig == "sell":
            # In a crunch, sell faster and heavier
            fraction = min(1.0, 0.8 + max(0.0, -liq) * 0.2)
            return self._sell(self._symbol, fraction) if ext < 0.4 else self._hold()
        return self._hold()

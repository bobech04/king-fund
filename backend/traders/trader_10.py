import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MeanReversionStrategy


class Trader(BaseTrader):
    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "VEGA"
        self.strategy = "Mean reversion · GOOGL"
        self._symbol  = "GOOGL"
        self._strat   = MeanReversionStrategy(window=20, k=1.5)
        self._history: list = []

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig = self._strat.signal(self._history)
        if sig == "buy":
            return self._buy(self._symbol, 0.4, prices)
        if sig == "sell":
            return self._sell(self._symbol, 0.8)
        return self._hold()

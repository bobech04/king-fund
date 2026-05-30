import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import BreakoutStrategy


class Trader(BaseTrader):
    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "SPIKE"
        self.strategy = "Breakout long · ETH"
        self._symbol  = "ETH-USD"
        self._strat   = BreakoutStrategy(window=20)
        self._history: list = []

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig = self._strat.signal(self._history)
        if sig == "buy":
            return self._buy(self._symbol, 0.5, prices)
        if sig == "sell":
            return self._sell(self._symbol, 1.0)
        return self._hold()

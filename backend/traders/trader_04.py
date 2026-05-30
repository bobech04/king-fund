import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MomentumStrategy


class Trader(BaseTrader):
    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "ALPHA"
        self.strategy = "Momentum prudent · AAPL"
        self._symbol  = "AAPL"
        self._strat   = MomentumStrategy(short_window=10, long_window=30, threshold=0.005)
        self._history: list = []

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig = self._strat.signal(self._history)
        if sig == "buy":
            return self._buy(self._symbol, 0.3, prices)
        if sig == "sell":
            return self._sell(self._symbol, 0.5)
        return self._hold()

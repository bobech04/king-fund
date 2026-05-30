import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MomentumStrategy


class Trader(BaseTrader):
    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "SURGE"
        self.strategy = "Momentum modéré · NVDA"
        self._symbol  = "NVDA"
        self._strat   = MomentumStrategy(short_window=5, long_window=20, threshold=0.005)
        self._history: list = []

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig = self._strat.signal(self._history)
        if sig == "buy":
            return self._buy(self._symbol, 0.6, prices)
        if sig == "sell":
            return self._sell(self._symbol, 1.0)
        return self._hold()

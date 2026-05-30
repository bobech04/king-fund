import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import RSIStrategy


class Trader(BaseTrader):
    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "NEXUS"
        self.strategy = "RSI classique · AMZN"
        self._symbol  = "AMZN"
        self._strat   = RSIStrategy(period=14, oversold=30.0, overbought=70.0)
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
            return self._sell(self._symbol, 0.8)
        return self._hold()

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MACDStrategy


class Trader(BaseTrader):
    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "TREND"
        self.strategy = "MACD classique · MSFT"
        self._symbol  = "MSFT"
        self._strat   = MACDStrategy(fast=12, slow=26, signal_period=9)
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

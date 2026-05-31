import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import RSIStrategy
from data.fred_client import get_fred_client


class Trader(BaseTrader):
    """Banque Centrale — FRED macro bias modulates position size."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "PRISM"
        self.strategy = "RSI lent prudent · AAPL + FRED"
        self._symbol  = "AAPL"
        self._strat   = RSIStrategy(period=21, oversold=30.0, overbought=70.0)
        self._history: list = []
        self._fred    = get_fred_client()

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig  = self._strat.signal(self._history)
        bias = self._fred.macro_bias()
        if sig == "buy":
            fraction = 0.3 * max(0.3, 1.0 + bias * 0.5)
            return self._buy(self._symbol, min(0.5, fraction), prices)
        if sig == "sell":
            fraction = 0.5 * max(0.5, 1.0 - bias * 0.3)
            return self._sell(self._symbol, min(1.0, fraction))
        return self._hold()

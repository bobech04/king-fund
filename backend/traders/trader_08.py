import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MeanReversionStrategy
from data.fmp_client import get_fmp_client


class Trader(BaseTrader):
    """Division Investissement — FMP fundamentals scale position size."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "BOUNCE"
        self.strategy = "Mean reversion agressif · TSLA + FMP"
        self._symbol  = "TSLA"
        self._strat   = MeanReversionStrategy(window=10, k=1.0)
        self._history: list = []
        self._fmp     = get_fmp_client()

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig  = self._strat.signal(self._history)
        fund = self._fmp.fundamental_signal(self._symbol)
        if sig == "buy":
            fraction = 0.8 * max(0.4, 1.0 + fund * 0.4)
            return self._buy(self._symbol, min(1.0, fraction), prices)
        if sig == "sell":
            return self._sell(self._symbol, 1.0)
        return self._hold()

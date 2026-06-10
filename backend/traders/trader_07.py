import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MeanReversionStrategy
from data.fmp_client import get_fmp_client
from data.liquidity_client import get_liquidity_client


class Trader(BaseTrader):
    """Groupe A — EU Valeurs Sous-suivies · AIR.PA mean reversion prudent."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "ZEN"
        self.strategy = "Mean Reversion w=20 k=2 · AIR.PA + FMP"
        self._symbol  = "AIR.PA"
        self._strat   = MeanReversionStrategy(window=20, k=2.0)
        self._history: list = []
        self._fmp     = get_fmp_client()
        self._liq     = get_liquidity_client()

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig  = self._strat.signal(self._history)
        fund = self._fmp.fundamental_signal(self._symbol)
        liq  = self._liq.liquidity_bias()
        if sig == "buy" and liq > -0.50:
            fraction = 0.55 * max(0.3, 1.0 + fund * 0.2)
            return self._buy(self._symbol, min(0.70, fraction), prices)
        if sig == "sell":
            return self._sell(self._symbol, 1.0)
        return self._hold()

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MeanReversionStrategy
from data.fmp_client import get_fmp_client
from data.liquidity_client import get_liquidity_client


class Trader(BaseTrader):
    """Groupe A — EU Valeurs Sous-suivies · DSY.PA mean reversion modéré."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "BOUNCE"
        self.strategy = "Mean Reversion w=10 k=1.5 · DSY.PA + FMP"
        self._symbol  = "DSY.PA"
        self._strat   = MeanReversionStrategy(window=10, k=1.5)
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
        if sig == "buy":
            fraction = 0.60 * max(0.3, 1.0 + fund * 0.25 + liq * 0.15)
            return self._buy(self._symbol, min(0.75, fraction), prices)
        if sig == "sell":
            held = self.portfolio.positions.get(self._symbol, 0)
            if held > 0:
                return self._sell(self._symbol, 1.0)
        return self._hold()

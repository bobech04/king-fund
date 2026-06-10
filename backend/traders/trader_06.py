import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MomentumStrategy
from data.fmp_client import get_fmp_client
from data.liquidity_client import get_liquidity_client


class Trader(BaseTrader):
    """Groupe A — EU Valeurs Sous-suivies · SU.PA momentum modéré + FMP."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "APEX"
        self.strategy = "Momentum modéré · SU.PA + FMP + Liquidité"
        self._symbol  = "SU.PA"
        self._strat   = MomentumStrategy(short_window=5, long_window=15, threshold=0.006)
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
        if sig == "buy" and fund > -0.20:
            fraction = 0.70 * max(0.3, 1.0 + fund * 0.3 + liq * 0.1)
            return self._buy(self._symbol, min(0.85, fraction), prices)
        if sig == "sell":
            return self._sell(self._symbol, 0.9)
        return self._hold()

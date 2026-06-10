import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MomentumStrategy
from data.fmp_client import get_fmp_client
from data.liquidity_client import get_liquidity_client


class Trader(BaseTrader):
    """Groupe A — EU Valeurs Sous-suivies · TEL.OL momentum + FMP."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "CHASE"
        self.strategy = "Momentum · TEL.OL + FMP + Liquidité"
        self._symbol  = "TEL.OL"
        self._strat   = MomentumStrategy(short_window=4, long_window=12, threshold=0.007)
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
        if sig == "buy" and liq > -0.40:
            fraction = 0.65 * max(0.3, 1.0 + fund * 0.25 + liq * 0.15)
            return self._buy(self._symbol, min(0.80, fraction), prices)
        if sig == "sell":
            return self._sell(self._symbol, 1.0)
        return self._hold()

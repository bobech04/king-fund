import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MomentumStrategy
from data.fmp_client import get_fmp_client
from data.liquidity_client import get_liquidity_client


class Trader(BaseTrader):
    """Groupe A — EU Valeurs Sous-suivies · BIPC momentum infrastructure."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "EURO-MOM"
        self.strategy = "Momentum MA3/12 · BIPC Infrastructure + FMP"
        self._symbol  = "BIPC"
        self._strat   = MomentumStrategy(short_window=3, long_window=12, threshold=0.006)
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
        expert_sig = self._experts.get_signal(self._symbol)
        if sig == "buy" and expert_sig > -0.40 and liq > -0.30:
            frac = self.base_fraction * (1.0 + liq * 0.2 + fund * 0.15)
            return self._buy(self._symbol, min(frac, 0.65), prices)
        if sig == "sell":
            held = self.portfolio.positions.get(self._symbol, 0)
            if held > 0:
                return self._sell(self._symbol, 1.0)
        return self._hold()

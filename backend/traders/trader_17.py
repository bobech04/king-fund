import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import RSIStrategy
from data.liquidity_client import get_liquidity_client


_HOWELL_THRESHOLD = -0.30   # signal Howell : réduire exposition émergents


class Trader(BaseTrader):
    """Groupe B — Macro Global Dalio · EEM émergents réduit Howell."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "PRISM"
        self.strategy = "RSI 9 · EEM Émergents · exposition réduite signal Howell"
        self._symbol  = "EEM"
        self._strat   = RSIStrategy(period=9, oversold=25, overbought=75)
        self._history: list = []
        self._liq     = get_liquidity_client()

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig = self._strat.signal(self._history)
        liq = self._liq.liquidity_bias()
        # Signal Howell : sommet appétit risque → couper exposition émergents
        howell_caution = liq < _HOWELL_THRESHOLD
        if sig == "buy":
            fraction = 0.25 if howell_caution else 0.55
            return self._buy(self._symbol, fraction, prices)
        if sig == "sell":
            return self._sell(self._symbol, 1.0)
        return self._hold()

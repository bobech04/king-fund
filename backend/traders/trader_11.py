import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MeanReversionStrategy
from data.liquidity_client import get_liquidity_client


class Trader(BaseTrader):
    """Groupe B — Macro Global Dalio · SPY mean reversion core."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "NOVA"
        self.strategy = "Mean Reversion w=20 k=2 · SPY Risk Parity Core"
        self._symbol  = "SPY"
        self._strat   = MeanReversionStrategy(window=20, k=2.0)
        self._history: list = []
        self._liq     = get_liquidity_client()

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig = self._strat.signal(self._history)
        liq = self._liq.liquidity_bias()
        if sig == "buy":
            fraction = 0.65 * max(0.3, 1.0 + liq * 0.25)
            return self._buy(self._symbol, min(0.80, fraction), prices)
        if sig == "sell":
            return self._sell(self._symbol, 1.0)
        return self._hold()

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MACDStrategy
from data.liquidity_client import get_liquidity_client


_HOWELL_THRESHOLD = -0.30


class Trader(BaseTrader):
    """Groupe B — Macro Global Dalio · INDA Inde MACD réduit Howell."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "TREND"
        self.strategy = "MACD 12/26/9 · INDA Inde · exposition réduite signal Howell"
        self._symbol  = "INDA"
        self._strat   = MACDStrategy(fast=12, slow=26, signal_period=9)
        self._history: list = []
        self._liq     = get_liquidity_client()

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig = self._strat.signal(self._history)
        liq = self._liq.liquidity_bias()
        howell_caution = liq < _HOWELL_THRESHOLD
        if sig == "buy":
            fraction = 0.25 if howell_caution else 0.55
            return self._buy(self._symbol, fraction, prices)
        if sig == "sell":
            return self._sell(self._symbol, 1.0)
        return self._hold()

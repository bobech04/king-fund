import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import RSIStrategy
from data.liquidity_client import get_liquidity_client


class Trader(BaseTrader):
    """Groupe B — Macro Global Dalio · TLT obligations long terme safe haven."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "ORACLE"
        self.strategy = "RSI 14 · TLT Obligations LT Dalio risk parity"
        self._symbol  = "TLT"
        self._strat   = RSIStrategy(period=14, oversold=35, overbought=65)
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
            # TLT monte en risk-off → amplifier si liquidité tendue
            fraction = 0.55 + max(0.0, -liq) * 0.25
            return self._buy(self._symbol, min(0.80, fraction), prices)
        if sig == "sell":
            return self._sell(self._symbol, 0.85)
        return self._hold()

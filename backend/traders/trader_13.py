import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import RSIStrategy
from data.liquidity_client import get_liquidity_client


class Trader(BaseTrader):
    """Groupe B — Macro Global Dalio · GLD RSI safe haven."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "HAWK"
        self.strategy = "RSI 14 · GLD Or safe haven Dalio"
        self._symbol  = "GLD"
        self._strat   = RSIStrategy(period=14, oversold=30, overbought=70)
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
            # Or s'apprécie quand liquidité se resserre — amplifier en crise
            fraction = 0.60 + max(0.0, -liq) * 0.20
            return self._buy(self._symbol, min(0.85, fraction), prices)
        if sig == "sell" and liq > 0.20:
            # Ne vend l'or que si liquidité ample (marché risk-on)
            return self._sell(self._symbol, 0.80)
        return self._hold()

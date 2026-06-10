import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import RSIStrategy
from data.fmp_client import get_fmp_client
from data.liquidity_client import get_liquidity_client


class Trader(BaseTrader):
    """Groupe A — EU Valeurs Sous-suivies · DNB.OL value fondamentale RSI."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "ALPHA"
        self.strategy = "Value fondamentale RSI · DNB.OL + FMP"
        self._symbol  = "DNB.OL"
        self._strat   = RSIStrategy(period=14, oversold=35, overbought=65)
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
        if sig == "buy" and fund >= 0.0:
            # Valeur : n'achète que si fondamentaux positifs
            fraction = 0.6 * (1.0 + fund * 0.4)
            return self._buy(self._symbol, min(0.80, fraction), prices)
        if sig == "sell":
            return self._sell(self._symbol, 0.8)
        return self._hold()

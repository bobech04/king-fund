import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import RSIStrategy
from data.fmp_client import get_fmp_client
from data.liquidity_client import get_liquidity_client


class Trader(BaseTrader):
    """Groupe A — EU Valeurs Sous-suivies · ADC REIT value RSI."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "VEGA"
        self.strategy = "Value RSI · ADC REIT + FMP fondamentaux"
        self._symbol  = "ADC"
        self._strat   = RSIStrategy(period=14, oversold=30, overbought=70)
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
            # REIT : sensible aux taux → liquidity bias crucial
            if liq < -0.50:
                return self._hold()
            fraction = 0.60 * max(0.3, 1.0 + fund * 0.35)
            return self._buy(self._symbol, min(0.75, fraction), prices)
        if sig == "sell":
            return self._sell(self._symbol, 0.85)
        return self._hold()

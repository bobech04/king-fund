import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MACDStrategy
from data.morning_brief import get_morning_brief


class Trader(BaseTrader):
    """
    Morning Brief — Claude génère chaque matin un outlook marché global.
    Le signal Claude prime ; MACD sert de confirmation intraday.
    """

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "TREND"
        self.strategy = "Morning Brief · MSFT + Claude"
        self._symbol  = "MSFT"
        self._strat   = MACDStrategy(fast=12, slow=26, signal_period=9)
        self._history: list = []
        self._brief   = get_morning_brief()

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig       = self._strat.signal(self._history)
        direction = self._brief.direction_signal(prices)   # -1.0 bearish → +1.0 bullish

        # Claude high conviction overrides technical signal
        if direction > 0.6 and not self.portfolio.positions.get(self._symbol):
            return self._buy(self._symbol, 0.25, prices)
        if direction < -0.6 and self.portfolio.positions.get(self._symbol):
            return self._sell(self._symbol, 1.0)

        # Normal path: technical signal filtered by Claude direction
        if sig == "buy" and direction >= -0.2:
            return self._buy(self._symbol, 0.5, prices)
        if sig == "sell" and direction <= 0.2:
            return self._sell(self._symbol, 1.0)
        return self._hold()

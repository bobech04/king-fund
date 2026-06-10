import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import MeanReversionStrategy
from data.liquidity_client import get_liquidity_client


def _bertez_mode() -> str:
    try:
        from divisions.investissement.agent_bertez import get_agent_bertez
        return get_agent_bertez().analyse().get("mode", "NEUTRE")
    except Exception:
        return "NEUTRE"


class Trader(BaseTrader):
    """Groupe C — Protecteurs Taleb · SPY mean reversion bear défensif."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "CROSS"
        self.strategy = "Mean Reversion bear · SPY · cash si crise Bertez"
        self._symbol  = "SPY"
        self._strat   = MeanReversionStrategy(window=15, k=1.8)
        self._history: list = []
        self._liq     = get_liquidity_client()

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        liq = self._liq.liquidity_bias()
        is_defensive = liq < -0.40 or _bertez_mode() in ("STAGFLATION", "DEFENSIF")
        if is_defensive:
            held = self.portfolio.positions.get(self._symbol, 0)
            if held > 0:
                return self._sell(self._symbol, 1.0)
            return self._hold()
        sig = self._strat.signal(self._history)
        if sig == "buy" and liq > -0.20:
            return self._buy(self._symbol, 0.20, prices)
        if sig == "sell":
            return self._sell(self._symbol, 1.0)
        return self._hold()

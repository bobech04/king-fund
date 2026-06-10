import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import BreakoutStrategy
from data.liquidity_client import get_liquidity_client


def _bertez_mode() -> str:
    try:
        from divisions.investissement.agent_bertez import get_agent_bertez
        return get_agent_bertez().analyse().get("mode", "NEUTRE")
    except Exception:
        return "NEUTRE"


class Trader(BaseTrader):
    """Groupe C — Protecteurs Taleb · GLD breakout agressif barbell final."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "FURY"
        self.strategy = "Breakout agressif w=10 · GLD Or barbell Bertez"
        self._symbol  = "GLD"
        self._strat   = BreakoutStrategy(window=10)
        self._history: list = []
        self._liq     = get_liquidity_client()

    def decide(self, prices: dict) -> dict:
        price = prices.get(self._symbol, 0.0)
        if price <= 0:
            return self._hold()
        self._history.append(price)
        sig  = self._strat.signal(self._history)
        liq  = self._liq.liquidity_bias()
        mode = _bertez_mode()
        if sig == "buy":
            if mode == "STAGFLATION":
                frac = 0.90
            elif liq < -0.20:
                frac = 0.70
            else:
                frac = 0.45
            return self._buy(self._symbol, frac, prices)
        if sig == "sell" and mode not in ("STAGFLATION",) and liq > 0.20:
            return self._sell(self._symbol, 1.0)
        return self._hold()

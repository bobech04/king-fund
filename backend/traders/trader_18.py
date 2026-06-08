import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import BreakoutStrategy


class Trader(BaseTrader):
    """EU Breakout Trader — SU.PA / TEL.OL / DNB.OL via canal Donchian."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name     = "EURO-BRK"
        self.strategy = "Breakout Donchian15 · SU.PA TEL.OL DNB.OL · BCE+Bertez"
        self._symbols = ["SU.PA", "TEL.OL", "DNB.OL"]
        self._symbol  = "SU.PA"   # primary pour le price-change check du moteur
        self._strat   = BreakoutStrategy(window=15)
        self._history: dict[str, list] = {s: [] for s in self._symbols}

    def decide(self, prices: dict) -> dict:
        for sym in self._symbols:
            price = prices.get(sym, 0.0)
            if price <= 0:
                continue
            self._history[sym].append(price)
            sig = self._strat.signal(self._history[sym])

            expert_sig = self._experts.get_signal(sym)
            liq        = self._liq.liquidity_bias()

            if sig == "buy" and expert_sig > -0.40 and liq > -0.30:
                frac = self.base_fraction * (1.0 + liq * 0.2)
                return self._buy(sym, min(frac, 0.60), prices)

            if sig == "sell":
                held = self.portfolio.positions.get(sym, 0)
                if held > 0:
                    return self._sell(sym, 0.9)

        return self._hold()

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from traders.base_trader import BaseTrader
from strategies import RSIStrategy
from data.liquidity_client import get_liquidity_client


def _bertez_mode() -> str:
    try:
        from divisions.investissement.agent_bertez import get_agent_bertez
        return get_agent_bertez().analyse().get("mode", "NEUTRE")
    except Exception:
        return "NEUTRE"


class Trader(BaseTrader):
    """Groupe C — Protecteurs Taleb · GLD + TLT barbell Or obligations."""

    def __init__(self, trader_id: int, starting_capital: float):
        super().__init__(trader_id, starting_capital)
        self.name      = "BLAST"
        self.strategy  = "Barbell RSI · GLD + TLT · Or + Obligations Taleb"
        self._symbol   = "GLD"
        self._symbol2  = "TLT"
        self._strat    = RSIStrategy(period=14, oversold=30, overbought=70)
        self._history:  dict[str, list] = {"GLD": [], "TLT": []}
        self._liq      = get_liquidity_client()

    def decide(self, prices: dict) -> dict:
        liq  = self._liq.liquidity_bias()
        mode = _bertez_mode()
        for sym in [self._symbol, self._symbol2]:
            price = prices.get(sym, 0.0)
            if price <= 0:
                continue
            self._history[sym].append(price)
            sig = self._strat.signal(self._history[sym])
            if sig == "buy":
                if sym == "GLD":
                    frac = 0.70 if mode == "STAGFLATION" else (0.55 if liq < -0.20 else 0.40)
                else:  # TLT
                    frac = 0.40 if liq < -0.20 else 0.25
                return self._buy(sym, frac, prices)
            if sig == "sell":
                held = self.portfolio.positions.get(sym, 0)
                if held > 0 and mode not in ("STAGFLATION",) and liq > 0.15:
                    return self._sell(sym, 0.80)
        return self._hold()

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.portfolio import Portfolio


class BaseTrader:
    """
    Base class for all 30 AI traders.

    Subclasses must override `decide()` to implement a trading strategy.
    The engine calls `decide(prices)` once per tick and applies the returned action.

    Returned action dict:
        {
            "action": "buy" | "sell" | "hold",
            "symbol": str,          # ticker, e.g. "AAPL" or "BTC-USD"
            "amount": float,        # number of units (shares / coins), NOT euros
        }

    Rules enforced by the engine (not here):
    - "buy"  → rejected if cost > portfolio.cash
    - "sell" → capped at quantity actually held
    - Any unknown action is treated as "hold"
    """

    def __init__(self, trader_id: int, starting_capital: float):
        self.id: int = trader_id
        self.name: str = f"Trader {trader_id:02d}"
        self.strategy: str = "Hold"
        self.portfolio: Portfolio = Portfolio(starting_capital)

    # ------------------------------------------------------------------
    # Strategy interface — override in subclasses
    # ------------------------------------------------------------------

    def decide(self, prices: dict) -> dict:
        return {"action": "hold", "symbol": "", "amount": 0}

    # ------------------------------------------------------------------
    # Helpers available to all subclasses
    # ------------------------------------------------------------------

    def _buy(self, symbol: str, fraction: float, prices: dict) -> dict:
        """
        Place a buy order for `fraction` of available cash on `symbol`.
        fraction=1.0 means "go all-in", fraction=0.1 means "10% of cash".
        """
        fraction = max(0.0, min(fraction, 1.0))
        price = prices.get(symbol, 0.0)
        if price <= 0:
            return {"action": "hold", "symbol": symbol, "amount": 0}
        amount = (self.portfolio.cash * fraction) / price
        return {"action": "buy", "symbol": symbol, "amount": amount}

    def _sell(self, symbol: str, fraction: float = 1.0) -> dict:
        """
        Place a sell order for `fraction` of the held quantity of `symbol`.
        fraction=1.0 means "sell everything held".
        """
        fraction = max(0.0, min(fraction, 1.0))
        held = self.portfolio.positions.get(symbol, 0.0)
        return {"action": "sell", "symbol": symbol, "amount": held * fraction}

    def _hold(self) -> dict:
        return {"action": "hold", "symbol": "", "amount": 0}

    def _price_change(self, symbol: str, prices: dict, window: int = 1) -> float:
        """
        Returns the % change of symbol over the last `window` ticks
        using the portfolio's internal price cache.
        Only works once the cache has been populated by at least one tick.
        """
        cache = self.portfolio._price_cache
        current = prices.get(symbol, cache.get(symbol, 0.0))
        previous = cache.get(symbol, current)
        if previous == 0:
            return 0.0
        return (current - previous) / previous

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id} name={self.name} strategy={self.strategy}>"

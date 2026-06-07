import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.portfolio import Portfolio
from data.liquidity_client import get_liquidity_client
from data.expert_signal_client import get_expert_signal_client
from config import get_grade, get_grade_fraction


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

    Available signal helpers:
    - self._liq.liquidity_bias()          → global liquidity [-1, +1]
    - self._experts.get_signal(symbol)    → expert consensus [-1, +1]
    - self.grade                          → current performance tier (str)
    - self.base_fraction                  → recommended trade size fraction for this grade
    """

    def __init__(self, trader_id: int, starting_capital: float):
        self.id: int = trader_id
        self.name: str = f"Trader {trader_id:02d}"
        self.strategy: str = "Hold"
        self.portfolio: Portfolio = Portfolio(starting_capital)
        self._starting_capital: float = starting_capital
        self._liq     = get_liquidity_client()       # global liquidity regime
        self._experts = get_expert_signal_client()   # sectoral + CB expert signals
        self.sitg_budget: float = 1.0                # Skin-in-the-Game : multiplicateur dynamique [0.25, 1.75]
        self._feedback_cautious: bool = False        # True si taux de réussite < 40%
        self._win_rate: float = 1.0                  # taux de réussite sur les 20 derniers cycles

    @property
    def grade(self) -> str:
        """Current performance tier: RECRUE → JUNIOR → SENIOR → ELITE → LÉGENDE."""
        pnl_pct = (self.portfolio.portfolio_value / self._starting_capital - 1.0) * 100
        return get_grade(pnl_pct)

    @property
    def base_fraction(self) -> float:
        """Recommended fraction of available cash to deploy per trade for this grade."""
        pnl_pct = (self.portfolio.portfolio_value / self._starting_capital - 1.0) * 100
        return get_grade_fraction(pnl_pct)

    # ------------------------------------------------------------------
    # Strategy interface — override in subclasses
    # ------------------------------------------------------------------

    def refresh_feedback(self, db_path: Path) -> None:
        """Lit les 20 derniers cycles buy→sell dans SQLite et active le mode prudent si taux < 40%."""
        try:
            conn = sqlite3.connect(str(db_path), timeout=5, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT action, symbol, price FROM trades "
                "WHERE trader_id = ? ORDER BY id DESC LIMIT 40",
                (self.id,),
            ).fetchall()
            conn.close()
        except Exception:
            return

        if not rows:
            return

        wins = 0
        losses = 0
        last_buy: dict[str, float] = {}

        for row in reversed(rows):   # ordre chronologique
            act, sym, price = row["action"], row["symbol"], float(row["price"])
            if act == "buy":
                last_buy[sym] = price
            elif act == "sell" and wins + losses < 20:
                bp = last_buy.pop(sym, None)
                if bp is not None:
                    if price > bp:
                        wins += 1
                    else:
                        losses += 1

        total = wins + losses
        if total >= 5:
            self._win_rate = wins / total
            self._feedback_cautious = self._win_rate < 0.40
        else:
            self._feedback_cautious = False

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
        if self._feedback_cautious:
            fraction *= 0.5   # taux réussite < 40% → taille position réduite de 50%
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

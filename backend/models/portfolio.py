class Portfolio:
    """
    Holds a trader's cash, open positions, and a cached total value.

    The engine updates `portfolio_value` after every tick by calling value(prices).
    Direct mutations of `cash` and `positions` are done by the engine on trade execution.
    """

    def __init__(self, starting_capital: float):
        self.cash: float = starting_capital
        self.positions: dict[str, float] = {}   # symbol -> quantity held
        self.portfolio_value: float = starting_capital
        self._price_cache: dict[str, float] = {}

    def value(self, prices: dict) -> float:
        """Calculate total value using current prices, falling back to last known price."""
        self._price_cache.update(prices)
        total = self.cash
        for symbol, qty in self.positions.items():
            price = self._price_cache.get(symbol, 0.0)
            total += qty * price
        return total

    def position_value(self, symbol: str, prices: dict) -> float:
        qty = self.positions.get(symbol, 0.0)
        price = prices.get(symbol) or self._price_cache.get(symbol, 0.0)
        return qty * price

    def max_buy_qty(self, symbol: str, prices: dict) -> float:
        """How many units of symbol can be bought with available cash."""
        price = prices.get(symbol) or self._price_cache.get(symbol, 0.0)
        if price <= 0:
            return 0.0
        return self.cash / price

    def allocation(self, prices: dict) -> dict[str, float]:
        """Returns each position's weight as a fraction of total portfolio value."""
        total = self.value(prices)
        if total == 0:
            return {}
        result = {"cash": self.cash / total}
        for symbol, qty in self.positions.items():
            price = prices.get(symbol) or self._price_cache.get(symbol, 0.0)
            result[symbol] = (qty * price) / total
        return result

    def __repr__(self) -> str:
        return (
            f"Portfolio(cash={self.cash:.2f}, "
            f"positions={self.positions}, "
            f"value={self.portfolio_value:.2f})"
        )

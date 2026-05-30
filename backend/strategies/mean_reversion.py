class MeanReversionStrategy:
    """
    Bollinger-band style mean reversion.
    Buy when price falls below (MA - k*std); sell when it rises above (MA + k*std).

    Needs at least `window` data points.
    """

    def __init__(self, window: int = 20, k: float = 1.5):
        self.window = window
        self.k = k

    def signal(self, prices: list) -> str:
        if len(prices) < self.window:
            return "hold"

        window_prices = prices[-self.window:]
        ma  = sum(window_prices) / self.window
        variance = sum((p - ma) ** 2 for p in window_prices) / self.window
        std = variance ** 0.5

        current = prices[-1]
        if std == 0:
            return "hold"

        if current < ma - self.k * std:
            return "buy"
        if current > ma + self.k * std:
            return "sell"
        return "hold"

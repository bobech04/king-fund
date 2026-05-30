class BreakoutStrategy:
    """
    Donchian channel breakout.
    Buy when the current price exceeds the highest price of the last `window` ticks.
    Sell when it falls below the lowest price of the last `window` ticks.

    Needs at least `window + 1` data points (so the current tick is not part of the channel).
    """

    def __init__(self, window: int = 20):
        self.window = window

    def signal(self, prices: list) -> str:
        if len(prices) < self.window + 1:
            return "hold"

        channel = prices[-(self.window + 1):-1]   # exclude current tick
        current = prices[-1]

        if current > max(channel):
            return "buy"
        if current < min(channel):
            return "sell"
        return "hold"

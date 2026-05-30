class MomentumStrategy:
    """
    Moving-average crossover.
    Buy when the short MA crosses above the long MA; sell on the reverse.

    Needs at least `long_window` data points before emitting a non-hold signal.
    """

    def __init__(self, short_window: int = 5, long_window: int = 20, threshold: float = 0.005):
        self.short_window = short_window
        self.long_window = long_window
        self.threshold = threshold  # minimum gap to avoid noise trades

    def signal(self, prices: list) -> str:
        if len(prices) < self.long_window:
            return "hold"

        short_ma = sum(prices[-self.short_window:]) / self.short_window
        long_ma  = sum(prices[-self.long_window:])  / self.long_window

        ratio = (short_ma - long_ma) / long_ma
        if ratio >  self.threshold:
            return "buy"
        if ratio < -self.threshold:
            return "sell"
        return "hold"

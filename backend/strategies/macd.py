def _ema(prices: list, period: int) -> float:
    """Exponential moving average of the full series, returning only the last value."""
    if not prices:
        return 0.0
    k = 2.0 / (period + 1)
    result = prices[0]
    for p in prices[1:]:
        result = p * k + result * (1 - k)
    return result


class MACDStrategy:
    """
    MACD line / signal line crossover.
    Buy on bullish crossover (MACD crosses above signal); sell on bearish crossover.

    Maintains an internal MACD history to compute the signal line EMA.
    Needs at least `slow + signal_period` data points before firing.
    """

    def __init__(self, fast: int = 12, slow: int = 26, signal_period: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal_period = signal_period
        self._macd_history: list = []
        self._prev_macd: float = 0.0
        self._prev_signal: float = 0.0

    def signal(self, prices: list) -> str:
        if len(prices) < self.slow:
            return "hold"

        macd_line = _ema(prices, self.fast) - _ema(prices, self.slow)
        self._macd_history.append(macd_line)

        if len(self._macd_history) < self.signal_period:
            self._prev_macd = macd_line
            return "hold"

        signal_line = _ema(self._macd_history, self.signal_period)

        action = "hold"
        if self._prev_macd < self._prev_signal and macd_line > signal_line:
            action = "buy"
        elif self._prev_macd > self._prev_signal and macd_line < signal_line:
            action = "sell"

        self._prev_macd   = macd_line
        self._prev_signal = signal_line
        return action

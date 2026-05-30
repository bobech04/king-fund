def compute_rsi(prices: list, period: int = 14) -> float:
    """Wilder's RSI. Returns 50.0 when there is not enough data."""
    if len(prices) < period + 1:
        return 50.0

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent = deltas[-period:]

    avg_gain = sum(d for d in recent if d > 0) / period
    avg_loss = sum(-d for d in recent if d < 0) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


class RSIStrategy:
    """
    Classic RSI oscillator.
    Buy below `oversold` threshold; sell above `overbought` threshold.
    """

    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def signal(self, prices: list) -> str:
        rsi = compute_rsi(prices, self.period)
        if rsi < self.oversold:
            return "buy"
        if rsi > self.overbought:
            return "sell"
        return "hold"

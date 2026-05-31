"""
Thin wrapper around LiquidityDesk — returns cached liquidity data for traders.
Never triggers a refresh (read-only); relies on the engine's 15-tick refresh cycle.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_instance = None
_lock = threading.Lock()


class LiquidityClient:
    def liquidity_score(self) -> float | None:
        """Cached global liquidity score (0-10), or None if not yet available."""
        try:
            from divisions.middle_office import get_liquidity_desk
            return get_liquidity_desk().get_score()
        except Exception:
            return None

    def liquidity_bias(self) -> float:
        """
        Float in [-1.0, +1.0].
          +1.0 = très ample liquidity   → risk-on bullish
          -1.0 = très tendue liquidity  → risk-off bearish
          0.0  = neutre ou donnée indisponible
        Formule : (score - 5) / 5  — centré sur 5/10 = neutre.
        """
        score = self.liquidity_score()
        if score is None:
            return 0.0
        return max(-1.0, min(1.0, (score - 5.0) / 5.0))


def get_liquidity_client() -> LiquidityClient:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = LiquidityClient()
    return _instance

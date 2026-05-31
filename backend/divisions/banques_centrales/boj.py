from .base_banque import BaseBanque


class BOJ(BaseBanque):
    """Bank of Japan — taux directeur via FRED (RSS indisponible de façon stable)."""
    NAME        = "Bank of Japan"
    CURRENCY    = "JPY"
    REGION      = "Japan"
    RSS_URL     = ""
    FRED_SERIES = "IRSTCB01JPM156N"   # OECD overnight rate Japan

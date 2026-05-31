from .base_banque import BaseBanque


class SARB(BaseBanque):
    """South African Reserve Bank — taux via FRED, pas de RSS stable."""
    NAME        = "South African Reserve Bank"
    CURRENCY    = "ZAR"
    REGION      = "South Africa"
    RSS_URL     = ""
    FRED_SERIES = "IRSTCB01ZAM156N"

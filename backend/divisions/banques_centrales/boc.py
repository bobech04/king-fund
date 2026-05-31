from .base_banque import BaseBanque


class BOC(BaseBanque):
    """Bank of Canada — taux directeur + flux RSS officiel."""
    NAME        = "Bank of Canada"
    CURRENCY    = "CAD"
    REGION      = "Canada"
    RSS_URL     = "https://www.bankofcanada.ca/rss/"
    FRED_SERIES = "IRSTCB01CAM156N"

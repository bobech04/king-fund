from .base_banque import BaseBanque


class BOE(BaseBanque):
    """Bank of England — taux directeur + flux de presse officiel."""
    NAME        = "Bank of England"
    CURRENCY    = "GBP"
    REGION      = "United Kingdom"
    RSS_URL     = "https://www.bankofengland.co.uk/rss/news"
    FRED_SERIES = "IRSTCB01GBM156N"

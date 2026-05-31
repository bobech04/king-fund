from .base_banque import BaseBanque


class RBA(BaseBanque):
    """Reserve Bank of Australia — taux directeur + flux RSS officiel."""
    NAME        = "Reserve Bank of Australia"
    CURRENCY    = "AUD"
    REGION      = "Australia"
    RSS_URL     = "https://www.rba.gov.au/rss.xml"
    FRED_SERIES = "IRSTCB01AUM156N"

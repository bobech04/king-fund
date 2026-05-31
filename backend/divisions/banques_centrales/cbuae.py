from .base_banque import BaseBanque


class CBUAE(BaseBanque):
    """Central Bank of the UAE — pas de flux FRED/RSS public fiable."""
    NAME        = "Central Bank of the UAE"
    CURRENCY    = "AED"
    REGION      = "United Arab Emirates"
    RSS_URL     = ""
    FRED_SERIES = ""

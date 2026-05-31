from .base_banque import BaseBanque


class CBN(BaseBanque):
    """Central Bank of Nigeria — pas de flux FRED/RSS public fiable en anglais."""
    NAME        = "Central Bank of Nigeria"
    CURRENCY    = "NGN"
    REGION      = "Nigeria"
    RSS_URL     = ""
    FRED_SERIES = ""

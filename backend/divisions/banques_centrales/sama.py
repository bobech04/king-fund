from .base_banque import BaseBanque


class SAMA(BaseBanque):
    """Saudi Central Bank (SAMA) — pas de flux FRED/RSS public fiable en anglais."""
    NAME        = "Saudi Central Bank"
    CURRENCY    = "SAR"
    REGION      = "Saudi Arabia"
    RSS_URL     = ""
    FRED_SERIES = ""

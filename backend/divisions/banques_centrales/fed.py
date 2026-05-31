from .base_banque import BaseBanque


class FederalReserve(BaseBanque):
    """Réserve Fédérale américaine — taux FEDFUNDS + communiqués officiels."""
    NAME        = "Federal Reserve"
    CURRENCY    = "USD"
    REGION      = "United States"
    RSS_URL     = "https://www.federalreserve.gov/feeds/press_all.xml"
    FRED_SERIES = "FEDFUNDS"

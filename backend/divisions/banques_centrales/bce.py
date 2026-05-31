from .base_banque import BaseBanque


class BCE(BaseBanque):
    """Banque Centrale Européenne — taux de dépôt + flux de presse officiel."""
    NAME        = "Banque Centrale Européenne"
    CURRENCY    = "EUR"
    REGION      = "Zone Euro"
    RSS_URL     = "https://www.ecb.europa.eu/rss/press.rss"
    FRED_SERIES = "ECBDFR"   # ECB Deposit Facility Rate

from .base_banque import BaseBanque


class RBI(BaseBanque):
    """Reserve Bank of India — taux directeur + flux politique monétaire officiel."""
    NAME        = "Reserve Bank of India"
    CURRENCY    = "INR"
    REGION      = "India"
    RSS_URL     = "https://rbi.org.in/rss/MonetaryPolicy.xml"
    FRED_SERIES = "IRSTCB01INM156N"

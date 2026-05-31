from .base_banque import BaseBanque


class NorgesBank(BaseBanque):
    """Norges Bank — taux directeur + flux RSS officiel."""
    NAME        = "Norges Bank"
    CURRENCY    = "NOK"
    REGION      = "Norway"
    RSS_URL     = "https://www.norges-bank.no/en/rss/"
    FRED_SERIES = "IRSTCB01NOM156N"

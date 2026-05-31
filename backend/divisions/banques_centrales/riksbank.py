from .base_banque import BaseBanque


class Riksbank(BaseBanque):
    """Riksbank (Suède) — taux directeur + flux RSS officiel."""
    NAME        = "Riksbank"
    CURRENCY    = "SEK"
    REGION      = "Sweden"
    RSS_URL     = "https://www.riksbank.se/en-gb/rss/"
    FRED_SERIES = "IRSTCB01SEM156N"

from .base_banque import BaseBanque


class SNB(BaseBanque):
    """Swiss National Bank — taux directeur + flux de publications officielles."""
    NAME        = "Swiss National Bank"
    CURRENCY    = "CHF"
    REGION      = "Switzerland"
    RSS_URL     = "https://www.snb.ch/en/feed/newspublications"
    FRED_SERIES = "IRSTCB01CHM156N"

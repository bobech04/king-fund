from .base_banque import BaseBanque


class BCB(BaseBanque):
    """Banco Central do Brasil — taux Selic via FRED, pas de RSS stable en anglais."""
    NAME        = "Banco Central do Brasil"
    CURRENCY    = "BRL"
    REGION      = "Brazil"
    RSS_URL     = ""
    FRED_SERIES = "IRSTCB01BRM156N"

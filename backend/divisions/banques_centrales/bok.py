from .base_banque import BaseBanque


class BOK(BaseBanque):
    """Bank of Korea — taux directeur via FRED, pas de RSS stable en anglais."""
    NAME        = "Bank of Korea"
    CURRENCY    = "KRW"
    REGION      = "South Korea"
    RSS_URL     = ""
    FRED_SERIES = "IRSTCB01KRM156N"

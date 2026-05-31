from .base_banque import BaseBanque


class TCMB(BaseBanque):
    """Banque Centrale de la République de Turquie — taux via FRED."""
    NAME        = "Central Bank of the Republic of Turkey"
    CURRENCY    = "TRY"
    REGION      = "Turkey"
    RSS_URL     = ""
    FRED_SERIES = "IRSTCB01TRM156N"

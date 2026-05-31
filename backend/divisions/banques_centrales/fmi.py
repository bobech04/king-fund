from .base_banque import BaseBanque


class FMI(BaseBanque):
    """Fonds Monétaire International — flux d'actualités officielles (pas de taux)."""
    NAME        = "Fonds Monétaire International"
    CURRENCY    = "SDR"
    REGION      = "International"
    RSS_URL     = "https://www.imf.org/en/News/RSS"
    FRED_SERIES = ""   # le FMI ne fixe pas de taux directeur

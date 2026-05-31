from .base_banque import BaseBanque


class BRI(BaseBanque):
    """Banque des Règlements Internationaux — discours officiels (pas de taux)."""
    NAME        = "Banque des Règlements Internationaux"
    CURRENCY    = "XDR"
    REGION      = "International"
    RSS_URL     = "https://www.bis.org/doclist/all_speeches.rss"
    FRED_SERIES = ""   # la BRI ne fixe pas de taux directeur

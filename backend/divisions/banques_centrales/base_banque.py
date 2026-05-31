import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data.fred_client import get_fred_client
from data.rss_client  import get_rss_client


class BaseBanque:
    """
    Prototype commun à tous les modules banques centrales.

    Chaque sous-classe déclare :
      NAME         — nom officiel (str)
      CURRENCY     — code ISO de la devise contrôlée (str)
      REGION       — zone économique (str)
      RSS_URL      — flux RSS officiel de communiqués (str, "" si absent)
      FRED_SERIES  — identifiant FRED du taux directeur (str, "" si absent)
    """

    NAME:        str = ""
    CURRENCY:    str = ""
    REGION:      str = ""
    RSS_URL:     str = ""
    FRED_SERIES: str = ""

    def __init__(self):
        self._fred = get_fred_client()
        self._rss  = get_rss_client()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def rate(self) -> float:
        """Taux directeur actuel (%). 0.0 si série FRED indisponible."""
        return self._fred._get(self.FRED_SERIES) if self.FRED_SERIES else 0.0

    def sentiment(self) -> float:
        """
        Biais RSS : -1.0 hawkish (baisse équités) → +1.0 dovish (hausse équités).
        0.0 si flux absent ou requête échouée.
        """
        return self._rss.get_bias(self.RSS_URL) if self.RSS_URL else 0.0

    def latest_headline(self) -> str:
        """Dernier titre du flux RSS officiel."""
        if not self.RSS_URL:
            return ""
        items = self._rss.get_items(self.RSS_URL, n=1)
        return items[0] if items else ""

    def signal(self) -> dict:
        """
        Dictionnaire complet du signal de cette banque centrale :
          name      — nom officiel
          currency  — code devise
          region    — zone économique
          rate      — taux directeur (%)
          sentiment — biais [-1, +1]
          headline  — dernier communiqué (120 chars max)
        """
        return {
            "name":      self.NAME,
            "currency":  self.CURRENCY,
            "region":    self.REGION,
            "rate":      self.rate(),
            "sentiment": self.sentiment(),
            "headline":  self.latest_headline()[:120],
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.NAME!r} ({self.CURRENCY})>"

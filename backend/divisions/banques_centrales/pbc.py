from .base_banque import BaseBanque


class PBC(BaseBanque):
    """People's Bank of China — taux via FRED, pas de RSS stable en anglais."""
    NAME        = "People's Bank of China"
    CURRENCY    = "CNY"
    REGION      = "China"
    RSS_URL     = ""
    FRED_SERIES = "IRSTCB01CNM156N"   # OECD overnight rate China

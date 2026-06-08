import os
from pathlib import Path
from dotenv import load_dotenv

# Load backend .env first (authoritative), then desk-local .env as override
_backend_env = Path(__file__).resolve().parent.parent.parent.parent / ".env"
if _backend_env.exists():
    load_dotenv(_backend_env)
load_dotenv(Path(__file__).parent / ".env", override=True)

FRED_API_KEY      = os.getenv("FRED_API_KEY", "")        # https://fred.stlouisfed.org/docs/api/api_key.html
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")  # optionnel, tier gratuit disponible
EIA_API_KEY       = os.getenv("EIA_API_KEY", "")        # https://www.eia.gov/opendata/ — optionnel (backup WTI)
GLASSNODE_API_KEY = os.getenv("GLASSNODE_API_KEY", "")  # https://studio.glassnode.com/api — free tier disponible

FRED_SERIES = {
    "m2_money_supply":    "M2SL",
    "fed_funds_rate":     "FEDFUNDS",
    "sofr":               "SOFR90DAYAVG",   # SOFR 90-day avg (remplace SOFR quotidien)
    "reserve_balances":   "WRESBAL",
    "treasury_10y":       "DGS10",
}

FRED_CREDIT_SERIES = {
    "hy_spread":          "BAMLH0A0HYM2",
    "ig_spread":          "BAMLC0A0CM",
    "bank_credit":        "TOTBKCR",
    "commercial_paper":   "CPFF",
    "sofr_ois":           "IORB",           # Interest on Reserve Balances (remplace TED)
}

YAHOO_EQUITIES      = ["SPY", "QQQ", "IWM", "^VIX", "^GSPC"]
YAHOO_ASIAN_INDICES = ["^N225", "^HSI", "000001.SS", "^KS11", "^BSESN", "^AXJO"]
YAHOO_ETFS     = ["TLT", "HYG", "LQD", "JNK", "AGG"]
YAHOO_FOREX    = ["EURUSD=X", "USDJPY=X", "GBPUSD=X", "DX-Y.NYB", "USDCHF=X"]

COINGECKO_TOP_COINS = ["bitcoin", "ethereum", "tether", "binancecoin", "usd-coin"]
COINGECKO_DEFI      = ["uniswap", "aave", "compound-governance-token", "maker", "curve-dao-token"]

COINGECKO_BASE_URL  = "https://api.coingecko.com/api/v3"
COINGECKO_PRO_URL   = "https://pro-api.coingecko.com/api/v3"

def coingecko_is_demo_key() -> bool:
    """Les cles Demo CoinGecko commencent par 'CG-'."""
    return COINGECKO_API_KEY.startswith("CG-")

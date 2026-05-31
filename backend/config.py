import os
from pathlib import Path
from datetime import date

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Battle parameters
# ---------------------------------------------------------------------------

STARTING_CAPITAL  = float(os.getenv("STARTING_CAPITAL", 500))
TARGET_CAPITAL    = float(os.getenv("TARGET_CAPITAL", 10_000))
BATTLE_DAYS       = int(os.getenv("BATTLE_DAYS", 30))
TICK_INTERVAL     = int(os.getenv("TICK_INTERVAL", 60))
BATTLE_START_DATE = date.fromisoformat(os.getenv("BATTLE_START_DATE", "2026-05-30"))

SYMBOLS = os.getenv(
    "SYMBOLS",
    "AAPL,MSFT,TSLA,AMZN,GOOGL,NVDA,META,NFLX,BTC-USD,ETH-USD",
).split(",")

DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).parent.parent / "database" / "king_fund.db"))
LOG_DIR = Path(os.getenv("LOG_DIR", Path(__file__).parent.parent / "logs"))

# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

MARKET_CACHE_TTL = int(os.getenv("MARKET_CACHE_TTL", 55))

# ---------------------------------------------------------------------------
# External API keys
# ---------------------------------------------------------------------------

FRED_API_KEY          = os.getenv("FRED_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
TWELVE_DATA_API_KEY   = os.getenv("TWELVE_DATA_API_KEY", "")
NEWS_API_KEY          = os.getenv("NEWS_API_KEY", "")
FMP_API_KEY           = os.getenv("FMP_API_KEY", "")   # not used — fundamentals via yfinance
COINGECKO_API_KEY     = os.getenv("COINGECKO_API_KEY", "")
EXCHANGE_RATE_API_KEY = os.getenv("EXCHANGE_RATE_API_KEY", "")
POLYGON_API_KEY       = os.getenv("POLYGON_API_KEY", "")
ANTHROPIC_API_KEY     = os.getenv("ANTHROPIC_API_KEY", "")

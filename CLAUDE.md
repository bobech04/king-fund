# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**King Fund** is an autonomous trading battle engine. 30 AI traders each start with 500€ and compete to reach 10,000€ within 30 days. A Python Flask backend fetches live market prices via Yahoo Finance; a mobile-first HTML/JS frontend lets users watch the battle in real time.

## Architecture

```
king-fund/
├── backend/
│   ├── app.py               # Flask entry point, REST + WebSocket endpoints
│   ├── engine.py            # Main trading loop — ticks every N seconds, calls each trader
│   ├── traders/
│   │   ├── base_trader.py   # Abstract Trader class (portfolio, decide(), execute())
│   │   └── trader_*.py      # 30 concrete traders, one file each (or generated)
│   ├── strategies/          # Reusable strategy modules imported by traders
│   │   ├── momentum.py
│   │   ├── mean_reversion.py
│   │   ├── rsi.py
│   │   └── ...
│   ├── data/
│   │   └── market.py        # Yahoo Finance wrapper (yfinance), price cache
│   └── models/
│       └── portfolio.py     # Portfolio state: cash, positions, PnL, history
├── frontend/
│   ├── index.html           # Single-page mobile app (no build step)
│   ├── assets/              # CSS, icons
│   └── components/          # Reusable JS modules (leaderboard, chart, trader card)
├── database/
│   └── king_fund.db         # SQLite — trade log, snapshots, battle config
└── logs/                    # Per-trader daily logs
```

## Key Design Rules

- **One battle session = 30 days, 30 traders, 500€ start, 10 000€ target.**
- The engine ticks on a configurable interval (default: every 60 s during market hours).
- Each trader calls `decide(prices) → action` independently; the engine aggregates and executes.
- Market data is fetched centrally in `data/market.py` (one call per tick, shared by all traders) to avoid Yahoo Finance rate limits.
- The Flask server exposes:
  - `GET /api/state` — full leaderboard snapshot (JSON)
  - `GET /api/trader/<id>` — individual trader detail + trade history
  - `WebSocket /ws` — push updates to the frontend on every tick
- The frontend polls `/api/state` as fallback if WebSocket is unavailable.
- SQLite is used for persistence; no external database required.

## Dev Commands

```bash
# Install dependencies
pip install flask flask-sock yfinance pandas

# Run the backend (development)
cd backend
python app.py

# The frontend is static — open frontend/index.html directly in a browser,
# or serve it via Flask by placing it under backend/static/.
```

## Trader Interface

Every trader inherits from `base_trader.py`:

```python
class BaseTrader:
    id: int           # 1–30
    name: str
    portfolio: Portfolio  # cash + positions
    strategy: str     # label shown in UI

    def decide(self, prices: dict) -> dict:
        # Returns {"action": "buy"|"sell"|"hold", "symbol": str, "amount": float}
        ...
```

Traders must never mutate shared state directly — they return an action dict; the engine validates and applies it.

## Data Flow

```
Yahoo Finance (yfinance)
    → data/market.py (price cache, rate-limit guard)
        → engine.py (broadcast prices to all 30 traders each tick)
            → trader.decide() × 30
                → engine applies trades → updates Portfolio
                    → snapshot written to SQLite
                        → Flask pushes update via WebSocket
                            → frontend re-renders leaderboard
```

## Configuration

Battle parameters live in `backend/config.py` (create if absent):

```python
STARTING_CAPITAL = 500      # euros per trader
TARGET_CAPITAL   = 10_000   # euros — victory condition
BATTLE_DAYS      = 30
TICK_INTERVAL    = 60       # seconds between engine ticks
SYMBOLS          = ["AAPL", "MSFT", "TSLA", "BTC-USD", "ETH-USD", ...]
```

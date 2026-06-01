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

## Profil académique BAC+6 — Injection dans tous les appels Claude API

Le fichier `backend/agents/formation.py` définit le profil académique du gestionnaire de portefeuille.
Ce profil est **injecté automatiquement en tête de chaque system prompt** Claude via `enrichir_systeme()`.

### Formation (BAC+6)
| Diplôme | Compétences clés |
|---|---|
| Master Finance de Marché | Valorisation, dérivés, obligataire, structuration, marchés actions/taux |
| Master Mathématiques Appliquées – Statistiques Quantitatives | Stochastique, Itô, Monte Carlo, VaR, CVaR, backtesting |
| Master Économie Géopolitique & Macro | Cycles éco, politique monétaire comparée, risques géopolitiques, marchés émergents |
| Droit Financier MiFID II & AMF | Best execution, transparency, reporting réglementaire, protection investisseurs |
| CFA Level 3 | Portfolio management, allocation d'actifs, risk management, éthique CFA Institute |
| Anglais Financier (C1/C2) | Terminologie financière internationale, rédaction rapports institutionnels |

### Usage
```python
from agents.formation import enrichir_systeme

prompt_systeme = enrichir_systeme("Tu es le CIO d'un fonds institutionnel...")
```

### Fichiers qui injectent le profil
- `backend/divisions/sources/anthropic_reports.py` — Morning Brief + Post-Market (sources)
- `backend/divisions/back_office/post_market_review.py` — Post-Market Review 18:00
- `backend/divisions/middle_office/risk_committee.py` — Risk Committee vendredi 19:00

### Règle de développement
Tout nouveau fichier ajoutant un appel `client.messages.create()` **doit** utiliser
`enrichir_systeme()` sur le `system=` prompt. Ne jamais passer un system prompt brut.

---

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

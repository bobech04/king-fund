import time
import sqlite3
import json
import threading
import logging
import importlib
from datetime import datetime, date
from pathlib import Path

from config import (
    STARTING_CAPITAL, TARGET_CAPITAL, BATTLE_DAYS,
    TICK_INTERVAL, SYMBOLS, DB_PATH, BATTLE_START_DATE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._tick_callback = None
        self._last_prices: dict = {}
        self._traders = []
        self._init_db()
        self._load_traders()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def set_tick_callback(self, fn):
        self._tick_callback = fn

    def _init_db(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trades (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    trader_id       INTEGER NOT NULL,
                    timestamp       TEXT    NOT NULL,
                    symbol          TEXT    NOT NULL,
                    action          TEXT    NOT NULL,
                    amount          REAL    NOT NULL,
                    price           REAL    NOT NULL,
                    portfolio_value REAL    NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    trader_id       INTEGER NOT NULL,
                    timestamp       TEXT    NOT NULL,
                    portfolio_value REAL    NOT NULL,
                    cash            REAL    NOT NULL,
                    positions       TEXT    NOT NULL
                );
            """)

    def _load_traders(self):
        loaded = []
        for i in range(1, 31):
            try:
                mod = importlib.import_module(f"traders.trader_{i:02d}")
                trader = mod.Trader(trader_id=i, starting_capital=STARTING_CAPITAL)
            except ModuleNotFoundError:
                from traders.base_trader import BaseTrader
                trader = BaseTrader(trader_id=i, starting_capital=STARTING_CAPITAL)
            loaded.append(trader)
        self._traders = loaded
        logger.info(f"Loaded {len(self._traders)} traders")

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(self, prices: dict):
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(DB_PATH) as conn:
            for trader in self._traders:
                try:
                    action = trader.decide(prices)
                    if action and action.get("action") != "hold":
                        self._execute_trade(trader, action, prices, now, conn)
                    trader.portfolio.portfolio_value = trader.portfolio.value(prices)
                    self._save_snapshot(trader, now, conn)
                except Exception as e:
                    logger.error(f"Trader {trader.id} error: {e}")

    def _execute_trade(self, trader, action: dict, prices: dict, timestamp: str, conn):
        symbol = action.get("symbol")
        act    = action.get("action")
        amount = float(action.get("amount", 0))

        if not symbol or symbol not in prices or amount <= 0:
            return

        price = prices[symbol]

        if act == "buy":
            cost = amount * price
            if cost > trader.portfolio.cash:
                return
            trader.portfolio.cash -= cost
            trader.portfolio.positions[symbol] = (
                trader.portfolio.positions.get(symbol, 0) + amount
            )
        elif act == "sell":
            held = trader.portfolio.positions.get(symbol, 0)
            sell_qty = min(amount, held)
            if sell_qty <= 0:
                return
            trader.portfolio.cash += sell_qty * price
            trader.portfolio.positions[symbol] = held - sell_qty
        else:
            return

        pv = trader.portfolio.value(prices)
        conn.execute(
            "INSERT INTO trades "
            "(trader_id, timestamp, symbol, action, amount, price, portfolio_value) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (trader.id, timestamp, symbol, act, amount, price, pv),
        )

    def _save_snapshot(self, trader, timestamp: str, conn):
        conn.execute(
            "INSERT INTO snapshots "
            "(trader_id, timestamp, portfolio_value, cash, positions) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                trader.id,
                timestamp,
                trader.portfolio.portfolio_value,
                trader.portfolio.cash,
                json.dumps(trader.portfolio.positions),
            ),
        )

    # ------------------------------------------------------------------
    # Read state (called by Flask)
    # ------------------------------------------------------------------

    def get_state(self) -> dict:
        battle_day = (date.today() - BATTLE_START_DATE).days + 1
        leaderboard = []
        for t in self._traders:
            pv = t.portfolio.portfolio_value
            leaderboard.append({
                "id":       t.id,
                "name":     t.name,
                "strategy": t.strategy,
                "value":    round(pv, 2),
                "pnl":      round(pv - STARTING_CAPITAL, 2),
                "pnl_pct":  round((pv - STARTING_CAPITAL) / STARTING_CAPITAL * 100, 2),
                "won":      pv >= TARGET_CAPITAL,
            })
        leaderboard.sort(key=lambda x: x["value"], reverse=True)
        for rank, entry in enumerate(leaderboard, 1):
            entry["rank"] = rank
        return {
            "battle_day": min(battle_day, BATTLE_DAYS),
            "target":     TARGET_CAPITAL,
            "leaderboard": leaderboard,
            "timestamp":  datetime.utcnow().isoformat(),
        }

    def get_trader(self, trader_id: int):
        trader = next((t for t in self._traders if t.id == trader_id), None)
        if trader is None:
            return None
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            trades = conn.execute(
                "SELECT * FROM trades WHERE trader_id = ? ORDER BY timestamp DESC LIMIT 100",
                (trader_id,),
            ).fetchall()
            history = conn.execute(
                "SELECT timestamp, portfolio_value FROM snapshots "
                "WHERE trader_id = ? ORDER BY timestamp ASC",
                (trader_id,),
            ).fetchall()
        return {
            "id":        trader.id,
            "name":      trader.name,
            "strategy":  trader.strategy,
            "cash":      round(trader.portfolio.cash, 2),
            "positions": trader.portfolio.positions,
            "value":     round(trader.portfolio.portfolio_value, 2),
            "trades":    [dict(r) for r in trades],
            "history":   [dict(r) for r in history],
        }

    def get_battle_info(self) -> dict:
        battle_day = (date.today() - BATTLE_START_DATE).days + 1
        winners = [t for t in self._traders if t.portfolio.portfolio_value >= TARGET_CAPITAL]
        return {
            "start_date":       BATTLE_START_DATE.isoformat(),
            "battle_day":       min(battle_day, BATTLE_DAYS),
            "days_remaining":   max(0, BATTLE_DAYS - battle_day),
            "starting_capital": STARTING_CAPITAL,
            "target_capital":   TARGET_CAPITAL,
            "total_traders":    len(self._traders),
            "winners":          len(winners),
        }

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        from data.market import MarketData
        market = MarketData(SYMBOLS)
        self._running = True
        logger.info("Trading engine started")
        while self._running:
            try:
                prices = market.get_prices()
                self._last_prices = prices
                self.tick(prices)
                if self._tick_callback:
                    self._tick_callback(self.get_state())
            except Exception as e:
                logger.error(f"Engine tick error: {e}")
            time.sleep(TICK_INTERVAL)

    def stop(self):
        self._running = False
        logger.info("Trading engine stopped")

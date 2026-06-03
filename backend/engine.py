import random
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

# ---------------------------------------------------------------------------
# SQLite helpers — WAL mode + retry with exponential backoff
# ---------------------------------------------------------------------------

_DB_MAX_RETRIES = 5
_DB_BASE_DELAY  = 0.05   # 50 ms — doubles each attempt


def db_connect() -> sqlite3.Connection:
    """Open a WAL-mode connection with a 30-second busy-timeout."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")   # ms — SQLite-level wait before error
    conn.row_factory = sqlite3.Row
    return conn


def _write_with_retry(fn):
    """Execute fn(conn) inside a single transaction, retrying on 'database is locked'."""
    for attempt in range(_DB_MAX_RETRIES):
        conn = None
        try:
            conn = db_connect()
            result = fn(conn)
            conn.commit()
            return result
        except sqlite3.OperationalError as exc:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if "locked" not in str(exc).lower() or attempt == _DB_MAX_RETRIES - 1:
                raise
            delay = _DB_BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.02)
            logger.warning(
                "SQLite locked (tentative %d/%d) — retry dans %.0f ms",
                attempt + 1, _DB_MAX_RETRIES, delay * 1000,
            )
            time.sleep(delay)
        except Exception:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
    raise sqlite3.OperationalError("database is locked — max retries atteint")


# ---------------------------------------------------------------------------
# SITG — Skin-in-the-Game : budget dynamique selon la performance
# ---------------------------------------------------------------------------

def _compute_sitg_budget(portfolio_value: float) -> float:
    """
    Budget multiplicateur [0.25, 1.75] basé sur le PnL courant.

    - PnL = 0%   → 1.00x (neutre)
    - PnL = +100% → 1.75x (maximum, atteint dès qu'on double sa mise)
    - PnL = -100% → 0.25x (plancher, quasi-faillite)

    Les bonnes performances débloquent plus de capital à déployer ;
    les pertes le contractent proportionnellement.
    """
    pnl_pct = (portfolio_value / STARTING_CAPITAL) - 1.0   # ex. 0.50 = +50 %
    if pnl_pct >= 0:
        budget = 1.0 + min(1.0, pnl_pct) * 0.75
    else:
        budget = 1.0 + max(-1.0, pnl_pct) * 0.75
    return round(max(0.25, min(1.75, budget)), 3)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class TradingEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._tick_callback = None
        self._last_prices: dict = {}
        self._prev_tick_prices: dict = {}   # used to skip decide() on stale prices
        self._traders = []
        self._tick_count = 0
        from data.expert_signal_client import get_expert_signal_client
        self._expert_signals = get_expert_signal_client()
        self._init_db()
        self._load_traders()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    _DIVISION_COLORS = {
        "Investissement":   "#ffd700",
        "Banque Centrale":  "#4488ff",
        "Expert Tech":      "#00e5a0",
        "Expert Crypto":    "#b44cff",
        "Expert Commerce":  "#ff6b35",
        "Morning Brief":    "#ff4488",
    }
    _DIVISION_ICONS = {
        "Investissement":   "📈",
        "Banque Centrale":  "🏛️",
        "Expert Tech":      "💻",
        "Expert Crypto":    "₿",
        "Expert Commerce":  "🛒",
        "Morning Brief":    "🌅",
    }

    def _get_division(self, trader) -> str:
        doc = (trader.__class__.__doc__ or "").strip()
        if "Division Investissement" in doc:
            return "Investissement"
        if "Banque Centrale" in doc:
            return "Banque Centrale"
        if "Morning Brief" in doc:
            return "Morning Brief"
        if "Expert Sectoriel Tech" in doc:
            return "Expert Tech"
        if "Expert Sectoriel Crypto" in doc:
            return "Expert Crypto"
        if "Expert Sectoriel" in doc:
            return "Expert Commerce"
        return "Standard"

    def set_tick_callback(self, fn):
        self._tick_callback = fn

    def _init_db(self):
        """Crée les tables et active WAL mode de façon permanente sur la DB."""
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = db_connect()
        try:
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
            conn.commit()
        finally:
            conn.close()

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
        self._restore_trader_states()
        self._update_sitg_budgets()
        self._preload_histories()

    def _restore_trader_states(self):
        """Reload cash + positions from the latest snapshot for each trader."""
        conn = db_connect()
        try:
            rows = conn.execute(
                """
                SELECT trader_id, cash, positions, portfolio_value
                FROM snapshots
                WHERE id IN (
                    SELECT MAX(id) FROM snapshots GROUP BY trader_id
                )
                """
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            logger.info(
                "[RESTORE] No snapshots found - traders start fresh at %.2f", STARTING_CAPITAL
            )
            return

        logger.info("[RESTORE] Restoring %d traders from last snapshot...", len(rows))
        restored = 0
        for row in rows:
            trader = next((t for t in self._traders if t.id == row["trader_id"]), None)
            if trader is None:
                continue
            try:
                positions = json.loads(row["positions"])
                trader.portfolio.cash = row["cash"]
                trader.portfolio.positions = positions
                trader.portfolio.portfolio_value = row["portfolio_value"]
                restored += 1
                pos_count = sum(1 for qty in positions.values() if qty > 0)
                logger.info(
                    "[RESTORE] TRD%02d  pv=%.2f  cash=%.2f  positions=%d",
                    row["trader_id"], row["portfolio_value"], row["cash"], pos_count,
                )
            except Exception as e:
                logger.warning("[RESTORE] Trader %d failed: %s", row["trader_id"], e)

        logger.info(
            "[RESTORE] Done: %d/%d traders restored from last snapshot",
            restored, len(self._traders),
        )

    def _preload_histories(self):
        """Preload each trader's price history with real market data at startup.

        This ensures strategies can generate signals from the very first tick
        instead of waiting for N warmup ticks to fill their history windows.
        Also prevents the 'flat history' problem that occurs when the engine
        starts during off-market hours and stale prices fill the history.
        """
        from data.market import MarketData
        market = MarketData(SYMBOLS)

        # One fetch per unique symbol — at most 10 calls
        histories: dict = {}
        for sym in SYMBOLS:
            hist = market.get_history(sym, period="5d", interval="1m")
            if hist:
                histories[sym] = hist
                logger.info("Preloaded %d price points for %s", len(hist), sym)
            else:
                logger.warning("Could not preload history for %s", sym)

        assigned = 0
        for trader in self._traders:
            sym = getattr(trader, "_symbol", None)
            if sym and sym in histories and hasattr(trader, "_history"):
                trader._history = list(histories[sym])
                assigned += 1
        logger.info("Preloaded histories for %d/%d traders", assigned, len(self._traders))

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(self, prices: dict):
        self._tick_count += 1
        now = datetime.utcnow().isoformat()
        prev = self._prev_tick_prices   # snapshot of previous tick's prices

        def _do_tick(conn):
            for trader in self._traders:
                try:
                    sym = getattr(trader, "_symbol", None)
                    # Skip decide() when price hasn't changed since last tick.
                    # This prevents stale off-market prices from polluting the
                    # strategy history and causing perpetual "hold" signals.
                    price_unchanged = bool(
                        sym and prev and prices.get(sym) == prev.get(sym)
                    )
                    if not price_unchanged:
                        action = trader.decide(prices)
                        # Apply expert signal influence (sectoral experts + CBs)
                        expert_sig = self._expert_signals.get_signal(sym)
                        action = self._apply_expert_influence(
                            trader, action, expert_sig, prices
                        )
                        if action and action.get("action") != "hold":
                            self._execute_trade(trader, action, prices, now, conn)
                    trader.portfolio.portfolio_value = trader.portfolio.value(prices)
                    self._save_snapshot(trader, now, conn)
                except Exception as e:
                    logger.error(f"Trader {trader.id} error: {e}")

        _write_with_retry(_do_tick)
        self._prev_tick_prices = dict(prices)   # becomes "prev" on next tick
        self._update_sitg_budgets()

        if self._tick_count % 15 == 0:
            self._schedule_liquidity_refresh()

    def _schedule_liquidity_refresh(self):
        try:
            from divisions.middle_office import get_liquidity_desk
            get_liquidity_desk().trigger_background_refresh()
        except Exception as e:
            logger.debug(f"Liquidity refresh skipped: {e}")

    # ------------------------------------------------------------------
    # Expert signal influence
    # ------------------------------------------------------------------

    def _apply_expert_influence(
        self, trader, action: dict, expert_sig: float, prices: dict
    ) -> dict:
        """
        Modulates a trader's raw decide() output using aggregated expert signals
        from sectoral desk agents (Yahoo_Equity, CoinGecko_Market, FRED_*) and
        central bank RSS sentiments (FED, BCE …).

        expert_sig in [-1.0, +1.0]:
          +1.0  all experts strongly bullish
          -1.0  all experts strongly bearish
           0.0  neutral / data not yet available

        Behaviour table:
          HOLD + sig ≥ +0.70, no position, cash ≥ 20€  → open 10% long
          HOLD + sig ≤ -0.70, has position               → partial 20% exit
          BUY  + sig ≤ -0.55                             → blocked
          SELL + sig ≥ +0.55                             → blocked
          BUY/SELL + |sig| > 0.20                        → size scaled ±20% max
        """
        act = action.get("action", "hold")
        sym = getattr(trader, "_symbol", None)

        if abs(expert_sig) < 0.20:
            return action   # signal too weak — no influence

        # ---- Expert override on HOLD -----------------------------------------
        if act == "hold" and sym:
            held = trader.portfolio.positions.get(sym, 0.0)

            if expert_sig >= 0.70 and held == 0.0 and trader.portfolio.cash >= 20.0:
                frac = trader.base_fraction
                new_action = trader._buy(sym, frac, prices)
                if new_action.get("amount", 0) > 0:
                    logger.info(
                        "Expert +%.2f → open position TRD%02d %s (%.0f%% — grade %s)",
                        expert_sig, trader.id, sym, frac * 100, trader.grade,
                    )
                    return new_action

            elif expert_sig <= -0.70 and held > 0.0:
                new_action = trader._sell(sym, 0.20)
                if new_action.get("amount", 0) > 0:
                    logger.info(
                        "Expert %.2f → partial exit TRD%02d %s (20%%)",
                        expert_sig, trader.id, sym,
                    )
                    return new_action

            return action

        # ---- Scale or block existing BUY / SELL ------------------------------
        action = dict(action)   # shallow copy — never mutate caller's dict

        if act == "buy":
            if expert_sig <= -0.55:
                logger.info(
                    "Expert %.2f blocks BUY TRD%02d %s",
                    expert_sig, trader.id, sym or "?",
                )
                return {"action": "hold", "symbol": "", "amount": 0}
            # scale: +1.0 → ×1.20,  0.0 → ×1.00,  -0.55 → ×0.89
            scale = 1.0 + expert_sig * 0.20
            action["amount"] = action["amount"] * max(0.50, min(1.50, scale))

        elif act == "sell":
            if expert_sig >= 0.55:
                logger.info(
                    "Expert %.2f blocks SELL TRD%02d %s",
                    expert_sig, trader.id, sym or "?",
                )
                return {"action": "hold", "symbol": "", "amount": 0}
            # scale: -1.0 → ×1.20,  0.0 → ×1.00,  +0.55 → ×0.89
            scale = 1.0 - expert_sig * 0.20
            action["amount"] = action["amount"] * max(0.50, min(1.50, scale))

        return action

    def _execute_trade(self, trader, action: dict, prices: dict, timestamp: str, conn):
        symbol = action.get("symbol")
        act    = action.get("action")
        amount = float(action.get("amount", 0))

        if not symbol or symbol not in prices or amount <= 0:
            return

        price = prices[symbol]

        if act == "buy":
            # SITG : ajuste la taille de position selon la performance du trader
            amount *= trader.sitg_budget
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
        logger.info(
            "TRADE TRD%02d %s %s %.6f @ %.4f → PV=%.2f",
            trader.id, act.upper(), symbol, amount, price, pv,
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
    # SITG update
    # ------------------------------------------------------------------

    def _update_sitg_budgets(self):
        """Recalcule le budget SITG de chaque trader après chaque tick."""
        for trader in self._traders:
            trader.sitg_budget = _compute_sitg_budget(trader.portfolio.portfolio_value)

    # ------------------------------------------------------------------
    # Read state (called by Flask)
    # ------------------------------------------------------------------

    def get_state(self) -> dict:
        battle_day = (date.today() - BATTLE_START_DATE).days + 1
        leaderboard = []
        for t in self._traders:
            pv = t.portfolio.portfolio_value
            leaderboard.append({
                "id":          t.id,
                "name":        t.name,
                "strategy":    t.strategy,
                "division":    self._get_division(t),
                "value":       round(pv, 2),
                "pnl":         round(pv - STARTING_CAPITAL, 2),
                "pnl_pct":     round((pv - STARTING_CAPITAL) / STARTING_CAPITAL * 100, 2),
                "won":         pv >= TARGET_CAPITAL,
                "sitg_budget": t.sitg_budget,
                "grade":       t.grade,
            })
        leaderboard.sort(key=lambda x: x["value"], reverse=True)
        for rank, entry in enumerate(leaderboard, 1):
            entry["rank"] = rank
        liq_score     = None
        liq_regime    = None
        bertez_signal = None
        bertez_mode   = None
        try:
            from divisions.middle_office import get_liquidity_desk
            desk          = get_liquidity_desk()
            liq_score     = desk.get_score()
            liq_regime    = desk.get_regime()
            bertez_signal = desk.get_bertez_signal()
            bertez_mode   = desk.get_bertez_mode()
        except Exception:
            pass

        return {
            "battle_day":       min(battle_day, BATTLE_DAYS),
            "target":           TARGET_CAPITAL,
            "leaderboard":      leaderboard,
            "timestamp":        datetime.utcnow().isoformat(),
            "liquidity_score":  liq_score,
            "liquidity_regime": liq_regime,
            "bertez_signal":    bertez_signal,
            "bertez_mode":      bertez_mode,
        }

    def get_trader(self, trader_id: int):
        trader = next((t for t in self._traders if t.id == trader_id), None)
        if trader is None:
            return None
        conn = db_connect()
        try:
            trades = conn.execute(
                "SELECT * FROM trades WHERE trader_id = ? ORDER BY timestamp DESC LIMIT 100",
                (trader_id,),
            ).fetchall()
            history = conn.execute(
                "SELECT timestamp, portfolio_value FROM snapshots "
                "WHERE trader_id = ? ORDER BY timestamp ASC",
                (trader_id,),
            ).fetchall()
        finally:
            conn.close()
        return {
            "id":          trader.id,
            "name":        trader.name,
            "strategy":    trader.strategy,
            "cash":        round(trader.portfolio.cash, 2),
            "positions":   trader.portfolio.positions,
            "value":       round(trader.portfolio.portfolio_value, 2),
            "sitg_budget": trader.sitg_budget,
            "trades":      [dict(r) for r in trades],
            "history":     [dict(r) for r in history],
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

    def get_divisions(self) -> list:
        DIVISION_ORDER = [
            "Investissement", "Banque Centrale",
            "Expert Tech", "Expert Crypto", "Expert Commerce", "Morning Brief",
        ]
        division_data: dict = {}
        for t in self._traders:
            div = self._get_division(t)
            pv  = t.portfolio.portfolio_value
            if div not in division_data:
                division_data[div] = {
                    "name":         div,
                    "icon":         self._DIVISION_ICONS.get(div, "⚡"),
                    "color":        self._DIVISION_COLORS.get(div, "#888"),
                    "traders":      [],
                    "total_value":  0.0,
                    "wins":         0,
                    "best_trader":  None,
                    "best_value":   0.0,
                }
            division_data[div]["traders"].append(t.id)
            division_data[div]["total_value"] += pv
            if pv >= TARGET_CAPITAL:
                division_data[div]["wins"] += 1
            if pv > division_data[div]["best_value"]:
                division_data[div]["best_value"] = pv
                division_data[div]["best_trader"] = {
                    "id": t.id, "name": t.name, "value": round(pv, 2),
                }

        result = []
        for div_name in DIVISION_ORDER:
            if div_name not in division_data:
                continue
            data  = division_data[div_name]
            count = len(data["traders"])
            avg   = data["total_value"] / count if count else STARTING_CAPITAL
            result.append({
                "name":         div_name,
                "icon":         data["icon"],
                "color":        data["color"],
                "trader_count": count,
                "avg_value":    round(avg, 2),
                "avg_pnl":      round(avg - STARTING_CAPITAL, 2),
                "avg_pnl_pct":  round((avg - STARTING_CAPITAL) / STARTING_CAPITAL * 100, 2),
                "wins":         data["wins"],
                "best_trader":  data["best_trader"],
            })
        return result

    def get_weekly_agent(self) -> dict:
        best = max(self._traders, key=lambda t: t.portfolio.portfolio_value)
        weekly_gain = best.portfolio.portfolio_value - STARTING_CAPITAL
        trade_count = 0
        week_num    = date.today().isocalendar()[1]

        conn = db_connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM trades WHERE trader_id = ? "
                "AND timestamp >= date('now', '-7 days')",
                (best.id,),
            ).fetchone()
            if row:
                trade_count = row["cnt"]

            oldest = conn.execute(
                "SELECT portfolio_value FROM snapshots "
                "WHERE trader_id = ? AND timestamp >= date('now', '-7 days') "
                "ORDER BY timestamp ASC LIMIT 1",
                (best.id,),
            ).fetchone()
            if oldest:
                weekly_gain = best.portfolio.portfolio_value - oldest["portfolio_value"]
        finally:
            conn.close()

        pv = best.portfolio.portfolio_value
        return {
            "id":          best.id,
            "name":        best.name,
            "strategy":    best.strategy,
            "division":    self._get_division(best),
            "value":       round(pv, 2),
            "pnl":         round(pv - STARTING_CAPITAL, 2),
            "pnl_pct":     round((pv - STARTING_CAPITAL) / STARTING_CAPITAL * 100, 2),
            "weekly_gain": round(weekly_gain, 2),
            "trade_count": trade_count,
            "week":        week_num,
            "sitg_budget": best.sitg_budget,
        }

    def get_post_market(self) -> dict:
        state       = self.get_state()
        leaderboard = state["leaderboard"]
        divisions   = self.get_divisions()

        values    = [t["value"] for t in leaderboard]
        total_pnl = sum(t["pnl"] for t in leaderboard)
        winners   = [t for t in leaderboard if t["won"]]

        divs_ranked = sorted(divisions, key=lambda d: d["avg_pnl_pct"], reverse=True)

        return {
            "battle_day":       state["battle_day"],
            "top5":             leaderboard[:5],
            "bottom5":          list(reversed(leaderboard[-5:])),
            "best_division":    divs_ranked[0]  if divs_ranked else None,
            "worst_division":   divs_ranked[-1] if divs_ranked else None,
            "divisions_ranked": divs_ranked,
            "total_pnl":        round(total_pnl, 2),
            "avg_value":        round(sum(values) / len(values), 2) if values else 0,
            "max_value":        round(max(values), 2) if values else 0,
            "min_value":        round(min(values), 2) if values else 0,
            "winners_count":    len(winners),
            "timestamp":        datetime.utcnow().isoformat(),
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

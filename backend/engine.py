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
        self._last_eod_date = None            # détection changement de journée
        self._selection_multipliers: dict = {}  # trader.id → multiplicateur sélection naturelle
        self._eliminated_ids: set = set()       # IDs des traders éliminés au J15
        self._orphan_symbols: set = set()       # symboles en position mais hors SYMBOLS feed
        from data.expert_signal_client import get_expert_signal_client
        self._expert_signals = get_expert_signal_client()
        self._init_db()
        self._load_traders()
        # Inter-agent communication hub (4 flux PubSub)
        try:
            from divisions.interagents import get_interagent_hub
            self._hub = get_interagent_hub()
        except Exception as _hub_err:
            logger.warning("[Engine] InterAgentHub indisponible : %s", _hub_err)
            self._hub = None

        # Gouvernance hiérarchique (hook avant chaque trade)
        try:
            from divisions.gouvernance.gouvernance import get_gouvernance_engine
            self._gouvernance = get_gouvernance_engine()
            logger.info("[Engine] GouvernanceEngine initialisé")
        except Exception as _gov_err:
            logger.warning("[Engine] GouvernanceEngine indisponible : %s", _gov_err)
            self._gouvernance = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    _DIVISION_COLORS = {
        "Groupe A — EU Valeurs":        "#00cc88",
        "Groupe B — Macro Dalio":       "#4488ff",
        "Groupe C — Protecteurs Taleb": "#ff4444",
        # Anciens noms (compatibilité si des traders non migrés subsistent)
        "Investissement":   "#ffd700",
        "Banque Centrale":  "#4488ff",
        "Expert Tech":      "#00e5a0",
        "Expert Crypto":    "#b44cff",
        "Expert Commerce":  "#ff6b35",
        "Morning Brief":    "#ff4488",
    }
    _DIVISION_ICONS = {
        "Groupe A — EU Valeurs":        "🇪🇺",
        "Groupe B — Macro Dalio":       "🌍",
        "Groupe C — Protecteurs Taleb": "🛡️",
        # Anciens noms
        "Investissement":   "📈",
        "Banque Centrale":  "🏛️",
        "Expert Tech":      "💻",
        "Expert Crypto":    "₿",
        "Expert Commerce":  "🛒",
        "Morning Brief":    "🌅",
    }
    _DIVISION_TO_CLASSE = {
        "Groupe A — EU Valeurs":        "equity",
        "Groupe B — Macro Dalio":       "fixed_income",
        "Groupe C — Protecteurs Taleb": "alternatives",
        "Investissement":               "equity",
        "Banque Centrale":              "fixed_income",
        "Expert Tech":                  "equity",
        "Expert Crypto":                "crypto",
        "Expert Commerce":              "equity",
        "Morning Brief":                "multi",
        "Standard":                     "multi",
    }
    _SYMBOL_TO_CLASSE = {
        "BTC-USD": "crypto",  "ETH-USD": "crypto",
        "BTC":     "crypto",  "ETH":     "crypto",
        "GC=F":    "commodities", "CL=F": "commodities", "NG=F": "commodities",
        "SI=F":    "commodities", "HG=F": "commodities",
        "EURUSD=X": "fx", "DX-Y.NYB": "fx", "GBPUSD=X": "fx",
        "USDJPY=X": "fx", "EURGBP=X": "fx",
        "TLT": "fixed_income", "IEF": "fixed_income", "SHY": "fixed_income",
        "BND": "fixed_income", "AGG": "fixed_income",
        "SPY": "equity", "QQQ": "equity", "IWM": "equity",
        "EEM": "equity", "VNQ": "alternatives",
    }

    def _get_division(self, trader) -> str:
        doc = (trader.__class__.__doc__ or "").strip()
        if "Groupe A" in doc:
            return "Groupe A — EU Valeurs"
        if "Groupe B" in doc:
            return "Groupe B — Macro Dalio"
        if "Groupe C" in doc:
            return "Groupe C — Protecteurs Taleb"
        # Fallback anciens noms
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
                CREATE TABLE IF NOT EXISTS eliminations (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    trader_id       INTEGER NOT NULL,
                    timestamp       TEXT    NOT NULL,
                    jour_bataille   INTEGER NOT NULL,
                    pv_au_moment    REAL    NOT NULL
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
        self._orphan_symbols = self._collect_orphan_symbols()
        self._update_sitg_budgets()
        self._preload_histories()

    def _collect_orphan_symbols(self) -> set:
        """Retourne les symboles détenus en position mais absents du feed SYMBOLS."""
        known = set(SYMBOLS)
        orphans = set()
        for trader in self._traders:
            for sym, qty in trader.portfolio.positions.items():
                if abs(qty) > 1e-9 and sym not in known:
                    orphans.add(sym)
        if orphans:
            logger.warning(
                "[ORPHAN] %d symbole(s) hors-feed détecté(s) dans les positions : %s",
                len(orphans), sorted(orphans),
            )
        return orphans

    def _liquidate_orphan_positions(self, prices: dict) -> None:
        """Force-vend toutes les positions dans des symboles orphelins (hors SYMBOLS).

        Appelé une seule fois au premier tick de run() après que MarketData a
        été étendu pour inclure ces symboles — les prix sont donc disponibles.
        """
        if not self._orphan_symbols:
            return

        now = datetime.utcnow().isoformat()
        nav_before = sum(t.portfolio.value(prices) for t in self._traders)
        liquidated = 0
        still_missing: set = set()

        def _do_liquidate(conn):
            nonlocal liquidated
            for trader in self._traders:
                for sym in list(trader.portfolio.positions.keys()):
                    if sym not in self._orphan_symbols:
                        continue
                    qty = trader.portfolio.positions[sym]
                    if abs(qty) < 1e-9:
                        trader.portfolio.positions.pop(sym, None)
                        continue
                    price = prices.get(sym, 0.0)
                    if price <= 0:
                        still_missing.add(sym)
                        logger.warning(
                            "[ORPHAN] TRD%02d %s qty=%.6f — prix introuvable, liquidation reportée",
                            trader.id, sym, qty,
                        )
                        continue
                    proceeds = qty * price
                    trader.portfolio.cash += proceeds
                    trader.portfolio.positions.pop(sym)
                    pv = trader.portfolio.value(prices)
                    trader.portfolio.portfolio_value = pv
                    conn.execute(
                        "INSERT INTO trades "
                        "(trader_id, timestamp, symbol, action, amount, price, portfolio_value) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (trader.id, now, sym, "sell", qty, price, pv),
                    )
                    logger.info(
                        "[ORPHAN] LIQUIDATION TRD%02d SELL %s %.6f @ %.4f "
                        "→ cash récupéré=%.2f€  PV=%.2f€",
                        trader.id, sym, qty, price, proceeds, pv,
                    )
                    liquidated += 1

        _write_with_retry(_do_liquidate)
        # Ne garder en orphelins que ce qu'on n'a pas pu liquider
        self._orphan_symbols = still_missing
        self._update_sitg_budgets()

        nav_after = sum(t.portfolio.value(prices) for t in self._traders)
        logger.info(
            "[ORPHAN] ══ Liquidation orphelins terminée ══ "
            "%d position(s) soldée(s) | NAV %+.2f€ (%.2f€ → %.2f€)",
            liquidated, nav_after - nav_before, nav_before, nav_after,
        )

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
            if sym and hasattr(trader, "_history"):
                if isinstance(trader._history, dict):
                    # Multi-symbol trader (e.g. trader_18): preload each symbol separately
                    for s in trader._history:
                        if s in histories:
                            trader._history[s] = list(histories[s])
                    if any(s in histories for s in trader._history):
                        assigned += 1
                elif sym in histories:
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

        # ── Flux 4 : Black Swan — si VIX > 35 on skip tous les trades ──────
        if self._hub and self._hub.black_swan_halt:
            logger.warning(
                "[Engine] BLACK SWAN HALT actif — tick %d ignoré (VIX=%.1f)",
                self._tick_count, self._hub.last_vix or 0,
            )
            self._prev_tick_prices = dict(prices)
            return

        _CIRCUIT_BREAKER_FLOOR = STARTING_CAPITAL * 0.05   # 25 € — freeze total si PV ≤ plancher

        def _do_tick(conn):
            for trader in self._traders:
                try:
                    # ── Circuit breaker individuel ─────────────────────────
                    # Si la valeur du portefeuille tombe sous 5 % du capital
                    # de départ (25 €), on gèle ce trader : plus aucun ordre
                    # ne passe jusqu'à une éventuelle élimination/remplacement.
                    pv_now = trader.portfolio.value(prices)
                    if pv_now <= _CIRCUIT_BREAKER_FLOOR:
                        trader.portfolio.portfolio_value = pv_now
                        self._save_snapshot(trader, now, conn)
                        if not getattr(trader, "_cb_logged", False):
                            logger.warning(
                                "CIRCUIT BREAKER TRD%02d  PV=%.2f€ ≤ %.0f€ — frozen",
                                trader.id, pv_now, _CIRCUIT_BREAKER_FLOOR,
                            )
                            trader._cb_logged = True
                        continue
                    trader._cb_logged = False   # reset si le trader remonte

                    sym = getattr(trader, "_symbol", None)
                    # Skip decide() when price hasn't changed since last tick.
                    # This prevents stale off-market prices from polluting the
                    # strategy history and causing perpetual "hold" signals.
                    price_unchanged = bool(
                        sym and prev and prices.get(sym) == prev.get(sym)
                    )
                    if not price_unchanged:
                        if self._tick_count % 20 == 0:
                            trader.refresh_feedback(DB_PATH)
                        action = trader.decide(prices)
                        # Apply expert signal influence (sectoral experts + CBs)
                        expert_sig = self._expert_signals.get_signal(sym)
                        action = self._apply_expert_influence(
                            trader, action, expert_sig, prices
                        )
                        if action and action.get("action") != "hold":
                            # ── Hook gouvernance hiérarchique ──────────────
                            gov = getattr(self, "_gouvernance", None)
                            if gov:
                                ok, bloqueur = gov.autoriser_trade(
                                    trader.id, action,
                                    action.get("symbol", sym or ""),
                                )
                                if not ok:
                                    logger.debug(
                                        "[GOV] TRD%02d bloqué par %s",
                                        trader.id, bloqueur,
                                    )
                                    continue
                            self._execute_trade(trader, action, prices, now, conn)
                    trader.portfolio.portfolio_value = trader.portfolio.value(prices)
                    self._save_snapshot(trader, now, conn)
                except Exception as e:
                    logger.error(f"Trader {trader.id} error: {e}")

        _write_with_retry(_do_tick)
        self._prev_tick_prices = dict(prices)   # becomes "prev" on next tick
        self._update_sitg_budgets()

        # Sélection naturelle — une fois par journée calendaire
        today = date.today()
        if self._last_eod_date is None:
            self._last_eod_date = today
        elif today > self._last_eod_date:
            self._run_eod_natural_selection()
            self._last_eod_date = today

        if self._tick_count % 15 == 0:
            self._schedule_liquidity_refresh()

        # ── Cycles inter-agents (non bloquants — threads daemon) ────────────
        if self._hub:
            if self._tick_count % 60 == 0:
                self._hub.run_cycle_cb()        # Flux 1 : CB → Groupe B Macro Dalio
            if self._tick_count % 30 == 0:
                self._hub.run_cycle_experts()   # Flux 2 : Experts → Groupe A EU Valeurs
                self._hub.run_cycle_bertez()    # Flux 3 : Bertez → Groupe C Protecteurs
            if self._tick_count % 15 == 0:
                self._hub.run_cycle_liq()       # Flux 4 : Desk Liq → budget_factor
            if self._tick_count % 20 == 0:
                self._hub.run_cycle_vix()       # Flux 5 : VIX Black Swan check

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

        # ── AUTO-SHORT SPY/QQQ lors d'un BLACK SWAN (VIX ≥ 35) ──────────────
        if self._hub and self._hub.black_swan_halt and act == "hold":
            for inv_sym in ["SPY", "QQQ"]:
                if inv_sym not in prices:
                    continue
                already_short = trader.portfolio.positions.get(inv_sym, 0) < 0
                if not already_short and trader.portfolio.cash >= 50.0:
                    new_action = trader._short(inv_sym, 0.08, prices)
                    if new_action.get("amount", 0) > 0:
                        logger.warning(
                            "BLACK SWAN SHORT TRD%02d %s (VIX=%.1f)",
                            trader.id, inv_sym, self._hub.last_vix or 0,
                        )
                        return new_action

        # ── AUTO-COVER quand Black Swan levé ────────────────────────────────
        if self._hub and not self._hub.black_swan_halt and act == "hold":
            for inv_sym in ["SPY", "QQQ"]:
                short_held = trader.portfolio.positions.get(inv_sym, 0)
                if short_held < 0 and inv_sym in prices:
                    new_action = trader._cover(inv_sym, 1.0)
                    if new_action.get("amount", 0) > 0:
                        logger.info(
                            "BLACK SWAN LIFTED — COVER TRD%02d %s", trader.id, inv_sym
                        )
                        return new_action

        # ── CIO BEARISH SHORT SPY/QQQ (expert_sig ≤ -0.70) ──────────────────
        if sym in ("SPY", "QQQ") and act == "hold" and expert_sig <= -0.70:
            already_short = trader.portfolio.positions.get(sym, 0) < 0
            if not already_short and trader.portfolio.cash >= 50.0:
                frac = trader.base_fraction * 0.5
                new_action = trader._short(sym, frac, prices)
                if new_action.get("amount", 0) > 0:
                    logger.info(
                        "CIO BEARISH SHORT TRD%02d %s sig=%.2f",
                        trader.id, sym, expert_sig,
                    )
                    return new_action

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
            # Sélection naturelle : bonus top5 (+20%/j) / malus bottom5 (-50%/j)
            amount *= self._selection_multipliers.get(trader.id, 1.0)
            # Flux 3 : Desk Liquidité — ajuste le budget selon la liquidité globale
            if self._hub:
                amount *= self._hub.liq_budget_factor
            if amount < 0.001:
                return
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
            if sell_qty < 0.001:
                return
            trader.portfolio.cash += sell_qty * price
            trader.portfolio.positions[symbol] = held - sell_qty
        elif act == "short":
            if amount < 0.001:
                return
            # Vente à découvert : le produit crédite le cash, position devient négative
            trader.portfolio.cash += amount * price
            trader.portfolio.positions[symbol] = (
                trader.portfolio.positions.get(symbol, 0) - amount
            )
        elif act == "cover":
            # Rachat de la position courte
            short_held = trader.portfolio.positions.get(symbol, 0)
            if short_held >= 0:
                return
            cover_qty = min(amount, abs(short_held))
            if cover_qty < 0.001:
                return
            buyback_cost = cover_qty * price
            if buyback_cost > trader.portfolio.cash:
                return
            trader.portfolio.cash -= buyback_cost
            new_qty = short_held + cover_qty
            if abs(new_qty) < 1e-9:
                trader.portfolio.positions.pop(symbol, None)
            else:
                trader.portfolio.positions[symbol] = new_qty
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
    # Sélection naturelle (fin de journée)
    # ------------------------------------------------------------------

    def _run_eod_natural_selection(self):
        """Top 5 +20% budget, Bottom 5 -50% budget. Élimination si J≥15 et PV<300€."""
        ranked    = sorted(self._traders, key=lambda t: t.portfolio.portfolio_value, reverse=True)
        battle_day = (date.today() - BATTLE_START_DATE).days + 1

        top5 = ranked[:5]
        bot5 = ranked[-5:]

        top_str = " | ".join(f"TRD{t.id:02d}={t.portfolio.portfolio_value:.0f}€" for t in top5)
        bot_str = " | ".join(f"TRD{t.id:02d}={t.portfolio.portfolio_value:.0f}€" for t in bot5)

        logger.info("╔══════════════════════════════════════════════════════════╗")
        logger.info("║  SÉLECTION NATURELLE — EOD J%-2d                          ║", battle_day)
        logger.info("║  TOP 5 (+20%%) : %-44s ║", top_str)
        logger.info("║  BOT 5 (-50%%) : %-44s ║", bot_str)
        logger.info("╚══════════════════════════════════════════════════════════╝")

        for t in top5:
            cur = self._selection_multipliers.get(t.id, 1.0)
            new = round(min(2.5, cur * 1.20), 3)
            self._selection_multipliers[t.id] = new
            logger.info(
                "SELECTION TOP5   TRD%02d  PV=%.2f€  ×%.3f → ×%.3f",
                t.id, t.portfolio.portfolio_value, cur, new,
            )

        for t in bot5:
            cur = self._selection_multipliers.get(t.id, 1.0)
            new = round(max(0.10, cur * 0.50), 3)
            self._selection_multipliers[t.id] = new
            logger.info(
                "SELECTION BOT5   TRD%02d  PV=%.2f€  ×%.3f → ×%.3f",
                t.id, t.portfolio.portfolio_value, cur, new,
            )

        if battle_day >= 15:
            self._check_eliminations(battle_day)

    def _check_eliminations(self, battle_day: int):
        """Élimine tout trader < 300€ après J15 et le remplace par une stratégie fraîche."""
        for trader in list(self._traders):
            if trader.id in self._eliminated_ids:
                continue
            if trader.portfolio.portfolio_value < 300:
                pv = trader.portfolio.portfolio_value
                logger.warning(
                    "ÉLIMINATION TRD%02d  PV=%.2f€ < 300€  (J%d)",
                    trader.id, pv, battle_day,
                )
                _write_with_retry(lambda conn, _id=trader.id, _pv=pv, _day=battle_day: conn.execute(
                    "INSERT INTO eliminations (trader_id, timestamp, jour_bataille, pv_au_moment) "
                    "VALUES (?, ?, ?, ?)",
                    (_id, datetime.utcnow().isoformat(), _day, _pv),
                ))
                self._eliminated_ids.add(trader.id)
                self._replace_trader(trader)

    def _replace_trader(self, trader):
        """Réinitialise le portfolio à 500€ et recharge le module (instance fraîche)."""
        i = trader.id
        try:
            mod_name = f"traders.trader_{i:02d}"
            mod      = importlib.import_module(mod_name)
            importlib.reload(mod)
            new_trader = mod.Trader(trader_id=i, starting_capital=STARTING_CAPITAL)
        except Exception:
            from traders.base_trader import BaseTrader
            new_trader = BaseTrader(trader_id=i, starting_capital=STARTING_CAPITAL)

        self._selection_multipliers[i] = 1.0
        self._eliminated_ids.discard(i)   # ardoise vierge après remplacement

        idx = next((j for j, t in enumerate(self._traders) if t.id == i), None)
        if idx is not None:
            self._traders[idx] = new_trader
        logger.info("REMPLACEMENT TRD%02d → capital %.2f€ remis à zéro", i, STARTING_CAPITAL)

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
                "won":                 pv >= TARGET_CAPITAL,
                "sitg_budget":         t.sitg_budget,
                "grade":               t.grade,
                "selection_multiplier": self._selection_multipliers.get(t.id, 1.0),
                "eliminated":          t.id in self._eliminated_ids,
            })
        leaderboard.sort(key=lambda x: x["value"], reverse=True)
        for rank, entry in enumerate(leaderboard, 1):
            entry["rank"] = rank

        # ── Per-trader DB stats (nb_trades, meilleur_ticker, win_rate) ────────
        _db_nb_trades: dict   = {}
        _db_best_ticker: dict = {}
        _db_win_rate: dict    = {}
        try:
            _conn = db_connect()
            try:
                for _row in _conn.execute(
                    "SELECT trader_id, COUNT(*) as cnt FROM trades GROUP BY trader_id"
                ).fetchall():
                    _db_nb_trades[int(_row["trader_id"])] = int(_row["cnt"])
                _seen_trd: set = set()
                for _row in _conn.execute(
                    "SELECT trader_id, symbol, COUNT(*) as cnt FROM trades "
                    "WHERE action='buy' GROUP BY trader_id, symbol "
                    "ORDER BY trader_id, cnt DESC"
                ).fetchall():
                    _tid = int(_row["trader_id"])
                    if _tid not in _seen_trd:
                        _db_best_ticker[_tid] = _row["symbol"]
                        _seen_trd.add(_tid)
                # Win rate : derniers 40 trades par trader (même algo que refresh_feedback)
                _wr_rows = _conn.execute(
                    "SELECT trader_id, action, symbol, price FROM ("
                    "  SELECT trader_id, action, symbol, price, id,"
                    "  ROW_NUMBER() OVER (PARTITION BY trader_id ORDER BY id DESC) rn"
                    "  FROM trades"
                    ") WHERE rn <= 40 ORDER BY trader_id, id ASC"
                ).fetchall()
                _wr_trades: dict = {}
                for _r in _wr_rows:
                    _wr_trades.setdefault(int(_r["trader_id"]), []).append(_r)
                for _tid2, _tlist in _wr_trades.items():
                    _wins = 0; _losses = 0; _lb: dict = {}
                    for _r in _tlist:
                        _act, _sym, _pr = _r["action"], _r["symbol"], float(_r["price"])
                        if _act == "buy":
                            _lb[_sym] = _pr
                        elif _act == "sell":
                            _bp = _lb.pop(_sym, None)
                            if _bp is not None:
                                if _pr > _bp:
                                    _wins += 1
                                else:
                                    _losses += 1
                    if _wins + _losses >= 5:
                        _db_win_rate[_tid2] = _wins / (_wins + _losses)
            finally:
                _conn.close()
        except Exception:
            pass

        # ── Classement (champs attendus par le frontend) ─────────────────────
        classement = []
        for _entry in leaderboard:
            _tid  = _entry["id"]
            _div  = _entry["division"]
            _nb_t = _db_nb_trades.get(_tid, 0)
            _wr   = round(_db_win_rate.get(_tid, 0.0) * 100, 0)
            _best = _db_best_ticker.get(_tid)
            _cls  = self._SYMBOL_TO_CLASSE.get(
                _best or "",
                self._DIVISION_TO_CLASSE.get(_div, "multi"),
            )
            classement.append({
                "trader_id":       f"TRD{_tid:03d}",
                "nom":             _entry["name"],
                "role":            _div,
                "specialite":      _entry["strategy"],
                "classe_actif":    _cls,
                "pnl_jour":        _entry["pnl"],
                "nb_trades":       _nb_t,
                "taux_victoire":   _wr,
                "meilleur_ticker": _best,
                "rank":            _entry["rank"],
                "value":           _entry["value"],
                "pnl_pct":         _entry["pnl_pct"],
                "grade":           _entry["grade"],
                "eliminated":      _entry["eliminated"],
            })

        # ── Stats globaux ─────────────────────────────────────────────────────
        _wr_vals = list(_db_win_rate.values())
        _stats = {
            "pnl_total_desk":      round(sum(e["pnl"] for e in leaderboard), 2),
            "nb_traders_positifs": sum(1 for e in leaderboard if e["pnl"] >= 0),
            "nb_traders_negatifs": sum(1 for e in leaderboard if e["pnl"] < 0),
            "taux_victoire_moyen": round(
                sum(_wr_vals) / len(_wr_vals) * 100, 1
            ) if _wr_vals else 0.0,
            "nb_trades_total":     sum(_db_nb_trades.values()),
            "volume_total":        0,
        }

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
            "classement":       classement,
            "stats":            _stats,
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
            "Groupe A — EU Valeurs",
            "Groupe B — Macro Dalio",
            "Groupe C — Protecteurs Taleb",
            # Anciens noms (si traders non migrés présents)
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
        # Étendre la liste de symboles pour inclure les positions orphelines
        # afin qu'elles puissent être valorisées et vendues au premier tick.
        all_symbols = list(SYMBOLS) + sorted(self._orphan_symbols)
        market = MarketData(all_symbols)
        self._market = market          # référence engine pour usage futur
        self._running = True
        logger.info("Trading engine started")
        _liquidation_done = not bool(self._orphan_symbols)  # skip si aucun orphelin
        while self._running:
            try:
                prices = market.get_prices()
                self._last_prices = prices
                if not _liquidation_done:
                    self._liquidate_orphan_positions(prices)
                    _liquidation_done = True
                self.tick(prices)
                if self._tick_callback:
                    self._tick_callback(self.get_state())
            except Exception as e:
                logger.error(f"Engine tick error: {e}")
            time.sleep(TICK_INTERVAL)

    def stop(self):
        self._running = False
        logger.info("Trading engine stopped")

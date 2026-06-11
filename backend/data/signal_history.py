"""
Signal History — Historique prédictif des signaux Bertez et Morning Brief.
Table : signal_log dans king_fund.db
Mesure la prédictivité dans le temps via comparaison direction préd. vs SPY.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _get_db_path() -> Path:
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from config import DB_PATH
        return Path(DB_PATH)
    except Exception:
        return Path(__file__).resolve().parents[2] / "database" / "king_fund.db"


def _conn() -> sqlite3.Connection:
    db = _get_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(db), check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _ensure_table() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS signal_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ts              TEXT    NOT NULL,
                signal_type     TEXT    NOT NULL,
                direction       TEXT,
                confidence      REAL,
                mode            TEXT,
                score           REAL,
                prediction_date TEXT    NOT NULL,
                outcome_date    TEXT,
                outcome         TEXT,
                success         INTEGER
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_sl_type ON signal_log (signal_type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sl_pred ON signal_log (prediction_date)")


try:
    _ensure_table()
except Exception as _e:
    logger.warning("[signal_history] Init: %s", _e)


def log_signal(signal_type: str, direction: str | None, confidence: float | None,
               mode: str | None, score: float | None) -> int | None:
    """
    Enregistre un signal. Déduplique sur (signal_type, prediction_date) —
    un seul enregistrement par type par jour calendaire.
    """
    now  = datetime.now(timezone.utc)
    date = now.date().isoformat()
    try:
        with _lock:
            with _conn() as c:
                exists = c.execute(
                    "SELECT id FROM signal_log WHERE signal_type=? AND prediction_date=?",
                    (signal_type, date)
                ).fetchone()
                if exists:
                    return exists["id"]
                cur = c.execute(
                    """INSERT INTO signal_log
                       (ts, signal_type, direction, confidence, mode, score, prediction_date)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (now.isoformat(), signal_type,
                     str(direction) if direction is not None else None,
                     float(confidence) if confidence is not None else None,
                     str(mode) if mode is not None else None,
                     float(score) if score is not None else None,
                     date),
                )
                logger.info("[signal_history] %s signal logged (id=%d)", signal_type, cur.lastrowid)
                return cur.lastrowid
    except Exception as e:
        logger.warning("[signal_history] log_signal: %s", e)
        return None


def check_pending_outcomes() -> int:
    """
    Pour les signaux sans outcome de plus d'un jour, évalue si la prédiction
    était juste vs la direction SPY J→J+1.
    Retourne le nombre de signaux mis à jour.
    """
    try:
        import yfinance as yf
        hist = yf.Ticker("SPY").history(period="5d", interval="1d")
        if hist.empty or len(hist) < 2:
            return 0
        last_close = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2])
        market_move = "up" if last_close > prev_close * 1.001 else (
            "down" if last_close < prev_close * 0.999 else "flat"
        )
    except Exception as e:
        logger.warning("[signal_history] SPY fetch: %s", e)
        return 0

    cutoff  = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    updated = 0

    try:
        with _lock:
            with _conn() as c:
                rows = c.execute(
                    """SELECT id, signal_type, direction FROM signal_log
                       WHERE success IS NULL AND prediction_date <= ?""",
                    (cutoff,)
                ).fetchall()

                for row in rows:
                    d = (row["direction"] or "").lower()
                    if d in ("bullish", "offensif"):
                        predicted = "up"
                    elif d in ("bearish", "defensif"):
                        predicted = "down"
                    else:
                        predicted = "neutral"

                    if predicted == "neutral" or market_move == "flat":
                        success = None
                        outcome = market_move
                    else:
                        outcome  = market_move
                        success  = 1 if predicted == market_move else 0

                    c.execute(
                        """UPDATE signal_log SET outcome=?, success=?, outcome_date=? WHERE id=?""",
                        (outcome, success, datetime.now(timezone.utc).date().isoformat(), row["id"])
                    )
                    if success is not None:
                        updated += 1
    except Exception as e:
        logger.warning("[signal_history] check_outcomes: %s", e)

    if updated:
        logger.info("[signal_history] %d signaux évalués (marché: %s)", updated, market_move)
    return updated


def get_stats() -> dict:
    """
    Taux de réussite par type.
    Retourne: {bertez: {total, evalues, succes, taux}, morning_brief: {...}}
    """
    result: dict = {}
    try:
        with _conn() as c:
            for stype in ("bertez", "morning_brief"):
                row = c.execute(
                    """SELECT COUNT(*) as total,
                              SUM(CASE WHEN success IS NOT NULL THEN 1 ELSE 0 END) as evalues,
                              SUM(CASE WHEN success = 1           THEN 1 ELSE 0 END) as succes
                       FROM signal_log WHERE signal_type = ?""",
                    (stype,)
                ).fetchone()
                total   = row["total"]   or 0
                evalues = row["evalues"] or 0
                succes  = row["succes"]  or 0
                result[stype] = {
                    "total":   total,
                    "evalues": evalues,
                    "succes":  succes,
                    "taux":    round(succes / evalues, 3) if evalues > 0 else None,
                }
    except Exception as e:
        logger.warning("[signal_history] get_stats: %s", e)
    return result


def get_history(signal_type: str | None = None, limit: int = 100) -> list[dict]:
    """Dernières N entrées, filtrées par type optionnel."""
    try:
        with _conn() as c:
            if signal_type:
                rows = c.execute(
                    """SELECT * FROM signal_log WHERE signal_type=? ORDER BY id DESC LIMIT ?""",
                    (signal_type, limit)
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM signal_log ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("[signal_history] get_history: %s", e)
        return []

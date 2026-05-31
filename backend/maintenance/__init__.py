"""Service maintenance informatique — santé du système King Fund."""

import os
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_health(engine, db_path: Path, ws_clients: int = 0) -> dict[str, Any]:
    """Retourne un rapport de santé complet du système."""
    checks: dict[str, Any] = {}
    overall_ok = True

    # ── Moteur de trading ─────────────────────────────────────────
    checks["engine"] = {
        "status":       "ok" if engine._running else "stopped",
        "running":      engine._running,
        "tick_count":   engine._tick_count,
        "prices_loaded": len(engine._last_prices),
    }
    if not engine._running:
        overall_ok = False

    # ── Traders ───────────────────────────────────────────────────
    values = [t.portfolio.portfolio_value for t in engine._traders]
    traders_ok = len(engine._traders) == 30
    checks["traders"] = {
        "status":    "ok" if traders_ok else "degraded",
        "count":     len(engine._traders),
        "avg_value": round(sum(values) / len(values), 2) if values else 0,
        "max_value": round(max(values), 2) if values else 0,
        "min_value": round(min(values), 2) if values else 0,
        "winners":   sum(1 for v in values if v >= 10_000),
    }
    if not traders_ok:
        overall_ok = False

    # ── Base de données SQLite ────────────────────────────────────
    try:
        size_kb = round(os.path.getsize(db_path) / 1024, 1) if Path(db_path).exists() else 0
        with sqlite3.connect(db_path) as conn:
            trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            snaps  = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            last_t = conn.execute("SELECT MAX(timestamp) FROM trades").fetchone()[0]
        checks["database"] = {
            "status":     "ok",
            "size_kb":    size_kb,
            "trades":     trades,
            "snapshots":  snaps,
            "last_trade": last_t,
        }
    except Exception as exc:
        checks["database"] = {"status": "error", "error": str(exc)}
        overall_ok = False

    # ── Desk Liquidité ────────────────────────────────────────────
    try:
        from divisions.middle_office import get_liquidity_desk
        desk   = get_liquidity_desk()
        score  = desk.get_score()
        regime = desk.get_regime()
        checks["liquidity_desk"] = {
            "status": "ok" if score is not None else "initializing",
            "score":  score,
            "regime": regime,
            "bias":   round((score - 5) / 5, 3) if score is not None else None,
        }
    except Exception as exc:
        checks["liquidity_desk"] = {"status": "error", "error": str(exc)}

    # ── WebSocket clients ─────────────────────────────────────────
    checks["websocket"] = {
        "status":  "ok",
        "clients": ws_clients,
    }

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "status":    "healthy" if overall_ok else "degraded",
        "checks":    checks,
    }

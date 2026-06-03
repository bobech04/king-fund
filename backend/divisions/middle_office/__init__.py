"""
Middle Office — service LiquidityDesk.

Expose get_liquidity_desk() : singleton thread-safe avec refresh background
toutes les REFRESH_INTERVAL secondes (defaut 15 min).
"""
import sys
import asyncio
import threading
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Rend desk_liquidite importable comme package depuis divisions/middle_office/
_MIDDLE_OFFICE = Path(__file__).parent
if str(_MIDDLE_OFFICE) not in sys.path:
    sys.path.insert(0, str(_MIDDLE_OFFICE))

REFRESH_INTERVAL = 15 * 60  # secondes


class LiquidityDesk:
    """
    Service singleton qui execute les 8 agents de liquidite en parallele
    et met en cache le resultat.  Thread-safe ; le refresh est non-bloquant.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict | None = None
        self._cache_time: datetime | None = None
        self._refreshing = False

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def get_data(self) -> dict[str, Any]:
        """Retourne les dernieres donnees de liquidite (depuis le cache).
        Declenche un refresh background si le cache est perime."""
        with self._lock:
            if self._cache is not None and self._is_fresh():
                return self._cache
        self.trigger_background_refresh()
        with self._lock:
            return self._cache or {"global_liquidity_score": None, "regime": "inconnu", "error": "initialisation"}

    def get_data_cached_only(self) -> dict[str, Any] | None:
        """Retourne le cache sans declencher de refresh. None si absent."""
        with self._lock:
            return self._cache if self._cache is not None else None

    def get_score(self) -> float | None:
        data = self.get_data_cached_only()
        return data.get("global_liquidity_score") if data else None

    def get_regime(self) -> str | None:
        data = self.get_data_cached_only()
        return data.get("regime") if data else None

    def get_bertez_signal(self) -> float | None:
        data = self.get_data_cached_only()
        return data.get("bertez_signal") if data else None

    def get_bertez_mode(self) -> str | None:
        data = self.get_data_cached_only()
        return data.get("bertez_mode") if data else None

    def trigger_background_refresh(self):
        """Lance un refresh dans un thread daemon — non bloquant, idempotent."""
        with self._lock:
            if self._refreshing or self._is_fresh():
                return
            self._refreshing = True
        t = threading.Thread(target=self._do_refresh, daemon=True, name="liquidite-refresh")
        t.start()

    # ------------------------------------------------------------------
    # Interne
    # ------------------------------------------------------------------

    def _is_fresh(self) -> bool:
        return (
            self._cache_time is not None
            and datetime.utcnow() - self._cache_time < timedelta(seconds=REFRESH_INTERVAL)
        )

    def _do_refresh(self):
        try:
            from desk_liquidite import run_async
            result = asyncio.run(run_async())
            with self._lock:
                self._cache = result
                self._cache_time = datetime.utcnow()
            score = result.get("global_liquidity_score")
            regime = result.get("regime", "?")
            logger.info("LiquidityDesk refreshed — score=%.2f regime=%s", score or 0, regime)
        except Exception as exc:
            logger.error("LiquidityDesk refresh error: %s", exc)
        finally:
            with self._lock:
                self._refreshing = False


_instance: LiquidityDesk | None = None
_instance_lock = threading.Lock()


def get_liquidity_desk() -> LiquidityDesk:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = LiquidityDesk()
    return _instance

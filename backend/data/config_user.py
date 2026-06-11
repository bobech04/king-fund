"""
Configuration utilisateur modifiable sans redémarrage.

Fichier : backend/config_user.json
Hot-reload : rechargé automatiquement si le fichier est plus récent que le cache.
Accès thread-safe via get_config() / update_config().
"""
from __future__ import annotations
import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_FILE = Path(__file__).resolve().parent.parent / "config_user.json"
_lock = threading.Lock()
_cache: dict = {}
_cache_mtime: float = 0.0

_DEFAULTS: dict = {
    "_comment":                "Editable sans redémarrage — rechargé à chaud par King Fund",
    "stop_loss_global_pct":    20.0,
    "budget_max_par_trade_eur": 50.0,
    "budget_journalier_eur":   500.0,
    "seuils_alerte_prix": {
        "VPK.AS":  {"objectif": 50.0,  "stop": 42.0},
        "BIPC":    {"objectif": 40.0,  "stop": 33.0},
        "DNB.OL":  {"objectif": 320.0, "stop": 260.0},
        "TTE.PA":  {"objectif": 65.0,  "stop": 52.0},
        "GTT.PA":  {"objectif": 200.0, "stop": 150.0},
    },
    "mode_trading":       "SIMULATION",
    "capital_reel_eur":   0.0,
    "autonomie": {
        "timeout_heures":          48,
        "pouvoirs_etendus_actifs": False,
        "budget_max_autonome_eur": 200.0,
    },
    "gouvernance": {
        "veto_agd_duree_minutes": 60,
        "log_tous_trades":        False,
        "activer_hook_engine":    True,
    },
    "notifications": {
        "telegram_actif":      True,
        "alertes_niveau_min":  "warning",
    },
    "engine": {
        "tick_interval_sec":   60,
        "max_position_pct":    0.30,
        "sitg_actif":          True,
    },
}


# ── I/O ──────────────────────────────────────────────────────────────────────

def _ensure_file() -> None:
    """Crée le fichier avec les valeurs par défaut s'il n'existe pas."""
    if not _CONFIG_FILE.exists():
        _CONFIG_FILE.write_text(
            json.dumps(_DEFAULTS, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[CONFIG] Fichier config_user.json créé avec valeurs par défaut")


def _reload() -> dict:
    """Force le rechargement depuis le disque."""
    global _cache, _cache_mtime
    _ensure_file()
    try:
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        # Merge avec les defaults pour les clés manquantes
        merged = _deep_merge(_DEFAULTS, data)
        _cache = merged
        _cache_mtime = _CONFIG_FILE.stat().st_mtime
        return _cache
    except Exception as e:
        logger.warning("[CONFIG] Erreur lecture config_user.json: %s", e)
        return dict(_DEFAULTS)


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge récursif — override gagne sur base."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ── API publique ──────────────────────────────────────────────────────────────

def get_config() -> dict:
    """Retourne la config, rechargée si le fichier a changé depuis le dernier accès."""
    global _cache, _cache_mtime
    with _lock:
        _ensure_file()
        try:
            current_mtime = _CONFIG_FILE.stat().st_mtime
        except OSError:
            current_mtime = 0.0

        if not _cache or current_mtime > _cache_mtime:
            _reload()
        return dict(_cache)


def update_config(key_path: str, value) -> dict:
    """
    Met à jour une clé (notation pointée supportée : "autonomie.timeout_heures").
    Écrit immédiatement sur le disque.
    Retourne la config complète mise à jour.
    """
    with _lock:
        _ensure_file()
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = dict(_DEFAULTS)

        # Navigation par clé pointée
        keys = key_path.split(".")
        node = data
        for k in keys[:-1]:
            if k not in node or not isinstance(node[k], dict):
                node[k] = {}
            node = node[k]
        node[keys[-1]] = value

        _CONFIG_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        global _cache, _cache_mtime
        _cache = _deep_merge(_DEFAULTS, data)
        _cache_mtime = _CONFIG_FILE.stat().st_mtime
        logger.info("[CONFIG] %s = %s", key_path, value)
        return dict(_cache)


def update_config_bulk(updates: dict) -> dict:
    """
    Met à jour plusieurs clés en une seule écriture.
    `updates` : {key_path: value, ...}
    """
    with _lock:
        _ensure_file()
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = dict(_DEFAULTS)

        for key_path, value in updates.items():
            keys = key_path.split(".")
            node = data
            for k in keys[:-1]:
                if k not in node or not isinstance(node[k], dict):
                    node[k] = {}
                node = node[k]
            node[keys[-1]] = value

        _CONFIG_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        global _cache, _cache_mtime
        _cache = _deep_merge(_DEFAULTS, data)
        _cache_mtime = _CONFIG_FILE.stat().st_mtime
        return dict(_cache)


def reload_config() -> dict:
    """Force le rechargement. Thread-safe."""
    with _lock:
        return _reload()


def get_config_file_path() -> str:
    return str(_CONFIG_FILE)

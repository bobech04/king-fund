"""
Telegram notifier partagé — Division Gérant Délégué.
"""
from __future__ import annotations
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logger = logging.getLogger(__name__)

_ICON = {
    "critique": "🚨",
    "warning":  "⚠️",
    "info":     "ℹ️",
    "ok":       "✅",
    "rapport":  "📋",
    "veto":     "🛑",
    "comite":   "🏛️",
    "dividende":"💰",
    "bench":    "📊",
    "risk":     "⚖️",
}


def send(message: str, niveau: str = "info") -> bool:
    """Envoie un message Telegram. Retourne True si succès."""
    try:
        from config import TELEGRAM_BOT_TOKEN as _token, TELEGRAM_CHAT_ID as _chat
    except ImportError:
        _token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        _chat  = os.getenv("TELEGRAM_CHAT_ID",  "")

    if not _token or not _chat:
        logger.debug("[Notifier] Telegram non configuré — message ignoré")
        return False

    try:
        import requests as _req
        resp = _req.post(
            f"https://api.telegram.org/bot{_token}/sendMessage",
            json={"chat_id": _chat, "text": message, "parse_mode": "HTML"},
            timeout=8,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.warning("[Notifier] Telegram erreur: %s", e)
        return False


def alerte(titre: str, corps: str, niveau: str = "info") -> bool:
    icon = _ICON.get(niveau, "•")
    return send(f"{icon} <b>{titre}</b>\n{corps}", niveau)

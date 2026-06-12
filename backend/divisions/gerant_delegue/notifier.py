"""
Telegram notifier partagé — Division Gérant Délégué.
Fallback automatique vers email SMTP si Telegram échoue.
"""
from __future__ import annotations
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logger = logging.getLogger(__name__)

# Niveaux qui déclenchent le fallback email (les moins urgents sont ignorés)
_EMAIL_FALLBACK_NIVEAUX = {"critique", "warning", "rapport", "veto", "comite"}

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
    """
    Envoie un message Telegram.
    Si Telegram échoue et que le niveau est suffisant, tente l'email SMTP.
    Retourne True si au moins un canal a réussi.
    """
    try:
        from config import TELEGRAM_BOT_TOKEN as _token, TELEGRAM_CHAT_ID as _chat
    except ImportError:
        _token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        _chat  = os.getenv("TELEGRAM_CHAT_ID",  "")

    telegram_ok = False
    if not _token or not _chat:
        logger.debug("[Notifier] Telegram non configuré")
    else:
        try:
            import requests as _req
            resp = _req.post(
                f"https://api.telegram.org/bot{_token}/sendMessage",
                json={"chat_id": _chat, "text": message, "parse_mode": "HTML"},
                timeout=8,
            )
            resp.raise_for_status()
            telegram_ok = True
        except Exception as e:
            logger.warning("[Notifier] Telegram erreur: %s — tentative email SMTP", e)

    if not telegram_ok and niveau in _EMAIL_FALLBACK_NIVEAUX:
        try:
            from divisions.gerant_delegue.notifier_email import send_email
            # Extrait un sujet court depuis la première ligne du message
            subject = message.split("\n")[0][:80].replace("<b>", "").replace("</b>", "")
            email_ok = send_email(subject, message)
            if email_ok:
                logger.info("[Notifier] Fallback email envoyé (Telegram KO)")
            return email_ok
        except Exception as e:
            logger.warning("[Notifier] Fallback email erreur: %s", e)
            return False

    return telegram_ok


def alerte(titre: str, corps: str, niveau: str = "info") -> bool:
    icon = _ICON.get(niveau, "•")
    return send(f"{icon} <b>{titre}</b>\n{corps}", niveau)

"""
Alerte email de secours — s'active uniquement si Telegram échoue.

Configuration dans backend/.env :
  SMTP_HOST=smtp.office365.com          # Hotmail/Outlook
  SMTP_PORT=587
  SMTP_USER=zoubida.kocheida@hotmail.com
  SMTP_PASSWORD=<mot_de_passe_app>
  ALERT_EMAIL_TO=zoubida.kocheida@hotmail.com

Si vous utilisez Gmail à la place :
  SMTP_HOST=smtp.gmail.com
  SMTP_PORT=587
  SMTP_USER=votre@gmail.com
  SMTP_PASSWORD=<mot_de_passe_application_16_car>   ← générer sur myaccount.google.com
  → Compte Google › Sécurité › Validation en deux étapes › Mots de passe des applis
"""
from __future__ import annotations

import html
import logging
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logger = logging.getLogger(__name__)

# ── Lecture config ─────────────────────────────────────────────────────────────

def _cfg() -> dict:
    """Lit les variables SMTP depuis l'environnement (chargé par config.py / .env)."""
    try:
        from config import ANTHROPIC_API_KEY  # noqa — force le load_dotenv de config.py
    except Exception:
        pass
    return {
        "host":     os.getenv("SMTP_HOST",     ""),
        "port":     int(os.getenv("SMTP_PORT",  "587")),
        "user":     os.getenv("SMTP_USER",     ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "to":       os.getenv("ALERT_EMAIL_TO", ""),
    }


# ── Conversion HTML → texte brut ───────────────────────────────────────────────

def _html_to_text(h: str) -> str:
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", h, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


# ── Envoi ──────────────────────────────────────────────────────────────────────

def send_email(subject: str, body_html: str) -> bool:
    """
    Envoie un email via SMTP (STARTTLS sur le port 587).
    Retourne True si succès, False sinon (sans lever d'exception).
    """
    cfg = _cfg()
    if not all([cfg["host"], cfg["user"], cfg["password"], cfg["to"]]):
        logger.debug("[Email] SMTP non configuré — variables manquantes dans .env")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[King Fund] {subject}"
        msg["From"]    = f"King Fund AGD-01 <{cfg['user']}>"
        msg["To"]      = cfg["to"]

        body_text = _html_to_text(body_html)
        msg.attach(MIMEText(body_text, "plain",  "utf-8"))
        msg.attach(MIMEText(body_html, "html",   "utf-8"))

        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(cfg["user"], cfg["password"])
            smtp.sendmail(cfg["user"], cfg["to"], msg.as_string())

        logger.info("[Email] Alerte envoyée à %s — %s", cfg["to"], subject[:60])
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "[Email] Échec authentification SMTP — vérifiez SMTP_USER/SMTP_PASSWORD."
            " Pour Gmail, générez un mot de passe d'application (16 car.) sur"
            " myaccount.google.com › Sécurité › Validation en deux étapes."
        )
        return False
    except Exception as e:
        logger.warning("[Email] Erreur SMTP: %s", e)
        return False


def alerte_email(titre: str, corps: str, niveau: str = "info") -> bool:
    """Wrapper avec mise en forme HTML minimale."""
    icons = {
        "critique": "🚨", "warning": "⚠️", "info": "ℹ️",
        "ok": "✅", "rapport": "📋", "veto": "🛑",
    }
    icon = icons.get(niveau, "•")
    body = (
        f"<h2>{icon} {titre}</h2>"
        f"<pre style='font-family:monospace;font-size:14px'>{corps}</pre>"
        f"<hr><small>King Fund AGD-01 — alerte de secours email</small>"
    )
    return send_email(f"{icon} {titre}", body)

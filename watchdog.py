"""
Watchdog King Fund — à lancer en parallèle du serveur Flask.
Vérifie /api/maintenance/health toutes les 5 minutes.
Envoie une alerte Telegram si le serveur ne répond plus.
Usage : python watchdog.py [http://localhost:5000]
"""
import os
import sys
import time
import logging
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / "backend" / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [WATCHDOG] %(message)s")
logger = logging.getLogger(__name__)

URL    = (sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:5000") + "/api/maintenance/health"
TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT   = os.getenv("TELEGRAM_CHAT_ID",  "")
INTERVAL = 300   # 5 minutes
RETRIES  = 3     # nombre d'échecs consécutifs avant alerte

_failures = 0


def _telegram(msg: str) -> None:
    if not TOKEN or not CHAT:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=8,
        )
    except Exception as exc:
        logger.warning("Telegram: %s", exc)


def check() -> bool:
    try:
        resp = requests.get(URL, timeout=10)
        return resp.status_code == 200
    except Exception as exc:
        logger.warning("Ping échoué: %s", exc)
        return False


if __name__ == "__main__":
    logger.info("Watchdog démarré — surveillance %s toutes les %ds", URL, INTERVAL)
    _telegram("🐕 <b>Watchdog King Fund démarré</b>\nSurveillance serveur active.")

    while True:
        ok = check()
        if ok:
            if _failures > 0:
                logger.info("Serveur récupéré après %d échec(s)", _failures)
                _telegram("✅ <b>King Fund — Serveur récupéré</b>\nLe serveur répond à nouveau.")
            _failures = 0
            logger.info("OK — serveur opérationnel")
        else:
            _failures += 1
            logger.warning("Échec %d/%d", _failures, RETRIES)
            if _failures >= RETRIES:
                logger.error("SERVEUR HORS LIGNE — alerte Telegram envoyée")
                _telegram(
                    "🚨 <b>KING FUND — SERVEUR HORS LIGNE</b>\n"
                    f"Le serveur ne répond pas depuis {_failures * INTERVAL // 60} minutes.\n"
                    "Redémarrage nécessaire : <code>python backend/app.py</code>"
                )
                _failures = 0  # reset pour éviter le spam
        time.sleep(INTERVAL)

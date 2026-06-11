"""
Backup automatique quotidien de king_fund.db.
Destination : database/backups/king_fund_YYYY-MM-DD_HHhMM.db
Conserve les 30 derniers backups, supprime les anciens.
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_RETENTION = 30  # nombre max de backups conservés


def faire_backup(db_path: Path | None = None) -> Path:
    if db_path is None:
        from config import DB_PATH
        db_path = DB_PATH

    if not db_path.exists():
        raise FileNotFoundError(f"Base de données introuvable : {db_path}")

    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts   = datetime.now().strftime("%Y-%m-%d_%Hh%M")
    dest = backup_dir / f"king_fund_{ts}.db"

    shutil.copy2(db_path, dest)
    logger.info("[Backup] ✓ Copie → %s (%.1f Ko)", dest, dest.stat().st_size / 1024)

    # Nettoyage rotation
    backups = sorted(backup_dir.glob("king_fund_*.db"), key=lambda p: p.stat().st_mtime)
    for old in backups[:-_RETENTION]:
        try:
            old.unlink()
            logger.info("[Backup] Supprimé ancien backup : %s", old.name)
        except Exception as exc:
            logger.warning("[Backup] Impossible de supprimer %s : %s", old.name, exc)

    return dest

"""
Audit AGD-01 — Journal immuable horodaté de toutes les décisions du Gérant Délégué.
Format : JSONL (une ligne JSON par décision), ouverture en mode append-only.
Fichier : logs/audit_agd01.jsonl
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _audit_path() -> Path:
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from config import DB_PATH
        return Path(DB_PATH).parent.parent / "logs" / "audit_agd01.jsonl"
    except Exception:
        return Path(__file__).resolve().parents[3] / "logs" / "audit_agd01.jsonl"


def _last_line_hash(path: Path) -> str:
    """SHA-256 (16 chars) de la dernière ligne pour chaîne d'intégrité."""
    try:
        if not path.exists() or path.stat().st_size == 0:
            return "genesis"
        with open(path, "rb") as f:
            f.seek(max(0, path.stat().st_size - 4096))
            raw  = f.read().rstrip(b"\n")
            last = raw.split(b"\n")[-1]
            return hashlib.sha256(last).hexdigest()[:16]
    except Exception:
        return "unknown"


def log_decision(event_type: str, **kwargs) -> None:
    """
    Enregistre une décision AGD-01 dans le journal JSONL.
    Chaque ligne est une entrée JSON autonome, jamais réécrite (append-only).
    Le champ prev_hash (SHA-256 tronqué) permet la détection de toute
    modification a posteriori (tamper-evident).
    """
    entry: dict = {
        "ts":         datetime.now(timezone.utc).isoformat(),
        "agent":      "AGD-01",
        "event_type": event_type,
    }
    entry.update({k: v for k, v in kwargs.items() if v is not None})

    try:
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            entry["prev_hash"] = _last_line_hash(path)
            line = json.dumps(entry, ensure_ascii=False, default=str)
            with open(path, "a", encoding="utf-8", buffering=1) as fh:
                fh.write(line + "\n")
        logger.debug("[AUDIT AGD-01] %s → %s", event_type, path.name)
    except Exception as e:
        logger.warning("[AUDIT AGD-01] Échec écriture: %s", e)


def get_recent(limit: int = 50) -> list[dict]:
    """Retourne les N dernières entrées du journal (ordre antéchronologique)."""
    try:
        path = _audit_path()
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        entries: list[dict] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
            if len(entries) >= limit:
                break
        return entries
    except Exception as e:
        logger.warning("[AUDIT AGD-01] Lecture: %s", e)
        return []

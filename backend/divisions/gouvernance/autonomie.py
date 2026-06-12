"""
Mode autonomie complète — AGD-01 agit seul si Zoubida ne répond pas dans les 48h.

Flux :
  1. AGD-01 soumet une décision importante → `soumettre_validation()`
  2. Alerte Telegram envoyée avec l'ID de validation + instructions
  3. Si réponse dans les 48h → `confirmer()` ou `rejeter()`
  4. Si pas de réponse → `check_timeouts()` marque AUTONOME et exécute le callback
  5. Chaque décision autonome est loggée dans `logs/autonomie_agd01.jsonl`
"""
from __future__ import annotations
import json
import logging
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_LOG_FILE = Path(__file__).resolve().parents[3] / "logs" / "autonomie_agd01.jsonl"
_STATE_FILE = Path(__file__).resolve().parents[3] / "data" / "gouvernance" / "validations_pending.json"
_lock = threading.Lock()
_instance: "AutonomieManager | None" = None

# Statuts possibles
PENDING   = "PENDING"
VALIDEE   = "VALIDEE"
REJETEE   = "REJETEE"
EXPIREE   = "EXPIREE"
AUTONOME  = "AUTONOME"  # décision prise sans validation de Zoubida


class AutonomieManager:
    """Gestionnaire du mode autonomie AGD-01."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}
        self._pouvoirs_etendus: bool = False
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._charger_pending()

    # ------------------------------------------------------------------
    # Persistance
    # ------------------------------------------------------------------

    def _charger_pending(self) -> None:
        if _STATE_FILE.exists():
            try:
                self._pending = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                self._pending = {}

    def _sauvegarder_pending(self) -> None:
        try:
            _STATE_FILE.write_text(
                json.dumps(self._pending, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("[AUTONOMIE] Save: %s", e)

    # ------------------------------------------------------------------
    # Soumettre une action pour validation Zoubida
    # ------------------------------------------------------------------

    def soumettre_validation(
        self,
        action:      str,
        description: str,
        ticker:      str | None = None,
        montant:     float | None = None,
        urgence:     str = "normal",   # normal | urgent
        callback_id: str | None = None,
    ) -> str:
        """
        Enregistre une validation en attente et envoie l'alerte Telegram.
        Retourne le validation_id.
        """
        try:
            from data.config_user import get_config
            timeout_h = get_config().get("autonomie", {}).get("timeout_heures", 48)
        except Exception:
            timeout_h = 48

        vid = str(uuid.uuid4())[:12]
        now = datetime.utcnow()
        deadline = now + timedelta(hours=timeout_h)

        entry = {
            "id":          vid,
            "action":      action,
            "description": description[:300],
            "ticker":      ticker,
            "montant":     montant,
            "urgence":     urgence,
            "callback_id": callback_id,
            "soumis_ts":   now.isoformat(),
            "deadline_ts": deadline.isoformat(),
            "statut":      PENDING,
        }
        with self._lock:
            self._pending[vid] = entry
            self._sauvegarder_pending()

        self._envoyer_alerte_telegram(entry)
        logger.info("[AUTONOMIE] Validation %s soumise — deadline %s", vid, deadline.strftime("%d/%m %H:%M"))
        return vid

    def _envoyer_alerte_telegram(self, entry: dict) -> None:
        try:
            from divisions.gerant_delegue.notifier import alerte
            urgence_icon = "🚨" if entry["urgence"] == "urgent" else "⏳"
            ticker_str = f" | {entry['ticker']}" if entry['ticker'] else ""
            montant_str = f" | {entry['montant']:.0f}€" if entry.get('montant') else ""
            deadline = datetime.fromisoformat(entry['deadline_ts'])
            msg = (
                f"{urgence_icon} <b>Validation requise — AGD-01</b>\n\n"
                f"<b>Action :</b> {entry['action']}{ticker_str}{montant_str}\n"
                f"<b>Détail :</b> {entry['description'][:200]}\n\n"
                f"<b>ID :</b> <code>{entry['id']}</code>\n"
                f"<b>Deadline :</b> {deadline.strftime('%d/%m/%Y %H:%M')} UTC\n\n"
                f"Répondre via l'onglet Gouvernance ou :\n"
                f"• <code>POST /api/gouvernance/validation/{entry['id']}/valider</code>\n"
                f"• <code>POST /api/gouvernance/validation/{entry['id']}/rejeter</code>\n\n"
                f"⚠️ Sans réponse sous 48h, AGD-01 agira en autonomie complète."
            )
            alerte(msg)
        except Exception as e:
            logger.debug("[AUTONOMIE] Telegram: %s", e)

    # ------------------------------------------------------------------
    # Réponses de Zoubida
    # ------------------------------------------------------------------

    def confirmer(self, validation_id: str) -> bool:
        with self._lock:
            entry = self._pending.get(validation_id)
            if not entry:
                # Recharge depuis le disque (peut avoir été écrit par un autre process)
                self._charger_pending()
                entry = self._pending.get(validation_id)
            if not entry or entry["statut"] != PENDING:
                return False
            entry["statut"] = VALIDEE
            entry["reponse_ts"] = datetime.utcnow().isoformat()
            self._sauvegarder_pending()

        self._log_autonomie({
            "validation_id": validation_id,
            "action": entry["action"],
            "statut": VALIDEE,
            "ticker": entry.get("ticker"),
            "montant": entry.get("montant"),
            "description": entry["description"],
            "decideur": "Zoubida",
        })
        self._notifier_resultat(entry, "✅ VALIDÉE")
        logger.info("[AUTONOMIE] Validation %s VALIDÉE par Zoubida", validation_id)
        return True

    def rejeter(self, validation_id: str, raison: str = "") -> bool:
        with self._lock:
            entry = self._pending.get(validation_id)
            if not entry:
                self._charger_pending()
                entry = self._pending.get(validation_id)
            if not entry or entry["statut"] != PENDING:
                return False
            entry["statut"] = REJETEE
            entry["raison_rejet"] = raison
            entry["reponse_ts"] = datetime.utcnow().isoformat()
            self._sauvegarder_pending()

        self._log_autonomie({
            "validation_id": validation_id,
            "action": entry["action"],
            "statut": REJETEE,
            "ticker": entry.get("ticker"),
            "raison": raison or "Rejetée par Zoubida",
            "decideur": "Zoubida",
        })
        self._notifier_resultat(entry, f"❌ REJETÉE — {raison or 'Sans motif'}")
        return True

    def _notifier_resultat(self, entry: dict, statut_label: str) -> None:
        try:
            from divisions.gerant_delegue.notifier import send
            send(
                f"📋 <b>Validation {entry['id']}</b> : {statut_label}\n"
                f"Action : {entry['action']}"
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Check timeouts — appelé par le scheduler toutes les heures
    # ------------------------------------------------------------------

    def check_timeouts(self) -> list[dict]:
        """Vérifie les validations expirées → passe en AUTONOME."""
        try:
            from data.config_user import get_config
            pouvoirs_ok = get_config().get("autonomie", {}).get("pouvoirs_etendus_actifs", False)
        except Exception:
            pouvoirs_ok = False

        now = datetime.utcnow()
        expirees = []

        with self._lock:
            for vid, entry in list(self._pending.items()):
                if entry["statut"] != PENDING:
                    continue
                deadline = datetime.fromisoformat(entry["deadline_ts"])
                if now >= deadline:
                    entry["statut"] = AUTONOME
                    entry["expire_ts"] = now.isoformat()
                    expirees.append(dict(entry))

            if expirees:
                self._pouvoirs_etendus = True
                self._sauvegarder_pending()

        for entry in expirees:
            logger.warning(
                "[AUTONOMIE] ⚡ Timeout — AGD-01 agit en autonomie : %s",
                entry["action"],
            )
            self._log_autonomie({
                "validation_id": entry["id"],
                "action": entry["action"],
                "statut": AUTONOME,
                "ticker": entry.get("ticker"),
                "montant": entry.get("montant"),
                "description": entry["description"],
                "decideur": "AGD-01 (autonomie 48h)",
                "raison": "Pas de réponse de Zoubida dans le délai imparti",
            })
            self._notifier_autonomie(entry)

        return expirees

    def _notifier_autonomie(self, entry: dict) -> None:
        try:
            from divisions.gerant_delegue.notifier import alerte
            alerte(
                f"⚡ <b>AGD-01 MODE AUTONOMIE</b>\n\n"
                f"Validation <code>{entry['id']}</code> expirée sans réponse.\n"
                f"<b>Action :</b> {entry['action']}\n"
                f"<b>Décision :</b> AGD-01 agit dans les limites des règles de risque.\n\n"
                f"Consultez le journal d'autonomie pour le détail."
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Log décisions autonomes
    # ------------------------------------------------------------------

    def log_decision_autonome(
        self,
        action:   str,
        raison:   str,
        contexte: dict | None = None,
        ticker:   str | None = None,
        montant:  float | None = None,
    ) -> None:
        """Loggue une décision prise en mode autonomie (hors timeout validation)."""
        self._log_autonomie({
            "action":   action,
            "statut":   AUTONOME,
            "ticker":   ticker,
            "montant":  montant,
            "raison":   raison,
            "contexte": contexte or {},
            "decideur": "AGD-01 (autonomie complète)",
        })

    def _log_autonomie(self, data: dict) -> None:
        entry = {
            "ts": datetime.utcnow().isoformat(),
            **data,
        }
        try:
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("[AUTONOMIE] Log file: %s", e)

    # ------------------------------------------------------------------
    # API lecture
    # ------------------------------------------------------------------

    def get_etat(self) -> dict:
        with self._lock:
            self._charger_pending()   # sync depuis le disque à chaque lecture
            pending = [e for e in self._pending.values() if e["statut"] == PENDING]
            pouvoirs = self._pouvoirs_etendus

        try:
            from data.config_user import get_config
            cfg_aut = get_config().get("autonomie", {})
        except Exception:
            cfg_aut = {}

        return {
            "pouvoirs_etendus_actifs":  pouvoirs or cfg_aut.get("pouvoirs_etendus_actifs", False),
            "timeout_heures":           cfg_aut.get("timeout_heures", 48),
            "budget_max_autonome_eur":  cfg_aut.get("budget_max_autonome_eur", 200.0),
            "validations_pending":      len(pending),
            "validations":              list(self._pending.values()),
            "ts": datetime.utcnow().isoformat(),
        }

    def get_log_autonomie(self, limit: int = 50) -> list[dict]:
        if not _LOG_FILE.exists():
            return []
        try:
            lignes = _LOG_FILE.read_text(encoding="utf-8").splitlines()
            entries = []
            for l in reversed(lignes[-limit * 2:]):
                try:
                    entries.append(json.loads(l))
                except Exception:
                    pass
            return entries[:limit]
        except Exception:
            return []


# ── Singleton ─────────────────────────────────────────────────────────────────

def get_autonomie_manager() -> AutonomieManager:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AutonomieManager()
    return _instance

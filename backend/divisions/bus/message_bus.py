"""
Bus de communication inter-agents King Fund.
Pattern Pub/Sub thread-safe.

Catégories de messages :
  ALERTE_CRITIQUE    — urgences (crash détecté, Black Swan, VIX > 35)
  ALERTE_WARNING     — risques élevés (spreads, levier, concentration)
  SIGNAL_MARCHE      — données de marché significatives
  RISQUE_SYSTEMIQUE  — alertes agent systémique
  SIGNAL_TRADER      — signaux entre traders (consensus, divergence)
  MACRO_UPDATE       — mise à jour banques centrales / FRED
  GEOPOLITIQUE       — événements GDELT critiques
  MAINTENANCE        — santé du système
"""
from __future__ import annotations
import json
import logging
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_BUS_LOG_DIR = Path(__file__).parent.parent.parent.parent / "rapports" / "bus"


class CategorieMessage(str, Enum):
    ALERTE_CRITIQUE   = "alerte_critique"
    ALERTE_WARNING    = "alerte_warning"
    SIGNAL_MARCHE     = "signal_marche"
    RISQUE_SYSTEMIQUE = "risque_systemique"
    SIGNAL_TRADER     = "signal_trader"
    MACRO_UPDATE      = "macro_update"
    GEOPOLITIQUE      = "geopolitique"
    MAINTENANCE       = "maintenance"


@dataclass
class BusMessage:
    categorie:        CategorieMessage
    niveau:           str                   # "info" | "warning" | "critique"
    source:           str                   # division émettrice
    titre:            str
    contenu:          dict
    entite:           str        = ""       # entité concernée (ticker, pays, code CB)
    traders_cibles:   list[str] = field(default_factory=list)
    divisions_cibles: list[str] = field(default_factory=list)
    id:               str        = field(default_factory=lambda: _gen_id())
    timestamp:        str        = field(default_factory=lambda: datetime.utcnow().isoformat())
    traite:           bool       = False

    def to_dict(self) -> dict:
        return {
            "id":              self.id,
            "categorie":       self.categorie.value,
            "niveau":          self.niveau,
            "source":          self.source,
            "titre":           self.titre,
            "entite":          self.entite,
            "contenu":         self.contenu,
            "traders_cibles":  self.traders_cibles,
            "divisions_cibles":self.divisions_cibles,
            "timestamp":       self.timestamp,
            "traite":          self.traite,
        }

    def resume(self) -> str:
        return f"[{self.categorie.value.upper()}][{self.niveau}] {self.source} → {self.titre}"


def _gen_id() -> str:
    import uuid
    return str(uuid.uuid4())[:12]


@dataclass
class Abonne:
    division:       str
    categories:     set[CategorieMessage]
    callback:       Callable[[BusMessage], None]
    filtres_niveau: set[str] = field(default_factory=lambda: {"info", "warning", "critique"})
    actif:          bool     = True

    def accepte(self, msg: BusMessage) -> bool:
        if not self.actif:
            return False
        if msg.categorie not in self.categories:
            return False
        if msg.niveau not in self.filtres_niveau:
            return False
        if msg.divisions_cibles and self.division not in msg.divisions_cibles:
            return False
        return True


class MessageBus:
    """
    Bus de communication central — singleton partagé entre toutes les divisions.
    Thread-safe. Livraison asynchrone via ThreadPoolExecutor.
    """

    MAX_HISTORIQUE = 2000

    def __init__(self, async_delivery: bool = True) -> None:
        self._abonnes:    list[Abonne]       = []
        self._historique: deque[BusMessage]  = deque(maxlen=self.MAX_HISTORIQUE)
        self._lock        = threading.RLock()
        self._async       = async_delivery
        self._pool        = None

        if async_delivery:
            from concurrent.futures import ThreadPoolExecutor
            self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="BusWorker")

        _BUS_LOG_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("[MessageBus] Initialisé (async=%s)", async_delivery)

    def publier(self, msg: BusMessage) -> None:
        with self._lock:
            self._historique.append(msg)
            abonnes_touches = [a for a in self._abonnes if a.accepte(msg)]

        self._persister(msg)

        log_fn = logger.critical if msg.niveau == "critique" else (
            logger.warning if msg.niveau == "warning" else logger.info
        )
        log_fn("[Bus] %s", msg.resume())

        for abonne in abonnes_touches:
            if self._async and self._pool:
                self._pool.submit(self._livrer, abonne, msg)
            else:
                self._livrer(abonne, msg)

    def _livrer(self, abonne: Abonne, msg: BusMessage) -> None:
        try:
            abonne.callback(msg)
            msg.traite = True
        except Exception as e:
            logger.warning("[Bus] Erreur livraison → %s : %s", abonne.division, e)

    def souscrire(
        self,
        division:   str,
        categories: list[CategorieMessage],
        callback:   Callable[[BusMessage], None],
        niveaux:    Optional[list[str]] = None,
    ) -> Abonne:
        abonne = Abonne(
            division=division,
            categories=set(categories),
            callback=callback,
            filtres_niveau=set(niveaux or ["info", "warning", "critique"]),
        )
        with self._lock:
            self._abonnes.append(abonne)
        logger.info("[Bus] %s souscrit à %s", division, [c.value for c in categories])
        return abonne

    def desabonner(self, division: str) -> int:
        with self._lock:
            avant = len(self._abonnes)
            self._abonnes = [a for a in self._abonnes if a.division != division]
        return avant - len(self._abonnes)

    def messages_recents(
        self,
        n: int = 50,
        categorie: Optional[CategorieMessage] = None,
        niveau: Optional[str] = None,
        source: Optional[str] = None,
    ) -> list[BusMessage]:
        with self._lock:
            msgs = list(reversed(self._historique))
        if categorie:
            msgs = [m for m in msgs if m.categorie == categorie]
        if niveau:
            msgs = [m for m in msgs if m.niveau == niveau]
        if source:
            msgs = [m for m in msgs if m.source == source]
        return msgs[:n]

    def alertes_critiques(self, n: int = 20) -> list[BusMessage]:
        return self.messages_recents(n=n, niveau="critique")

    def messages_pour_trader(self, trader_id: str, n: int = 20) -> list[BusMessage]:
        with self._lock:
            msgs = [m for m in reversed(self._historique)
                    if trader_id in m.traders_cibles]
        return msgs[:n]

    def etat(self) -> dict:
        with self._lock:
            nb_msgs    = len(self._historique)
            nb_abonnes = len(self._abonnes)
            critiques  = sum(1 for m in self._historique if m.niveau == "critique")
            par_cat    = defaultdict(int)
            for m in self._historique:
                par_cat[m.categorie.value] += 1

        return {
            "nb_messages":      nb_msgs,
            "nb_abonnes":       nb_abonnes,
            "critiques_actifs": critiques,
            "par_categorie":    dict(par_cat),
            "async":            self._async,
            "timestamp":        datetime.utcnow().isoformat(),
        }

    def division_abonnees(self) -> list[str]:
        with self._lock:
            return list({a.division for a in self._abonnes if a.actif})

    def _persister(self, msg: BusMessage) -> None:
        if msg.niveau not in ("critique", "warning"):
            return
        try:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            chemin   = _BUS_LOG_DIR / f"bus_{date_str}.jsonl"
            with chemin.open("a", encoding="utf-8") as f:
                f.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("[Bus] Erreur persistance : %s", e)

    def __del__(self):
        if self._pool:
            self._pool.shutdown(wait=False)

"""Connecteurs prêts-à-l'emploi pour chaque division du King Fund."""
from __future__ import annotations
import logging
from typing import Callable, Optional

from .message_bus import MessageBus, BusMessage, CategorieMessage

logger = logging.getLogger(__name__)

ABONNEMENTS_PAR_DEFAUT: dict[str, list[CategorieMessage]] = {
    "investissement":    [CategorieMessage.ALERTE_CRITIQUE, CategorieMessage.ALERTE_WARNING,
                          CategorieMessage.RISQUE_SYSTEMIQUE, CategorieMessage.MACRO_UPDATE,
                          CategorieMessage.SIGNAL_TRADER, CategorieMessage.SIGNAL_MARCHE],
    "banques_centrales": [CategorieMessage.MACRO_UPDATE, CategorieMessage.ALERTE_CRITIQUE,
                          CategorieMessage.GEOPOLITIQUE, CategorieMessage.ALERTE_WARNING],
    "experts_sectoriels":[CategorieMessage.ALERTE_CRITIQUE, CategorieMessage.ALERTE_WARNING,
                          CategorieMessage.SIGNAL_MARCHE, CategorieMessage.GEOPOLITIQUE],
    "middle_office":     [CategorieMessage.ALERTE_CRITIQUE, CategorieMessage.ALERTE_WARNING,
                          CategorieMessage.RISQUE_SYSTEMIQUE, CategorieMessage.MAINTENANCE,
                          CategorieMessage.SIGNAL_MARCHE],
    "black_swan":        [CategorieMessage.ALERTE_CRITIQUE],
    "engine":            [CategorieMessage.ALERTE_CRITIQUE, CategorieMessage.ALERTE_WARNING,
                          CategorieMessage.MACRO_UPDATE, CategorieMessage.SIGNAL_MARCHE],
}


class ConnecteurDivision:
    def __init__(self, division: str, bus: MessageBus) -> None:
        self._division = division
        self._bus      = bus
        self._abonne   = None

    def connecter(
        self,
        callback:   Optional[Callable[[BusMessage], None]] = None,
        categories: Optional[list[CategorieMessage]] = None,
        niveaux:    Optional[list[str]] = None,
    ) -> "ConnecteurDivision":
        if callback is None:
            callback = self._callback_defaut
        cats = categories or ABONNEMENTS_PAR_DEFAUT.get(self._division, [
            CategorieMessage.ALERTE_CRITIQUE, CategorieMessage.ALERTE_WARNING
        ])
        self._abonne = self._bus.souscrire(
            division=self._division,
            categories=cats,
            callback=callback,
            niveaux=niveaux or ["warning", "critique"],
        )
        return self

    def publier_critique(self, titre: str, contenu: dict, entite: str = "",
                         traders_cibles: Optional[list[str]] = None,
                         divisions_cibles: Optional[list[str]] = None) -> None:
        self._bus.publier(BusMessage(
            categorie=CategorieMessage.ALERTE_CRITIQUE,
            niveau="critique",
            source=self._division,
            titre=titre, contenu=contenu,
            entite=entite,
            traders_cibles=traders_cibles or [],
            divisions_cibles=divisions_cibles or [],
        ))

    def publier_warning(self, titre: str, contenu: dict, entite: str = "",
                        traders_cibles: Optional[list[str]] = None,
                        categorie: CategorieMessage = CategorieMessage.ALERTE_WARNING) -> None:
        self._bus.publier(BusMessage(
            categorie=categorie,
            niveau="warning",
            source=self._division,
            titre=titre, contenu=contenu,
            entite=entite,
            traders_cibles=traders_cibles or [],
        ))

    def publier_info(self, titre: str, contenu: dict,
                     categorie: CategorieMessage = CategorieMessage.SIGNAL_MARCHE,
                     entite: str = "",
                     traders_cibles: Optional[list[str]] = None) -> None:
        self._bus.publier(BusMessage(
            categorie=categorie,
            niveau="info",
            source=self._division,
            titre=titre, contenu=contenu,
            entite=entite,
            traders_cibles=traders_cibles or [],
        ))

    def _callback_defaut(self, msg: BusMessage) -> None:
        fn = logger.critical if msg.niveau == "critique" else (
            logger.warning if msg.niveau == "warning" else logger.info
        )
        fn("[%s ← Bus] %s", self._division, msg.resume())


def creer_connecteur(division: str, bus: MessageBus) -> ConnecteurDivision:
    conn = ConnecteurDivision(division, bus)
    conn.connecter()
    return conn

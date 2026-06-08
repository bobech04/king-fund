"""Bus de communication inter-agents King Fund (Pub/Sub thread-safe)."""
from .message_bus import MessageBus, BusMessage, CategorieMessage
from .connecteurs import ConnecteurDivision, creer_connecteur, ABONNEMENTS_PAR_DEFAUT

__all__ = [
    "MessageBus", "BusMessage", "CategorieMessage",
    "ConnecteurDivision", "creer_connecteur", "ABONNEMENTS_PAR_DEFAUT",
    "get_bus",
]

_bus_global: MessageBus | None = None


def get_bus() -> MessageBus:
    global _bus_global
    if _bus_global is None:
        _bus_global = MessageBus(async_delivery=True)
    return _bus_global

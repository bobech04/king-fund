"""
divisions.banques_centrales
===========================
Registre des 20 modules banques centrales.

Usage :
    from divisions.banques_centrales import REGISTRY, get_all_signals, get_signal

    signals = get_all_signals()           # liste de 20 dicts
    fed     = get_signal("FED")           # dict d'une banque
    inst    = REGISTRY["BCE"]             # instance BCE (méthodes .rate(), .sentiment(), …)
"""

from .fed      import FederalReserve
from .bce      import BCE
from .boj      import BOJ
from .pbc      import PBC
from .rbi      import RBI
from .boe      import BOE
from .snb      import SNB
from .rba      import RBA
from .bcb      import BCB
from .norges   import NorgesBank
from .riksbank import Riksbank
from .sarb     import SARB
from .tcmb     import TCMB
from .sama     import SAMA
from .cbuae    import CBUAE
from .cbn      import CBN
from .boc      import BOC
from .bok      import BOK
from .fmi      import FMI
from .bri      import BRI

REGISTRY: dict = {
    "FED":     FederalReserve(),
    "BCE":     BCE(),
    "BOJ":     BOJ(),
    "PBC":     PBC(),
    "RBI":     RBI(),
    "BOE":     BOE(),
    "SNB":     SNB(),
    "RBA":     RBA(),
    "BCB":     BCB(),
    "NORGES":  NorgesBank(),
    "RIKSBANK":Riksbank(),
    "SARB":    SARB(),
    "TCMB":    TCMB(),
    "SAMA":    SAMA(),
    "CBUAE":   CBUAE(),
    "CBN":     CBN(),
    "BOC":     BOC(),
    "BOK":     BOK(),
    "FMI":     FMI(),
    "BRI":     BRI(),
}


def get_all_signals() -> list[dict]:
    """Retourne les signaux des 20 banques centrales sous forme de liste."""
    return [bank.signal() for bank in REGISTRY.values()]


def get_signal(code: str) -> dict:
    """Retourne le signal d'une banque par son code (ex. 'FED', 'BCE')."""
    bank = REGISTRY.get(code.upper())
    return bank.signal() if bank else {}


__all__ = ["REGISTRY", "get_all_signals", "get_signal"]

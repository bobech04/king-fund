"""
Division Gérant Délégué — King Fund
Orchestre AGD-01 et les 5 agents du Bloc 1.
"""
from __future__ import annotations

from divisions.gerant_delegue.agd_01        import get_gerant_delegue,     AgentGerantDelegue
from divisions.gerant_delegue.agent_actualites import get_agent_actualites,  AgentActualites
from divisions.gerant_delegue.agent_dividendes import get_agent_dividendes,  AgentDividendes
from divisions.gerant_delegue.agent_risk_parity import get_agent_risk_parity, AgentRiskParity
from divisions.gerant_delegue.agent_benchmark  import get_agent_benchmark,   AgentBenchmark
from divisions.gerant_delegue.comite_selection import get_comite_selection,  ComiteSelection

__all__ = [
    "get_gerant_delegue",     "AgentGerantDelegue",
    "get_agent_actualites",   "AgentActualites",
    "get_agent_dividendes",   "AgentDividendes",
    "get_agent_risk_parity",  "AgentRiskParity",
    "get_agent_benchmark",    "AgentBenchmark",
    "get_comite_selection",   "ComiteSelection",
]


def etat_division() -> dict:
    """Retourne l'état consolidé de toute la division."""
    try:
        agd = get_gerant_delegue().etat()
    except Exception:
        agd = {"erreur": "AGD-01 indisponible"}
    try:
        actualites = get_agent_actualites().etat()
    except Exception:
        actualites = {}
    try:
        dividendes = get_agent_dividendes().etat()
    except Exception:
        dividendes = {}
    try:
        risk_parity = get_agent_risk_parity().etat()
    except Exception:
        risk_parity = {}
    try:
        benchmark = get_agent_benchmark().etat()
    except Exception:
        benchmark = {}
    try:
        comite = get_comite_selection().etat()
    except Exception:
        comite = {}

    return {
        "division":      "Gérant Délégué",
        "agd_01":        agd,
        "actualites":    actualites,
        "dividendes":    dividendes,
        "risk_parity":   risk_parity,
        "benchmark":     benchmark,
        "comite":        comite,
    }

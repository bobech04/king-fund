"""
AgentRapport — rédige via Claude API un rapport 1 page par candidat.

Chaque rapport est :
  • Une analyse institutionnelle complète (thèse, valorisation, risques, catalyseurs)
  • Sauvegardé en texte dans rapports/research/YYYY-MM-DD/ticker.txt
  • Soumis à Division Investissement via le bus de messages
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RAPPORTS_DIR = Path(__file__).resolve().parents[4] / "rapports" / "research"

_SYSTEM_PROMPT = """\
Tu es un analyste sell-side sénior dans une banque d'investissement de premier rang,
titulaire d'un CFA Level 3, spécialiste de l'analyse fondamentale Graham-Buffett-Damodaran.
Rédige des rapports concis, factuels et institutionnels. Jamais de formules de politesse.
Toujours conclure par une recommandation tranchée : ACHAT / CONSERVER / VENTE."""

_USER_PROMPT = """\
Rédige un rapport d'analyse de {ticker} — {nom} ({marche}).

DONNÉES QUANTITATIVES :
• Score pipeline 17 étapes : {score_pipeline}/10
• Score final (avec EDGAR) : {score_final}/10
• Signal : {signal}
• Score Graham composite : {score_graham}/100
• Prix actuel : {prix}
• WACC Damodaran : {wacc}%
• Valeur DCF (Gordon Growth) : {valeur_dcf}
• Marge de sécurité DCF : {marge_dcf}%
• Marge de sécurité analyste : {marge_analyste}%
• PER : {per} | PBR : {pbr}
• Dividende : {dividende}%
• D/E : {dette_equity}
• Croissance revenus : {croissance_rev}%
• Secteur : {secteur} | Pays : {pays}

EDGAR (filings SEC) :
• FCF réel : {fcf_real}
• Dette LT : {lt_debt}
• Accruals ratio : {accruals}

SCORES DES 17 ÉTAPES :
{stages_text}

FORMAT DU RAPPORT (1 page, max 500 mots) :
1. THÈSE D'INVESTISSEMENT (2-3 phrases)
2. VALORISATION (DCF, multiples, marge de sécurité)
3. ATOUTS FONDAMENTAUX (3 points clés issus du pipeline)
4. RISQUES MAJEURS (2-3 risques)
5. CATALYSEURS (2 éléments déclencheurs potentiels)
6. RECOMMANDATION FINALE : {signal} — justifiée en 1 phrase

Langue : français, terminologie institutionnelle. Pas de titre "Rapport" ou de sections en gras.
"""


class AgentRapport:
    """
    Génère un rapport textuel par candidat via Claude claude-sonnet-4-6.
    Sauvegarde sur disque et soumet au bus Division Investissement.
    """

    def __init__(self) -> None:
        self._lock   = threading.Lock()
        self._client = None
        self._init_client()

    def _init_client(self):
        try:
            import sys
            from pathlib import Path as _Path
            sys.path.insert(0, str(_Path(__file__).parent.parent.parent))
            from config import ANTHROPIC_API_KEY
            import anthropic
            if ANTHROPIC_API_KEY:
                self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                logger.info("[AgentRapport] Client Anthropic initialisé")
        except Exception as e:
            logger.warning("[AgentRapport] Client Anthropic non disponible: %s", e)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def generer_rapports(self, analyses: list[dict]) -> list[dict[str, Any]]:
        """Génère un rapport par analyse, retourne liste enrichie avec rapport."""
        resultats = []
        date_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dossier   = _RAPPORTS_DIR / date_str
        dossier.mkdir(parents=True, exist_ok=True)

        for analyse in analyses:
            ticker = analyse.get("ticker", "UNKNOWN")
            logger.info("[AgentRapport] Rédaction rapport %s", ticker)
            rapport_txt = self._generer_un(analyse)
            chemin      = dossier / f"{ticker.replace('.', '_')}.txt"
            chemin.write_text(rapport_txt, encoding="utf-8")
            self._soumettre_bus(ticker, analyse, rapport_txt)

            resultats.append({
                **analyse,
                "rapport":        rapport_txt,
                "rapport_chemin": str(chemin),
            })

        logger.info("[AgentRapport] %d rapports générés dans %s", len(resultats), dossier)
        return resultats

    # ------------------------------------------------------------------
    # Génération Claude
    # ------------------------------------------------------------------

    def _generer_un(self, analyse: dict) -> str:
        if self._client is None:
            return self._rapport_fallback(analyse)

        edgar  = analyse.get("edgar", {})
        stages = analyse.get("stages", [])
        stages_text = "\n".join(
            f"  {i+1:02d}. {s['name']} : {s['score']:+.3f}"
            for i, s in enumerate(stages[:16])
        )

        def fmt(val, suffix=""):
            if val is None or val == "":
                return "—"
            return f"{val}{suffix}"

        prompt = _USER_PROMPT.format(
            ticker       = analyse.get("ticker", ""),
            nom          = analyse.get("nom", ""),
            marche       = analyse.get("marche", ""),
            score_pipeline = fmt(analyse.get("score_pipeline")),
            score_final  = fmt(analyse.get("score_final")),
            signal       = fmt(analyse.get("signal")),
            score_graham = fmt(analyse.get("score_graham")),
            prix         = fmt(analyse.get("prix")),
            wacc         = fmt(analyse.get("wacc")),
            valeur_dcf   = fmt(analyse.get("valeur_dcf")),
            marge_dcf    = fmt(analyse.get("marge_securite_dcf")),
            marge_analyste = fmt(analyse.get("marge_securite_analyste")),
            per          = fmt(analyse.get("per")),
            pbr          = fmt(analyse.get("pbr")),
            dividende    = fmt(analyse.get("dividende")),
            dette_equity = fmt(analyse.get("dette_equity")),
            croissance_rev = fmt(analyse.get("croissance_rev")),
            secteur      = fmt(analyse.get("secteur")),
            pays         = fmt(analyse.get("pays")),
            fcf_real     = fmt(edgar.get("fcf_real")),
            lt_debt      = fmt(edgar.get("lt_debt")),
            accruals     = fmt(edgar.get("accruals_ratio")),
            stages_text  = stages_text or "  (non disponible)",
        )

        try:
            from agents.formation import enrichir_systeme
            system = enrichir_systeme(_SYSTEM_PROMPT)
        except Exception:
            system = _SYSTEM_PROMPT

        try:
            msg = self._client.messages.create(
                model      = "claude-sonnet-4-6",
                max_tokens = 700,
                system     = system,
                messages   = [{"role": "user", "content": prompt}],
            )
            return msg.content[0].text.strip()
        except Exception as e:
            logger.warning("[AgentRapport] Claude error %s: %s", analyse.get("ticker"), e)
            return self._rapport_fallback(analyse)

    def _rapport_fallback(self, analyse: dict) -> str:
        """Rapport minimaliste si Claude API indisponible."""
        return (
            f"RAPPORT — {analyse.get('ticker')} | {analyse.get('nom')}\n"
            f"Score : {analyse.get('score_final')}/10 | Signal : {analyse.get('signal')}\n"
            f"WACC : {analyse.get('wacc')}% | DCF : {analyse.get('valeur_dcf')}\n"
            f"Marge de sécurité DCF : {analyse.get('marge_securite_dcf')}%\n"
            f"PER : {analyse.get('per')} | PBR : {analyse.get('pbr')} | Div : {analyse.get('dividende')}%\n"
            f"[Rapport Claude API indisponible — données brutes ci-dessus]"
        )

    # ------------------------------------------------------------------
    # Soumission Division Investissement via bus
    # ------------------------------------------------------------------

    def _soumettre_bus(self, ticker: str, analyse: dict, rapport: str):
        try:
            import sys
            from pathlib import Path as _Path
            sys.path.insert(0, str(_Path(__file__).parent.parent.parent))
            from divisions.bus import get_bus
            from divisions.bus.message_bus import BusMessage, CategorieMessage

            bus = get_bus()
            msg = BusMessage(
                categorie  = CategorieMessage.SIGNAL_EXPERT,
                source     = "Research.AgentRapport",
                cible      = "Division.Investissement",
                payload    = {
                    "ticker":      ticker,
                    "signal":      analyse.get("signal"),
                    "score_final": analyse.get("score_final"),
                    "rapport":     rapport[:500],   # extrait
                },
            )
            bus.publier(msg)
            logger.debug("[AgentRapport] Message bus publié pour %s", ticker)
        except Exception as e:
            logger.debug("[AgentRapport] Bus indisponible: %s", e)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: AgentRapport | None = None
_lock = threading.Lock()


def get_agent_rapport() -> AgentRapport:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AgentRapport()
    return _instance
